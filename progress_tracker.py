from __future__ import annotations

import time


class ProgressTracker:
    def __init__(
        self,
        total: int,
        *,
        enabled_threshold: int = 1,
        start_message: str | None = None,
        print_all_percent_transitions: bool = False,
    ) -> None:
        self.total = total
        self.enabled = total >= enabled_threshold
        self.start_monotonic = time.monotonic()
        self.processed = 0
        self.last_percent = -1
        self.print_all_percent_transitions = print_all_percent_transitions

        if self.enabled and start_message:
            print(start_message)

    def _print_percent(self, percent: int) -> None:
        elapsed = time.monotonic() - self.start_monotonic
        per_item = elapsed / self.processed if self.processed else 0.0
        remaining = max(self.total - self.processed, 0)
        eta_seconds = int(per_item * remaining)
        print(f"Progress: {percent}% ({self.processed}/{self.total}), ETA: {eta_seconds}s")

    def step(self) -> None:
        if not self.enabled:
            return

        self.processed += 1
        percent = int((self.processed / self.total) * 100)
        if percent == self.last_percent:
            return

        self.last_percent = percent
        self._print_percent(percent)

    def update(self, processed: int) -> None:
        if not self.enabled:
            return

        self.processed = processed
        target_percent = int((processed / self.total) * 100)
        if self.print_all_percent_transitions:
            while self.last_percent < target_percent:
                self.last_percent += 1
                self._print_percent(self.last_percent)
            return

        if target_percent == self.last_percent:
            return

        self.last_percent = target_percent
        self._print_percent(target_percent)
