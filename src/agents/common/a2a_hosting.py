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
from fastapi import FastAPI


def _env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    if not value:
        return default
    return value.strip()


def _join_url(base: str, path: str) -> str:
    base = base.rstrip("/")
    path = "/" + path.lstrip("/")
    return f"{base}{path}"


def _new_id() -> str:
    return uuid.uuid4().hex


def _message_text(message: Message) -> str:
    chunks: list[str] = []
    for part in message.parts:
        root = part.root
        if isinstance(root, TextPart):
            chunks.append(root.text)
    return "\n".join(chunks).strip()


class _TextA2ARequestHandler(RequestHandler):
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
        incoming = params.message
        context_id = incoming.context_id or _new_id()
        user_text = _message_text(incoming)
        try:
            response_text = await self._respond(user_text, context_id)
        except Exception as exc:
            # The A2A server stack isn't FastAPI-aware; if an agent raises an
            # HTTPException (or anything else), translate it into a plain text
            # response instead of crashing the request with a 500.
            response_text = f"Error: {exc}"

        return Message(
            role=self._agent_role,
            parts=[Part(root=TextPart(text=response_text))],
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
    """

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
