""""Normal" plain-text/SMS channel — simulated until a real SMS gateway
(Twilio, MSG91, etc.) is wired in.
"""

import logging
import uuid

from app.channels.base import NotificationSender, SendResult
from app.models.notification import Recipient

logger = logging.getLogger(__name__)


class SmsSender(NotificationSender):
    def send(self, recipient: Recipient, title: str, data: str, reference: str) -> SendResult:
        if not recipient.phone:
            return SendResult(success=False, error="recipient.phone is required for the normal (SMS) channel")

        logger.info("[sms:simulated] to=%s title=%s ref=%s body=%s", recipient.phone, title, reference, data)
        return SendResult(success=True, provider_message_id=f"simulated-{uuid.uuid4()}")
