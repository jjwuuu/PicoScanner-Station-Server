"""Small durable FIFO queue for MicroPython RFID readers."""
import os
import ujson


class OfflineQueue:
    def __init__(self, path="swipe_queue.json", max_items=100):
        self.path = path
        self.max_items = max_items

    def _load(self):
        try:
            with open(self.path, "r") as file:
                return ujson.load(file)
        except Exception:
            return []

    def _save(self, items):
        temp = self.path + ".tmp"
        with open(temp, "w") as file:
            ujson.dump(items, file)
        try:
            os.remove(self.path)
        except OSError:
            pass
        os.rename(temp, self.path)

    def add(self, event):
        items = self._load()
        items.append(event)
        # Keep newest events if flash storage is exhausted.
        self._save(items[-self.max_items:])
        return len(items[-self.max_items:])

    def peek(self):
        items = self._load()
        return items[0] if items else None

    def remove_first(self):
        items = self._load()
        if items:
            self._save(items[1:])

    def __len__(self):
        return len(self._load())
