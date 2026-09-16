"""RCS (Rich Communication Services) channel — simulated until a real
provider (e.g. Google Business Messages / carrier RCS API) is wired in.
"""

import logging
import uuid

from app.channels.base import NotificationSender, SendResult
from app.models.notification import Recipient

logger = logging.getLogger(__name__)


class RcsSender(NotificationSender):
    def send(self, recipient: Recipient, title: str, data: str, reference: str) -> SendResult:
        if not recipient.phone:
            return SendResult(success=False, error="recipient.phone is required for the rcs channel")

        logger.info("[rcs:simulated] to=%s title=%s ref=%s body=%s", recipient.phone, title, reference, data)
        return SendResult(success=True, provider_message_id=f"simulated-{uuid.uuid4()}")
