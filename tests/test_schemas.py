import pytest
from pydantic import ValidationError

from app.schemas import ChatMessage, ChatRequest


def test_chat_request_requires_messages():
    with pytest.raises(ValidationError):
        ChatRequest(model="mock-1", messages=[])


def test_chat_message_requires_content():
    with pytest.raises(ValidationError):
        ChatMessage(role="user", content="")

