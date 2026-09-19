"""Strategy interface all channel senders implement.

`NotificationProcessor` only depends on this interface, so adding a new
channel is: implement `NotificationSender`, register it in `registry.py` —
nothing else in the pipeline changes.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.models.notification import Recipient


@dataclass
class SendResult:
    success: bool
    provider_message_id: str | None = None
    error: str | None = None


class NotificationSender(ABC):
    @abstractmethod
    def send(self, recipient: Recipient, title: str, data: str, reference: str) -> SendResult:
        """Attempt delivery. Must never raise — failures are reported via `SendResult`."""
