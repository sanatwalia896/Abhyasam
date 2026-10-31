"""Request-local pending source passages. Nothing in this module writes to GCS."""
from dataclasses import dataclass


@dataclass
class PendingPassage:
    source: dict
    added_at: int


class PageBuffer:
    MAX_CHUNKS = 4
    MAX_CHARACTERS = 6000
    MAX_AGE = 5

    def __init__(self):
        self.pending: list[PendingPassage] = []

    def sources(self, step):
        self.pending = [item for item in self.pending if step - item.added_at <= self.MAX_AGE]
        return [item.source for item in self.pending]

    def update(self, current, step, *, retain=(), drop=(), consumed=(), defer=False):
        """Only retain original supplied passages; never accept model-written text."""
        retain, drop, consumed = set(retain), set(drop), set(consumed)
        self.sources(step)
        self.pending = [item for item in self.pending
                        if item.source["id"] not in drop
                        and (item.source["id"] not in consumed or item.source["id"] in retain)]
        if current and current["id"] not in drop and (defer or current["id"] in retain):
            if not any(item.source["id"] == current["id"] for item in self.pending):
                # A single oversized passage cannot fit; do not silently truncate evidence.
                if len(current["text"]) <= self.MAX_CHARACTERS:
                    self.pending.append(PendingPassage(current, step))
        while len(self.pending) > self.MAX_CHUNKS or sum(len(item.source["text"]) for item in self.pending) > self.MAX_CHARACTERS:
            self.pending.pop(0)

    def clear(self):
        self.pending.clear()
