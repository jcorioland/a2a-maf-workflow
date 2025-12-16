import asyncio
from agent_framework import AgentRunUpdateEvent, WorkflowBuilder, WorkflowOutputEvent, WorkflowRunResult
import httpx
from agent_framework.a2a import A2AAgent
from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.types import AgentCard, TransportProtocol
from typing import cast


def _normalize_card_url(card: AgentCard, expected_base_url: str) -> AgentCard:
    """Ensure the AgentCard.url matches the reachable A2A base URL.

    In local dev it's easy to accidentally advertise `http://localhost/a2a` (port 80)
    which breaks message send, even if the card itself was fetched from a different
    host/port.
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
    config = ClientConfig(
        httpx_client=http_client,
        streaming=False,
        supported_transports=[TransportProtocol.http_json],
    )
    factory = ClientFactory(config)
    return factory.create(agent_card)

async def main():
    async with httpx.AsyncClient(timeout=60.0) as http_client:
        writer_agent = await create_writer_agent(http_client)
        reviewer_agent = await create_reviewer_agent(http_client)

        workflow = (
            WorkflowBuilder()
                .add_agent(writer_agent, output_response=True)
                .add_agent(reviewer_agent, output_response=True)
                .set_start_executor(writer_agent)
                .add_edge(source=writer_agent, target=reviewer_agent)
                .build()
        )

        last_executor_id: str | None = None

        events = workflow.run_stream("Tell me more about Microsoft.")
        async for event in events:
            if isinstance(event, AgentRunUpdateEvent):
                eid = event.executor_id
                if eid != last_executor_id:
                    if last_executor_id is not None:
                        print()
                    print(f"{eid}:", end=" ", flush=True)
                    last_executor_id = eid
                print(event.data, end="", flush=True)
            elif isinstance(event, WorkflowOutputEvent):
                print("\n===== Final output =====")
                print(event.data)

async def create_writer_agent(http_client):
    writer_base_url = "http://127.0.0.1:8000/a2a"
    writer_card_resolver = A2ACardResolver(httpx_client=http_client, base_url=writer_base_url)
    writer_card: AgentCard = await writer_card_resolver.get_agent_card()
    writer_card = _normalize_card_url(writer_card, writer_base_url)
    print(f"Discovered writer agent: {writer_card.name} - {writer_card.description}")

    writer_client = _create_rest_client(http_client=http_client, agent_card=writer_card)
    writer_agent = A2AAgent(
            name=writer_card.name,
            description=writer_card.description,
            client=writer_client,
        )
    
    return writer_agent

async def create_reviewer_agent(http_client):
    reviewer_base_url = "http://127.0.0.1:8001/a2a"
    reviewer_card_resolver = A2ACardResolver(httpx_client=http_client, base_url=reviewer_base_url)
    reviewer_card: AgentCard = await reviewer_card_resolver.get_agent_card()
    reviewer_card = _normalize_card_url(reviewer_card, reviewer_base_url)
    print(f"Discovered reviewer agent: {reviewer_card.name} - {reviewer_card.description}")

    reviewer_client = _create_rest_client(http_client=http_client, agent_card=reviewer_card)
    reviewer_agent = A2AAgent(
            name=reviewer_card.name,
            description=reviewer_card.description,
            client=reviewer_client,
        )
    
    return reviewer_agent
    

if __name__ == "__main__":
    asyncio.run(main())