"""Processes one dequeued notification message: sends it on every requested
channel and updates the store per channel, then rolls up the overall status.
"""

import logging

from app.channels.base import SendResult
from app.channels.registry import ChannelRegistry
from app.models.notification import ChannelResult, ChannelStatus, NotificationChannel, Recipient
from app.store.base import NotificationStore

logger = logging.getLogger(__name__)


class NotificationProcessor:
    def __init__(self, store: NotificationStore, registry: ChannelRegistry) -> None:
        self._store = store
        self._registry = registry

    def process(self, message: dict) -> None:
        notf_req_id = message["notf_req_id"]
        reference = message["reference"]
        recipient = Recipient(**message["recipient"])
        title = message["title"]
        data = message["data"]
        channels: list[NotificationChannel] = [NotificationChannel(c) for c in message["channels"]]

        logger.info("processing notf_req_id=%s ref=%s channels=%s", notf_req_id, reference, channels)

        for channel in channels:
            self._store.update_channel_result(
                notf_req_id, ChannelResult(channel=channel, status=ChannelStatus.processing)
            )
            result = self._send_one(channel, recipient, title, data, reference)
            status = ChannelStatus.sent if result.success else ChannelStatus.failed
            self._store.update_channel_result(
                notf_req_id,
                ChannelResult(
                    channel=channel,
                    status=status,
                    provider_message_id=result.provider_message_id,
                    error=result.error,
                ),
            )
            logger.info(
                "channel result notf_req_id=%s channel=%s status=%s error=%s",
                notf_req_id,
                channel.value,
                status.value,
                result.error,
            )

        overall = self._store.recompute_overall_status(notf_req_id)
        logger.info("finished notf_req_id=%s overall_status=%s", notf_req_id, overall)

    def _send_one(
        self, channel: NotificationChannel, recipient: Recipient, title: str, data: str, reference: str
    ) -> SendResult:
        try:
            sender = self._registry.get(channel)
            return sender.send(recipient=recipient, title=title, data=data, reference=reference)
        except Exception as exc:  # noqa: BLE001 - a channel bug must never take down the worker thread
            logger.exception("unexpected error sending channel=%s ref=%s", channel.value, reference)
            return SendResult(success=False, error=str(exc))
