import os
from dataclasses import dataclass

from agent_framework.azure import AzureAIAgentClient
from azure.identity.aio import DefaultAzureCredential


@dataclass(frozen=True)
class AgentRuntime:
    credential: DefaultAzureCredential
    client: AzureAIAgentClient


def _optional_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip()
    return value if value else None


def create_azure_ai_agent_client(*, agent_name: str, agent_description: str) -> AgentRuntime:
    """Create a long-lived Azure AI Foundry agent client using Managed Identity (DefaultAzureCredential).

    Required env vars (as expected by Agent Framework):
    - `AZURE_AI_PROJECT_ENDPOINT`
    - `AZURE_AI_MODEL_DEPLOYMENT_NAME`

    Optional:
    - `AZURE_AI_AGENT_ID` (if you want to reuse an existing persistent agent)
    """

    credential = DefaultAzureCredential()

    client = AzureAIAgentClient(
        credential=credential,
        agent_id=_optional_env("AZURE_AI_AGENT_ID"),
        agent_name=agent_name,
        agent_description=agent_description,
        # Picked up by AzureAISettings via env vars; can be overridden here if desired.
        project_endpoint=_optional_env("AZURE_AI_PROJECT_ENDPOINT"),
        model_deployment_name=_optional_env("AZURE_AI_MODEL_DEPLOYMENT_NAME"),
    )

    return AgentRuntime(credential=credential, client=client)
