"""Thread-safe in-memory store, guarded by a single lock.

Each notification request can fan out to several channels processed
concurrently by different worker threads, so every read-modify-write here
must be atomic — hence the lock spanning the whole method body rather than
per-field.
"""

import threading
from datetime import datetime, timezone

from app.models.notification import (
    ChannelResult,
    ChannelStatus,
    NotificationChannel,
    NotificationRecord,
    OverallStatus,
)
from app.store.base import NotificationStore


class InMemoryNotificationStore(NotificationStore):
    def __init__(self) -> None:
        self._records: dict[str, NotificationRecord] = {}
        self._lock = threading.Lock()

    def create(self, record: NotificationRecord) -> None:
        with self._lock:
            self._records[record.notf_req_id] = record

    def get(self, notf_req_id: str) -> NotificationRecord | None:
        with self._lock:
            record = self._records.get(notf_req_id)
            return record.model_copy(deep=True) if record else None

    def update_overall_status(self, notf_req_id: str, status: OverallStatus) -> None:
        with self._lock:
            record = self._records.get(notf_req_id)
            if record is None:
                return
            record.overall_status = status
            record.updated_at = datetime.now(timezone.utc)

    def update_channel_result(self, notf_req_id: str, result: ChannelResult) -> None:
        with self._lock:
            record = self._records.get(notf_req_id)
            if record is None:
                return
            record.channel_results[result.channel] = result
            record.updated_at = datetime.now(timezone.utc)

    def recompute_overall_status(self, notf_req_id: str) -> OverallStatus | None:
        with self._lock:
            record = self._records.get(notf_req_id)
            if record is None:
                return None

            statuses = [r.status for r in record.channel_results.values()]
            if any(s in (ChannelStatus.pending, ChannelStatus.processing) for s in statuses):
                overall = OverallStatus.processing
            elif all(s == ChannelStatus.sent for s in statuses):
                overall = OverallStatus.sent
            elif all(s == ChannelStatus.failed for s in statuses):
                overall = OverallStatus.failed
            else:
                overall = OverallStatus.partially_sent

            record.overall_status = overall
            record.updated_at = datetime.now(timezone.utc)
            return overall
