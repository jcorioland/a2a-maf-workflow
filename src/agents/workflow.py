import asyncio
from agent_framework import WorkflowBuilder
import httpx
from agent_framework.a2a import A2AAgent
from a2a.client import A2ACardResolver
from a2a.types import AgentCard

async def main():
    async with httpx.AsyncClient(timeout=60.0) as http_client:
        writer_card_resolver = A2ACardResolver(httpx_client=http_client, base_url="http://localhost:8000/a2a")
        writer_card: AgentCard = await writer_card_resolver.get_agent_card()
        print(f"Discovered writer agent: {writer_card.name} - {writer_card.description}")

        writer_agent = A2AAgent(
            name=writer_card.name,
            description=writer_card.description,
            agent_card=writer_card,
            url="http://localhost:8000/a2a",
            http_client=http_client
        )

        capabilities_response = await writer_agent.run("What are your capabilities?")
        for message in capabilities_response.messages:
            print(f"Writer agent says: {message.text}")

        reviewer_card_resolver = A2ACardResolver(httpx_client=http_client, base_url="http://localhost:8001/a2a")
        reviewer_card: AgentCard = await reviewer_card_resolver.get_agent_card()
        print(f"Discovered reviewer agent: {reviewer_card.name} - {reviewer_card.description}")

        reviewer_agent = A2AAgent(
            name=reviewer_card.name,
            description=reviewer_card.description,
            agent_card=reviewer_card,
            url="http://localhost:8001/a2a",
            http_client=http_client
        )

        workflow = (
            WorkflowBuilder()
                .add_edge(source=writer_agent, target=reviewer_agent)
                .set_start_executor(writer_agent)
                .build()
        )

        response = await workflow.run("Generate and review a summary about the impact of climate change on polar bears.")
        print("workflow_output:\n")
        print(response)
    

if __name__ == "__main__":
    asyncio.run(main())