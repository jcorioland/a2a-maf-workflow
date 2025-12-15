from __future__ import annotations

from agent_framework._types import ChatResponse


def chat_response_text(response: ChatResponse) -> str:
    """Best-effort extraction of plain text from Agent Framework chat responses."""

    text = response.text
    if text is None:
        return ""
    return str(text)
