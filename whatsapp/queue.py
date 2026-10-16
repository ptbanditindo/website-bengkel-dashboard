"""Per-number reply delay queue (in-process; one queue per number)."""

import time


class PerNumberQueue:
    """Independent reply delay per WhatsApp number.

    A delay for one number never blocks another. Delays are a courtesy window,
    not a way to evade platform limits.
    """

    def __init__(self, default_delay_seconds: int = 60):
        self.default_delay = default_delay_seconds
        self._pending: dict[str, list[dict]] = {}

    def enqueue(self, number: str, text: str, delay_seconds=None):
        delay = delay_seconds if delay_seconds is not None else self.default_delay
        due_at = time.monotonic() + max(0.0, float(delay))
        self._pending.setdefault(number, []).append({"due_at": due_at, "text": text})

    def pop_due(self):
        """Return list of (number, text) whose delay has elapsed."""
        now = time.monotonic()
        out = []
        for number in list(self._pending.keys()):
            items = self._pending[number]
            due = [it for it in items if it["due_at"] <= now]
            remaining = [it for it in items if it["due_at"] > now]
            if remaining:
                self._pending[number] = remaining
            else:
                self._pending.pop(number, None)
            for it in due:
                out.append((number, it["text"]))
        return out

    def pending_count(self, number=None) -> int:
        if number is not None:
            return len(self._pending.get(number, []))
        return sum(len(v) for v in self._pending.values())
