from __future__ import annotations
from typing import Callable, List
from eli.world.core.schemas import WorldEvent

class EliWorldEventBus:
    def __init__(self) -> None:
        self._subscribers: List[Callable[[WorldEvent], None]] = []

    def subscribe(self, callback: Callable[[WorldEvent], None]) -> None:
        if callback not in self._subscribers:
            self._subscribers.append(callback)

    def publish(self, event: WorldEvent) -> None:
        for callback in list(self._subscribers):
            callback(event)
