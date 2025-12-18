import asyncio
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv

from agent_framework import ChatMessage
from agent_framework.observability import get_tracer
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from agents.common.a2a_hosting import mount_a2a_text_agent
from agents.common.azure_ai import AgentRuntime, create_azure_ai_agent_client
from agents.common.telemetry import enable_observability
from agents.common.text import chat_response_text


load_dotenv()


class InvokeRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=4000)


class InvokeResponse(BaseModel):
    summary: str


_runtime: AgentRuntime | None = None


@asynccontextmanager
async def _lifespan(app: FastAPI):
    ai_project_endpoint = os.getenv("AZURE_AI_PROJECT_ENDPOINT", None)
    if ai_project_endpoint:
        await enable_observability(ai_project_endpoint=ai_project_endpoint)

    with get_tracer(__name__).start_as_current_span("agent_startup") as span:
        global _runtime
        _runtime = create_azure_ai_agent_client(
            agent_name=os.getenv("WRITER_AGENT_NAME", "writer-agent"),
            agent_description=os.getenv(
                "WRITER_AGENT_DESCRIPTION",
                "Writes a short summary for a user-provided topic.",
            ),
        )

        span.set_attribute("agent.name", str(_runtime.client.agent_name))

        try:
            yield
        finally:
            if _runtime is not None:
                await _runtime.client.close()
                await _runtime.credential.close()
                _runtime = None


app = FastAPI(
    title="writer-agent",
    lifespan=_lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)


async def _write_summary(topic: str) -> str:
    if _runtime is None:
        raise HTTPException(status_code=503, detail="service not initialized")

    system_prompt = (
        "You are a helpful writer. Produce a short, factual summary of the given topic. "
        "Keep it concise (roughly 6-10 sentences). Avoid speculation; if unsure, say so."
    )
    user_prompt = f"Topic: {topic}\n\nWrite the summary now."

    messages = [
        ChatMessage("system", text=system_prompt),
        ChatMessage("user", text=user_prompt),
    ]

    timeout_s = float(os.getenv("AGENT_TIMEOUT_SECONDS", "30"))
    max_tokens = int(os.getenv("AGENT_MAX_TOKENS", "400"))
    temperature = float(os.getenv("AGENT_TEMPERATURE", "0.3"))

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


mount_a2a_text_agent(
    app=app,
    name=os.getenv("WRITER_AGENT_NAME", "writer-agent"),
    description=os.getenv(
        "WRITER_AGENT_DESCRIPTION",
        "Writes a short summary for a user-provided topic.",
    ),
    skill_id="write-summary",
    skill_name="Write summary",
    skill_description="Writes a short, factual summary for a topic.",
    skill_tags=["writing", "summarization"],
    respond=lambda text, _context_id: _write_summary(text),
)


@app.get("/healthz")
async def healthz() -> dict[str, object]:
    return {
        "status": "ok",
        "service": os.getenv("SERVICE_NAME", "writer-agent"),
        "initialized": _runtime is not None,
    }


@app.post("/invoke", response_model=InvokeResponse)
async def invoke(payload: InvokeRequest) -> InvokeResponse:
    summary = await _write_summary(payload.topic)
    return InvokeResponse(summary=summary)
