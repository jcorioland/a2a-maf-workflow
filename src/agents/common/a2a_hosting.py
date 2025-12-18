"""Helpers to host an A2A agent inside a FastAPI app.

This module provides a thin adapter layer between:
- an agent implementation that takes/returns plain text, and
- the preview A2A REST server implementation from the `a2a` Python SDK.

Why this exists:
- The A2A SDK expects a `RequestHandler` implementation.
- Our agents in this repo are "text in -> text out".
- We mount an A2A sub-application (under `/a2a` by default) onto each agent's
    existing FastAPI app.

The main entrypoint is `mount_a2a_text_agent`.
"""

import logging
import os
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable

from a2a.server.apps.rest.fastapi_app import A2ARESTFastAPIApplication
from a2a.server.request_handlers.request_handler import RequestHandler
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentSkill,
    Message,
    MessageSendParams,
    Part,
    Role,
    Task,
    TaskIdParams,
    TaskPushNotificationConfig,
    TaskQueryParams,
    TextPart,
    TransportProtocol,
    UnsupportedOperationError,
)
from a2a.utils.errors import ServerError
from agent_framework.observability import get_tracer
from fastapi import FastAPI


logger = logging.getLogger(__name__)


def _env_str(name: str, default: str) -> str:
    """Read a string environment variable and normalize whitespace."""
    value = os.getenv(name)
    if not value:
        return default
    return value.strip()


def _join_url(base: str, path: str) -> str:
    """Join a base URL and path with exactly one slash between."""
    base = base.rstrip("/")
    path = "/" + path.lstrip("/")
    return f"{base}{path}"


def _new_id() -> str:
    """Generate IDs for A2A messages/contexts."""
    return uuid.uuid4().hex


def _message_text(message: Message) -> str:
    """Extract plain text from an A2A `Message`.

    The A2A `Message.parts` can contain multiple modalities; in this repo we only
    support text. Non-text parts are ignored.
    """
    chunks: list[str] = []
    for part in message.parts:
        root = part.root
        if isinstance(root, TextPart):
            chunks.append(root.text)
    return "\n".join(chunks).strip()


