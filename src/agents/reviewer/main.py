import asyncio
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv

from agent_framework import ChatMessage
from agent_framework.observability import get_tracer
from fastapi import FastAPI, HTTPException
from fastmcp import FastMCP
from pydantic import BaseModel, Field

from agents.common.a2a_hosting import mount_a2a_text_agent
from agents.common.azure_ai import AgentRuntime, create_azure_ai_agent_client
from agents.common.mcp_hosting import combine_lifespans, mount_mcp_tools
from agents.common.telemetry import enable_observability
from agents.common.text import chat_response_text


load_dotenv()


class InvokeRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=4000)
    draft: str = Field(min_length=1, max_length=20000)


class InvokeResponse(BaseModel):
    reviewed: str
    changes_made: bool


_runtime: AgentRuntime | None = None


# Initialize MCP server
mcp = FastMCP(
    name=os.getenv("REVIEWER_AGENT_NAME", "reviewer-agent"),
    instructions=os.getenv(
        "REVIEWER_AGENT_DESCRIPTION",
        "Reviews and improves a writer draft for a given topic.",
    ),
)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    ai_project_endpoint = os.getenv("AZURE_AI_PROJECT_ENDPOINT", None)
    if ai_project_endpoint:
        await enable_observability(ai_project_endpoint=ai_project_endpoint)
    
    with get_tracer(__name__).start_as_current_span("agent_startup") as span:
        global _runtime
        _runtime = create_azure_ai_agent_client(
            agent_name=os.getenv("REVIEWER_AGENT_NAME", "reviewer-agent"),
            agent_description=os.getenv(
                "REVIEWER_AGENT_DESCRIPTION",
                "Reviews and improves a writer draft for a given topic.",
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


combined_lifespan, mcp_app = combine_lifespans(_lifespan, mcp)

app = FastAPI(
    title="reviewer-agent",
    lifespan=combined_lifespan,
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


# Register MCP tool
@mcp.tool()
async def review_summary(topic: str, draft: str) -> dict:
    """Reviews and improves a draft summary for clarity and correctness.
    
    This tool takes a topic and a draft summary, then reviews and improves the draft
    for better clarity, correctness, and concision. It fixes grammar, removes redundancy,
    and ensures the content stays faithful to the topic.
    
    Args:
        topic: The topic of the summary (1-4000 characters)
        draft: The draft summary to review (1-20000 characters)
    
    Returns:
        dict: {
            "reviewed": str - The improved summary text,
            "changes_made": bool - Whether any changes were made to the draft
        }
        
    Raises:
        RuntimeError: If the service is not initialized
        TimeoutError: If the model call exceeds the timeout
        Exception: If the model call fails for other reasons
    """
    if _runtime is None:
        raise RuntimeError("Service not initialized")
    
    reviewed = await _review_draft(topic, draft)
    changes_made = reviewed != draft.strip()
    return {"reviewed": reviewed, "changes_made": changes_made}


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


# Mount MCP tools
mount_mcp_tools(app, mcp_app, prefix="/mcp")


@app.get("/mcp-info", tags=["MCP"])
async def mcp_info() -> dict[str, object]:
    """Get information about available MCP tools.
    
    The Model Context Protocol (MCP) endpoint is available at /mcp.
    This endpoint provides information about the MCP tools exposed by this agent.
    
    Returns:
        Information about available MCP tools and how to use them.
    """
    return {
        "protocol": "Model Context Protocol (MCP)",
        "endpoint": "/mcp",
        "tools": [
            {
                "name": "review_summary",
                "description": "Reviews and improves a draft summary for clarity and correctness.",
                "parameters": {
                    "topic": {
                        "type": "string",
                        "description": "The topic of the summary (1-4000 characters)",
                        "required": True,
                    },
                    "draft": {
                        "type": "string",
                        "description": "The draft summary to review (1-20000 characters)",
                        "required": True,
                    },
                },
                "returns": {
                    "reviewed": {
                        "type": "string",
                        "description": "The improved summary text",
                    },
                    "changes_made": {
                        "type": "boolean",
                        "description": "Whether any changes were made to the draft",
                    },
                },
            }
        ],
        "usage": {
            "description": "Connect an MCP client to this endpoint to use the tools",
            "examples": [
                "Claude Desktop",
                "VS Code with MCP extension",
                "Custom MCP clients",
            ],
        },
    }


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
