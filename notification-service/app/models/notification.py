"""Wire-format schemas for the notification hub.

`NotificationChannel` intentionally includes channels that aren't wired to a
real provider yet (whatsapp, rcs) — the API contract is stable for external
callers from day one; only the internal sender behind each channel changes
as providers are added.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class NotificationChannel(str, Enum):
    telegram = "telegram"
    normal = "normal"  # plain SMS / text message
    whatsapp = "whatsapp"
    email = "email"
    rcs = "rcs"


class ChannelStatus(str, Enum):
    pending = "PENDING"
    processing = "PROCESSING"
    sent = "SENT"
    failed = "FAILED"


class OverallStatus(str, Enum):
    accepted = "ACCEPTED"
    processing = "PROCESSING"
    sent = "SENT"  # every requested channel succeeded
    partially_sent = "PARTIALLY_SENT"  # some channels succeeded, some failed
    failed = "FAILED"  # every requested channel failed


class Recipient(BaseModel):
    """Contact info; only the fields relevant to the requested channels need to be set."""

    name: str | None = None
    email: str | None = None
    phone: str | None = None
    telegram_chat_id: str | None = Field(default=None, alias="telegramChatId")
    whatsapp_number: str | None = Field(default=None, alias="whatsappNumber")

    model_config = {"populate_by_name": True}


class NotificationRequest(BaseModel):
    """Payload any external system posts to `/api/v1/notifications`."""

    channels: list[NotificationChannel] = Field(min_length=1)
    recipient: Recipient
    title: str = Field(min_length=1, max_length=200)
    data: str = Field(min_length=1, description="The notification body/message content")
    reference: str = Field(min_length=1, description="Caller-supplied correlation id, e.g. an order or alert id")
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("channels")
    @classmethod
    def _dedupe_channels(cls, value: list[NotificationChannel]) -> list[NotificationChannel]:
        seen = list(dict.fromkeys(value))
        return seen


class ChannelResult(BaseModel):
    channel: NotificationChannel
    status: ChannelStatus
    provider_message_id: str | None = None
    error: str | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class NotificationRecord(BaseModel):
    """Full server-side state for one notification request, keyed by `notf_req_id`."""

    notf_req_id: str
    reference: str
    title: str
    data: str
    recipient: Recipient
    metadata: dict[str, Any] = Field(default_factory=dict)
    overall_status: OverallStatus
    channel_results: dict[NotificationChannel, ChannelResult]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class NotificationAcceptedResponse(BaseModel):
    notf_req_id: str
    status: OverallStatus
    accepted_at: datetime


class NotificationStatusResponse(BaseModel):
    notf_req_id: str
    reference: str
    overall_status: OverallStatus
    channels: list[ChannelResult]
    created_at: datetime
    updated_at: datetime
