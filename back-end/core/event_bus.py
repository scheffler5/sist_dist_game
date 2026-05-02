import asyncio
import time
from typing import Dict, Optional


class EventBus:
    """
    Pub/sub de eventos por partida.
    Cada jogador possui uma asyncio.Queue dedicada.
    O broadcast coloca eventos em todas as filas (ou só na do target).
    """

    def __init__(self):
        # game_id → { player_id → Queue }
        self._queues: Dict[str, Dict[str, asyncio.Queue]] = {}

    async def subscribe(self, game_id: str, player_id: str) -> asyncio.Queue:
        if game_id not in self._queues:
            self._queues[game_id] = {}
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._queues[game_id][player_id] = q
        return q

    def unsubscribe(self, game_id: str, player_id: str) -> None:
        if game_id in self._queues:
            self._queues[game_id].pop(player_id, None)

    async def broadcast(
        self,
        game_id: str,
        event_type: str,
        data: dict,
        target: Optional[str] = None,
    ) -> None:
        event = {
            "event_type": event_type,
            "data": data,
            "timestamp": int(time.time() * 1000),
            "target_player_id": target or "",
        }
        for pid, q in self._queues.get(game_id, {}).items():
            if target is None or target == pid:
                try:
                    q.put_nowait(event)
                except asyncio.QueueFull:
                    pass
