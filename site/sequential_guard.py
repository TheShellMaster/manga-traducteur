"""Force one-page-at-a-time translation for free model quotas."""
from __future__ import annotations

import time
from typing import Any, Callable, Dict, Iterable, List


class SequentialTranslator:
    """Runs page jobs in archive order. Never fans out free-tier calls."""

    def __init__(self, pause_seconds: float = 1.5, max_retries: int = 3):
        self.pause_seconds = pause_seconds
        self.max_retries = max_retries

    def run(self, pages: Iterable[int], worker: Callable[[int], Dict[str, Any]]) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for index in pages:
            attempt = 0
            while True:
                try:
                    result = worker(index)
                except Exception as exc:  # noqa: BLE001 - surfaced to the job log
                    result = {"status": "error", "page": index, "error": str(exc)[:300]}
                if result.get("status") == "rate_limited" and attempt < self.max_retries:
                    attempt += 1
                    time.sleep(self.pause_seconds * attempt)
                    continue
                result.setdefault("page", index)
                results.append(result)
                break
            time.sleep(self.pause_seconds)
        return results