class _TextA2ARequestHandler(RequestHandler):
    """A2A request handler that adapts text messages to a simple `respond` hook.

    The `respond` function represents the actual business logic of the agent.
    It receives the user text plus a `context_id` (conversation/thread id) and
    returns the agent's response text.

    Notes for reviewers:
    - We implement only the subset of the A2A surface area we need.
    - Unsupported endpoints explicitly raise `UnsupportedOperationError`.
    - Streaming is implemented as a single-message stream (one chunk). This keeps
      the protocol surface available even though we don't stream incremental tokens.
    """

    def __init__(
        self,
        *,
        respond: Callable[[str, str | None], Awaitable[str]],
        agent_role: Role = Role.agent,
    ) -> None:
        self._respond = respond
        self._agent_role = agent_role

    async def on_get_task(
        self,
        params: TaskQueryParams,
        context=None,
    ) -> Task | None:
        return None

    async def on_cancel_task(
        self,
        params: TaskIdParams,
        context=None,
    ) -> Task | None:
        return None

    async def on_message_send(
        self,
        params: MessageSendParams,
        context=None,
    ) -> Message:
        with get_tracer(__name__).start_as_current_span("a2a_on_message_send") as span:
            span.set_attribute("a2a.message_id", params.message.message_id or "unknown")
            span.set_attribute("a2a.context_id", params.message.context_id or "unknown")
            # A2A request payload -> our agent function signature.
            incoming = params.message
            context_id = incoming.context_id or _new_id()
            user_text = _message_text(incoming)

            # We deliberately catch all exceptions here:
            # - The A2A server stack isn't FastAPI-aware.
            # - If the agent raises `HTTPException` (or any other exception), letting it
            #   bubble up tends to become a generic 500 without a user-friendly payload.
            # - Returning a textual error keeps the caller workflow moving and makes it
            #   easier to debug during local development.

            # By default we *don't* include exception details in the response (to avoid
            # accidentally leaking secrets). Opt in with `A2A_INCLUDE_ERROR_DETAILS=true`.
            include_error_details = _env_str("A2A_INCLUDE_ERROR_DETAILS", "false").lower() in (
                "1",
                "true",
                "yes",
                "y",
            )
            try:
                response_text = await self._respond(user_text, context_id)
            except Exception as exc:
                logger.exception("A2A agent handler error")
                response_text = "Error: internal server error"
                if include_error_details:
                    response_text = f"Error: {type(exc).__name__}: {exc}"

            return Message(
                role=self._agent_role,
                parts=[Part(root=TextPart(text=response_text))],
                # The A2A SDK models use camelCase aliases for JSON, but the Python
                # field names are snake_case. Pydantic takes care of serialization.
                message_id=_new_id(),
                context_id=context_id,
            )

    async def on_message_send_stream(
        self,
        params: MessageSendParams,
        context=None,
    ) -> AsyncGenerator[Message, None]:
        yield await self.on_message_send(params, context)

    async def on_set_task_push_notification_config(
        self,
        params: TaskPushNotificationConfig,
        context=None,
    ) -> TaskPushNotificationConfig:
        raise ServerError(error=UnsupportedOperationError())

    async def on_get_task_push_notification_config(
        self,
        params,
        context=None,
    ) -> TaskPushNotificationConfig:
        raise ServerError(error=UnsupportedOperationError())

    async def on_resubscribe_to_task(
        self,
        params: TaskIdParams,
        context=None,
    ) -> AsyncGenerator[Message, None]:
        raise ServerError(error=UnsupportedOperationError())
        yield

    async def on_list_task_push_notification_config(
        self,
        params,
        context=None,
    ) -> list[TaskPushNotificationConfig]:
        raise ServerError(error=UnsupportedOperationError())

    async def on_delete_task_push_notification_config(
        self,
        params,
        context=None,
    ) -> None:
        raise ServerError(error=UnsupportedOperationError())


def mount_a2a_text_agent(
    *,
    app: FastAPI,
    name: str,
    description: str,
    skill_id: str,
    skill_name: str,
    skill_description: str,
    skill_tags: list[str],
    respond: Callable[[str, str | None], Awaitable[str]],
    base_path: str = "/a2a",
    version: str = "0.1.0",
) -> None:
    """Mount an A2A REST server at `base_path` on an existing FastAPI app.

    This uses the preview A2A server implementation from the `a2a` Python SDK.

        Environment variables:
        - `A2A_PUBLIC_URL`: Public base URL used in the advertised `AgentCard.url`.
            Important for discovery: some clients use the card's URL for subsequent calls.
            In local dev you often want a host+port like `http://127.0.0.1:8000`.
        - `A2A_INCLUDE_ERROR_DETAILS`: If true, include exception details in the textual
            error response returned to clients.
    """

    if not base_path.startswith("/"):
        raise ValueError("base_path must start with '/'")

    public_base_url = _env_str("A2A_PUBLIC_URL", "http://localhost")
    public_url = _join_url(public_base_url, base_path)

    agent_card = AgentCard(
        name=name,
        description=description,
        version=version,
        url=public_url,
        preferred_transport=TransportProtocol.http_json.value,
        capabilities=AgentCapabilities(streaming=True, push_notifications=False),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=[
            AgentSkill(
                id=skill_id,
                name=skill_name,
                description=skill_description,
                tags=skill_tags,
            )
        ],
    )

    http_handler = _TextA2ARequestHandler(respond=respond)
    server = A2ARESTFastAPIApplication(agent_card=agent_card, http_handler=http_handler)

    a2a_app = server.build(title=f"{name} (A2A)")
    app.mount(base_path, a2a_app)
