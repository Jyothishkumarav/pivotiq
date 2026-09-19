"""Accepts an inbound notification request: logs it, records it with PENDING
per-channel status, enqueues it for the subscriber, and returns immediately.
"""

import logging
import uuid
from datetime import datetime, timezone

from app.models.notification import (
    ChannelResult,
    ChannelStatus,
    NotificationAcceptedResponse,
    NotificationRecord,
    NotificationRequest,
    NotificationStatusResponse,
    OverallStatus,
)
from app.queue.base import MessageQueue
from app.store.base import NotificationStore

logger = logging.getLogger(__name__)


class NotificationService:
    def __init__(self, message_queue: MessageQueue, store: NotificationStore) -> None:
        self._queue = message_queue
        self._store = store

    def accept(self, request: NotificationRequest) -> NotificationAcceptedResponse:
        notf_req_id = str(uuid.uuid4())
        accepted_at = datetime.now(timezone.utc)

        logger.info(
            "accepted notification notf_req_id=%s ref=%s channels=%s",
            notf_req_id,
            request.reference,
            [c.value for c in request.channels],
        )

        record = NotificationRecord(
            notf_req_id=notf_req_id,
            reference=request.reference,
            title=request.title,
            data=request.data,
            recipient=request.recipient,
            metadata=request.metadata,
            overall_status=OverallStatus.accepted,
            channel_results={
                channel: ChannelResult(channel=channel, status=ChannelStatus.pending) for channel in request.channels
            },
            created_at=accepted_at,
            updated_at=accepted_at,
        )
        self._store.create(record)

        self._queue.publish(
            {
                "notf_req_id": notf_req_id,
                "reference": request.reference,
                "title": request.title,
                "data": request.data,
                "recipient": request.recipient.model_dump(by_alias=False),
                "channels": [c.value for c in request.channels],
                "metadata": request.metadata,
            }
        )

        return NotificationAcceptedResponse(notf_req_id=notf_req_id, status=OverallStatus.accepted, accepted_at=accepted_at)

    def get_status(self, notf_req_id: str) -> NotificationStatusResponse | None:
        record = self._store.get(notf_req_id)
        if record is None:
            return None
        return NotificationStatusResponse(
            notf_req_id=record.notf_req_id,
            reference=record.reference,
            overall_status=record.overall_status,
            channels=list(record.channel_results.values()),
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
