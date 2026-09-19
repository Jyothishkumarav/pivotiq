"""WhatsApp channel — simulated until a real provider (e.g. Meta Cloud API,
Twilio) is wired in. Kept behind the same `NotificationSender` interface so
swapping in a live implementation later doesn't touch the processor/registry.
"""

import logging
import uuid

from app.channels.base import NotificationSender, SendResult
from app.models.notification import Recipient

logger = logging.getLogger(__name__)


class WhatsAppSender(NotificationSender):
    def send(self, recipient: Recipient, title: str, data: str, reference: str) -> SendResult:
        if not recipient.whatsapp_number:
            return SendResult(success=False, error="recipient.whatsappNumber is required for the whatsapp channel")

        logger.info(
            "[whatsapp:simulated] to=%s title=%s ref=%s body=%s", recipient.whatsapp_number, title, reference, data
        )
        return SendResult(success=True, provider_message_id=f"simulated-{uuid.uuid4()}")
