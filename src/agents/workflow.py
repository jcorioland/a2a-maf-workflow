"""Example workflow runner wiring two A2A agents (writer -> reviewer).

This script:
- Discovers each agent via its AgentCard (fetched from the agent's `/a2a` base URL)
- Creates an A2A REST client for each agent
- Builds a simple two-step workflow where the writer runs first, then reviewer
- Streams intermediate updates to stdout and prints the final output

The base URLs can be overridden via environment variables:
- WRITER_A2A_BASE_URL (default: http://localhost:8000/a2a)
- REVIEWER_A2A_BASE_URL (default: http://localhost:8001/a2a)
"""

import asyncio
import logging
import os
import re
import shutil
import textwrap
from agent_framework import AgentRunUpdateEvent, WorkflowBuilder, WorkflowOutputEvent
import httpx
from agent_framework.a2a import A2AAgent
from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.types import AgentCard, TransportProtocol
from typing import cast


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


def _normalize_card_url(card: AgentCard, expected_base_url: str) -> AgentCard:
    """Ensure the AgentCard.url matches the reachable A2A base URL.

    In local dev it's easy to accidentally advertise `http://localhost/a2a` (port 80)
    which breaks message send, even if the card itself was fetched from a different
    host/port.

    Why this matters:
    - We fetch the AgentCard from a known-good URL (e.g. http://127.0.0.1:8000/a2a)
    - The AgentCard may *advertise* a different URL
    - The A2A client uses the card's URL for subsequent calls
    - If the advertised URL is unreachable, workflow execution fails later
    """

    expected_base_url = expected_base_url.rstrip("/")
    actual_url = (card.url or "").rstrip("/")
    if actual_url == expected_base_url:
        return card

    # AgentCard is a Pydantic model; prefer model_copy when available (v2).
    model_copy = getattr(card, "model_copy", None)
    if callable(model_copy):
        return cast(AgentCard, model_copy(update={"url": expected_base_url}))

    # Fallback for older versions.
    card.url = expected_base_url
    return card


def _create_rest_client(*, http_client: httpx.AsyncClient, agent_card: AgentCard):
    """Create an A2A REST client bound to the given agent card.

    Notes:
    - We keep `streaming=False` because the workflow itself is already streamed via
      `workflow.run_stream(...)` and we only need non-streaming A2A HTTP JSON calls
      per agent execution.
    - `supported_transports` is restricted to HTTP JSON to match our deployment.
    """
    config = ClientConfig(
        httpx_client=http_client,
        streaming=False,
        supported_transports=[TransportProtocol.http_json],
    )
    factory = ClientFactory(config)
    return factory.create(agent_card)


async def _fetch_reviewer_card(http_client, a2a_base_url: str) -> AgentCard:
    """Fetch an agent card from an A2A base URL and normalize its advertised URL."""
    a2a_card_resolver = A2ACardResolver(httpx_client=http_client, base_url=a2a_base_url)
    agent_card: AgentCard = await a2a_card_resolver.get_agent_card()
    agent_card = _normalize_card_url(agent_card, a2a_base_url)
    return agent_card


def _create_agent_from_card(http_client, agent_card: AgentCard) -> A2AAgent:
    """Create an agent using its AgentCard and wrap it as an `A2AAgent`."""
    agent_client = _create_rest_client(http_client=http_client, agent_card=agent_card)
    a2a_agent = A2AAgent(
        name=agent_card.name,
        description=agent_card.description,
        client=agent_client,
    )

    return a2a_agent


async def main():
    """Entrypoint: create agents, build workflow, and stream results to stdout."""
    # Make console output less noisy (agent_framework logs a warning when an executor has no outgoing edges).
    logging.getLogger("agent_framework._workflows._runner").setLevel(logging.ERROR)

    async with httpx.AsyncClient(timeout=60.0) as http_client:
        # Discover writer agent.
        writer_base_url = os.getenv("WRITER_A2A_BASE_URL", "http://localhost:8000/a2a")
        writer_card = await _fetch_reviewer_card(http_client, writer_base_url)
        print(f"Discovered writer agent: {writer_card.name} - {writer_card.description} - {writer_card.url}")
        
        # Discover reviewer agent.
        reviewer_base_url = os.getenv("REVIEWER_A2A_BASE_URL", "http://localhost:8001/a2a")
        reviewer_card = await _fetch_reviewer_card(http_client, reviewer_base_url)
        print(f"Discovered reviewer agent: {reviewer_card.name} - {reviewer_card.description} - {reviewer_card.url}")

        executor_id_to_name = {
            "writer_agent": writer_card.name,
            "reviewer_agent": reviewer_card.name,
        }

        # Define the workflow graph:
        # - writer is the start node
        # - reviewer executes after writer
        workflow = (
            WorkflowBuilder()
                .register_agent(lambda: _create_agent_from_card(http_client, writer_card), "writer_agent", output_response=True)
                .register_agent(lambda: _create_agent_from_card(http_client, reviewer_card), "reviewer_agent", output_response=True)
                .set_start_executor("writer_agent")
                .add_edge(source="writer_agent", target="reviewer_agent")
                .build()
        )

        # Run the workflow and print readable blocks per executor output.
        last_output_source: str | None = None
        final_output_source: str | None = None
        events = workflow.run_stream("Tell me more about Microsoft.")
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
                    display = executor_id_to_name.get(source, source)
                    print(f"## {display} ##:\n")
                    last_output_source = source

                wrapped = _wrap_for_console(event.data)
                if wrapped:
                    print(wrapped)
                else:
                    print("  (no output)")

                final_output_source = executor_id_to_name.get(source, source)

        if final_output_source is not None:
            print(f"\n===== Final output: {final_output_source} =====")

if __name__ == "__main__":
    asyncio.run(main())