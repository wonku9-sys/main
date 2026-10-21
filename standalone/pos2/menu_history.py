"""Bounded, per-login menu visits. No business data or settings are written."""


class MenuHistory:
    def __init__(self, limit=100):
        self.limit = max(2, limit)
        self.entries = []
        self.index = -1

    def record(self, key):
        if self.index >= 0 and self.entries[self.index] == key:
            return
        del self.entries[self.index + 1:]
        self.entries.append(key)
        if len(self.entries) > self.limit:
            del self.entries[:-self.limit]
        self.index = len(self.entries) - 1

    def target(self, step):
        index = self.index + step
        return index if 0 <= index < len(self.entries) else None

    def label(self, step):
        index = self.target(step)
        return self.entries[index] if index is not None else None
