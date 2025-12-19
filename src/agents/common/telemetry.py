import logging

from agent_framework.observability import setup_observability
from azure.ai.projects.aio import AIProjectClient
from azure.identity.aio import DefaultAzureCredential as AsyncDefaultAzureCredential

_telemetry_configured = False

logger = logging.getLogger(__name__)


async def enable_observability(*, ai_project_endpoint: str) -> None:
    """Configure OpenTelemetry export to AI Foundry / Application Insights."""

    global _telemetry_configured
    if _telemetry_configured:
        return

    credential = AsyncDefaultAzureCredential()
    try:
        async with AIProjectClient(
            endpoint=ai_project_endpoint,
            credential=credential,
        ) as client:
            try:
                connection_string = await client.telemetry.get_application_insights_connection_string()
            except Exception as exc:
                # Missing Foundry permissions is a common case in new deployments.
                # Telemetry is optional for runtime correctness, so we don't fail startup.
                logger.warning(
                    "Telemetry setup skipped (could not read Application Insights connection string): %s",
                    exc,
                )
                return

            if not connection_string:
                return

            # Enable Microsoft Agent Framework observability
            setup_observability(
                enable_sensitive_data=True,
                applicationinsights_connection_string=connection_string,
            )

            _telemetry_configured = True
    finally:
        await credential.close()
