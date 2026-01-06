"""Example workflow using MCP agents with Microsoft Agent Framework.

This demonstrates how to use MCPAgent wrapper to integrate MCP tools
into Agent Framework workflows using WorkflowBuilder.

Note: This is a proof-of-concept showing MCP integration. In this implementation,
the workflow successfully calls both agents in sequence, but there's a known issue
with message content extraction in the current version of the agent framework.
The agents execute correctly (as evidenced by the HTTP logs), but the final
message extraction needs additional work.
"""

import asyncio
import re
import shutil
import textwrap
import uuid
import logging
import os

from agents.common.telemetry import enable_observability
from agent_framework import AgentRunUpdateEvent, MCPStreamableHTTPTool, WorkflowBuilder, WorkflowOutputEvent
from agent_framework.observability import get_tracer
from agent_framework.azure import AzureAIAgentClient
from azure.identity.aio import DefaultAzureCredential

def _wrap_for_console(text: object, *, indent: str = "  ") -> str:
    width = shutil.get_terminal_size(fallback=(100, 24)).columns
    width = max(40, width)

    raw = str(text).strip()
    if not raw:
        return ""

    paragraphs = [p for p in re.split(r"\n\s*\n", raw) if p.strip()]
    wrapped: list[str] = []
    for paragraph in paragraphs:
        normalized = re.sub(r"\s+", " ", paragraph).strip()
        wrapped.append(
            textwrap.fill(
                normalized,
                width=width,
                initial_indent=indent,
                subsequent_indent=indent,
                break_long_words=False,
                break_on_hyphens=False,
            )
        )
    return "\n\n".join(wrapped)

async def main() -> None:
    """Run the MCP-based workflow using Agent Framework."""
    # Make console output less noisy (agent_framework logs a warning when an executor has no outgoing edges).
    logging.getLogger("agent_framework._workflows._runner").setLevel(logging.ERROR)

     # Enable telemetry if configured.
    ai_project_endpoint = os.getenv("AZURE_AI_PROJECT_ENDPOINT")
    if ai_project_endpoint:
        await enable_observability(
            ai_project_endpoint=ai_project_endpoint,
        )

    writer_base_url = os.getenv("WRITER_MCP_BASE_URL", "http://localhost:8000/mcp")
    reviewer_base_url = os.getenv("REVIEWER_MCP_BASE_URL", "http://localhost:8001/mcp")

    writer_tool = MCPStreamableHTTPTool(
        name="writer-tool",
        description="Writes summaries on various topics",
        url=writer_base_url,
    )
    reviewer_tool = MCPStreamableHTTPTool(
        name="reviewer-tool",
        description="Reviews and improves summaries",
        url=reviewer_base_url,
    )
    
    writer_agent = AzureAIAgentClient(
        credential=DefaultAzureCredential(),
        agent_name="writer-agent",
        agent_description="You are a helpful assistant that writes summaries on various topics.",
    ).create_agent(
        name="writer-agent",
        description="You are a helpful assistant that writes summaries on various topics.",
        tools=[writer_tool],
    )
    reviewer_agent = AzureAIAgentClient(
        credential=DefaultAzureCredential(),
        agent_name="reviewer-agent",
        agent_description="You are a helpful assistant that reviews and improves summaries.",
    ).create_agent(
        name="reviewer-agent",
        description="You are a helpful assistant that reviews and improves summaries.",
        tools=[reviewer_tool],
    )

    with get_tracer(__name__).start_as_current_span("workflow_execution") as span:
        span.set_attribute("writer_agent.url", writer_base_url)
        span.set_attribute("reviewer_agent.url", reviewer_base_url)
    
        # Define the workflow graph:
        # - writer is the start node
        # - reviewer executes after writer
        workflow = (
            WorkflowBuilder()
                .register_agent(lambda: writer_agent, "writer_agent", output_response=True)
                .register_agent(lambda: reviewer_agent, "reviewer_agent", output_response=True)
                .set_start_executor("writer_agent")
                .add_edge(source="writer_agent", target="reviewer_agent")
                .build()
        )

        # Run the workflow in a prompt loop.
        # Note: use asyncio.to_thread to avoid blocking the event loop on stdin.
        while True:
            try:
                user_prompt = await asyncio.to_thread(
                    input,
                    "\nEnter a prompt for the workflow (or type 'exit' to quit): ",
                )
            except (EOFError, KeyboardInterrupt):
                print("\nExiting.")
                break

            user_prompt = (user_prompt or "").strip()
            if not user_prompt:
                continue
            if user_prompt.lower() == "exit":
                print("Exiting.")
                break

            run_id = str(uuid.uuid4())
            with get_tracer(__name__).start_as_current_span(f"workflow_execution/{run_id}") as run_span:
                run_span.set_attribute("workflow.run_id", run_id)
                run_span.set_attribute("workflow.prompt", user_prompt)

                # Run the workflow and print readable blocks per executor output.
                last_output_source: str | None = None
                final_output_source: str | None = None
                events = workflow.run_stream(user_prompt)
                async for event in events:
                    if isinstance(event, AgentRunUpdateEvent):
                        # Ignore per-token streaming updates to keep console output readable.
                        # (Final blocks are printed from WorkflowOutputEvent below.)
                        continue
                    elif isinstance(event, WorkflowOutputEvent):
                        source = getattr(event, "source_executor_id", None) or "unknown"
                        if source != last_output_source:
                            if last_output_source is not None:
                                print()
                            print(f"## {source} ##:\n")
                            last_output_source = source

                        wrapped = _wrap_for_console(event.data)
                        if wrapped:
                            print(wrapped)
                        else:
                            print("  (no output)")

                        final_output_source = source

                if final_output_source is not None:
                    print(f"\n===== Final output: {final_output_source} =====")


if __name__ == "__main__":
    asyncio.run(main())
