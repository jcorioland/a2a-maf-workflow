import asyncio
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv

from agent_framework import ChatMessage
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from agents.common.a2a_hosting import mount_a2a_text_agent
from agents.common.azure_ai import AgentRuntime, create_azure_ai_agent_client
from agents.common.telemetry import instrument_fastapi, enable_observability
from agents.common.text import chat_response_text


load_dotenv()


class InvokeRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=4000)
    draft: str = Field(min_length=1, max_length=20000)


class InvokeResponse(BaseModel):
    reviewed: str
    changes_made: bool


_runtime: AgentRuntime | None = None


@asynccontextmanager
async def _lifespan(app: FastAPI):
    ai_project_endpoint = os.getenv("AI_PROJECT_ENDPOINT", None)
    if ai_project_endpoint:
        await enable_observability(ai_project_endpoint=ai_project_endpoint)
    
    instrument_fastapi(app)

    global _runtime
    _runtime = create_azure_ai_agent_client(
        agent_name=os.getenv("REVIEWER_AGENT_NAME", "reviewer-agent"),
        agent_description=os.getenv(
            "REVIEWER_AGENT_DESCRIPTION",
            "Reviews and improves a writer draft for a given topic.",
        ),
    )

    try:
        yield
    finally:
        if _runtime is not None:
            await _runtime.client.close()
            await _runtime.credential.close()
            _runtime = None


app = FastAPI(
    title="reviewer-agent",
    lifespan=_lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)


def _parse_review_input(text: str) -> tuple[str, str]:
    """Parse reviewer input from a plain text message.

    Supported formats (in order):
    - "Topic: ...\n\nDraft: ..."
    - First line is topic, remaining lines are draft
    - Single line: topic==draft==text
    """

    raw = text.strip()
    lower = raw.lower()
    topic_idx = lower.find("topic:")
    draft_idx = lower.find("draft:")
    if topic_idx != -1 and draft_idx != -1 and topic_idx < draft_idx:
        topic = raw[topic_idx + len("topic:") : draft_idx].strip()
        draft = raw[draft_idx + len("draft:") :].strip()
        if topic and draft:
            return topic, draft

    lines = raw.splitlines()
    if len(lines) >= 2:
        topic = lines[0].strip()
        draft = "\n".join(lines[1:]).strip()
        return topic or raw, draft or raw

    return raw, raw


mount_a2a_text_agent(
    app=app,
    name=os.getenv("REVIEWER_AGENT_NAME", "reviewer-agent"),
    description=os.getenv(
        "REVIEWER_AGENT_DESCRIPTION",
        "Reviews and improves a writer draft for a given topic.",
    ),
    skill_id="review-summary",
    skill_name="Review summary",
    skill_description="Reviews and improves a draft summary for clarity and correctness.",
    skill_tags=["review", "editing", "summarization"],
    respond=lambda text, _context_id: _review_draft(*_parse_review_input(text)),
)


@app.get("/healthz")
async def healthz() -> dict[str, object]:
    return {
        "status": "ok",
        "service": os.getenv("SERVICE_NAME", "reviewer-agent"),
        "initialized": _runtime is not None,
    }


async def _review_draft(topic: str, draft: str) -> str:
    if _runtime is None:
        raise HTTPException(status_code=503, detail="service not initialized")

    system_prompt = (
        "You are a careful reviewer. Improve the draft summary for clarity, correctness, and concision. "
        "Fix grammar, remove redundancy, and keep it faithful to the topic. "
        "Return only the improved summary text; do not add commentary."
    )
    user_prompt = (
        f"Topic: {topic}\n\n"
        "Draft summary:\n"
        f"{draft}\n\n"
        "Produce the improved summary now."
    )

    messages = [
        ChatMessage("system", text=system_prompt),
        ChatMessage("user", text=user_prompt),
    ]

    timeout_s = float(os.getenv("AGENT_TIMEOUT_SECONDS", "30"))
    max_tokens = int(os.getenv("AGENT_MAX_TOKENS", "500"))
    temperature = float(os.getenv("AGENT_TEMPERATURE", "0.2"))

    try:
        response = await asyncio.wait_for(
            _runtime.client.get_response(
                messages,
                max_tokens=max_tokens,
                temperature=temperature,
            ),
            timeout=timeout_s,
        )
    except TimeoutError:
        raise HTTPException(status_code=504, detail="model call timed out")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"model call failed: {exc}")

    return chat_response_text(response).strip()


@app.post("/invoke", response_model=InvokeResponse)
async def invoke(payload: InvokeRequest) -> InvokeResponse:
    reviewed = await _review_draft(payload.topic, payload.draft)
    changes_made = reviewed != payload.draft.strip()
    return InvokeResponse(reviewed=reviewed, changes_made=changes_made)
