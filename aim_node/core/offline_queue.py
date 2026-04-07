from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from .config import AIMCoreConfig

logger = logging.getLogger(__name__)

MAX_QUEUE_ENTRIES = 50
DEFAULT_QUEUE_FILENAME = "pending_usage.jsonl"


class OfflineQueue:
    """Append-only JSONL queue for offline usage metering."""

    def __init__(self, config: AIMCoreConfig, path: Optional[str | Path] = None):
        self.config = config
        self._path = Path(path) if path is not None else config.data_dir / DEFAULT_QUEUE_FILENAME

    @property
    def path(self) -> Path:
        return self._path

    def append(self, entry: dict) -> bool:
        current_count = self.count()
        if current_count >= MAX_QUEUE_ENTRIES:
            logger.warning("Offline queue full (%d entries); rejecting new entry", current_count)
            return False

        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")
        logger.info("Queued offline usage: request_id=%s", entry.get("request_id", "?"))
        return True

    def count(self) -> int:
        if not self._path.exists():
            return 0
        try:
            with self._path.open("r", encoding="utf-8") as handle:
                return sum(1 for line in handle if line.strip())
        except OSError:
            return 0

    def read_all(self) -> list[dict]:
        if not self._path.exists():
            return []
        entries: list[dict] = []
        with self._path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.warning("Skipping malformed offline queue entry")
        return entries

    def dequeue_all(self) -> list[dict]:
        entries = self.read_all()
        self.clear()
        return entries

    def clear(self) -> None:
        try:
            self._path.unlink(missing_ok=True)
            logger.info("Offline queue cleared")
        except OSError as exc:
            logger.error("Failed to clear offline queue: %s", exc)

    async def flush(self, serial_client, serial: str, install_token: str) -> int:
        entries = self.read_all()
        if not entries:
            return 0

        from decimal import Decimal

        sent = 0
        for entry in entries:
            result = await serial_client.meter(
                serial=serial,
                install_token=install_token,
                category=entry.get("category", "setup"),
                cost_usd=Decimal(entry.get("cost_usd", "0.00")),
                request_id=entry["request_id"],
                description=entry.get("description", "offline-queued"),
            )
            if result.status_code in (200, 409):
                sent += 1
            else:
                logger.warning(
                    "Failed to flush offline entry %s: status=%d",
                    entry.get("request_id"),
                    result.status_code,
                )
                break

        if sent == len(entries):
            self.clear()
            logger.info("Flushed all %d offline entries", sent)
        else:
            remaining = entries[sent:]
            self.clear()
            for entry in remaining:
                self.append(entry)
            logger.info("Flushed %d/%d offline entries, %d remaining", sent, len(entries), len(remaining))

        return sent


_queue: Optional[OfflineQueue] = None


def get_offline_queue(config: AIMCoreConfig) -> OfflineQueue:
    global _queue
    if _queue is None or _queue.path != config.data_dir / DEFAULT_QUEUE_FILENAME:
        _queue = OfflineQueue(config)
    return _queue
