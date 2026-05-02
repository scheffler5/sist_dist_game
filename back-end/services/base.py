import asyncio
from typing import Dict, Optional

from core.event_bus import EventBus
from domain.models import GameState


class BaseService:
    """
    Dependências compartilhadas por todos os services:
      - _games   : dicionário game_id → GameState
      - _locks   : dicionário game_id → asyncio.Lock (um lock por partida)
      - _bus     : EventBus para broadcast de eventos
    """

    def __init__(
        self,
        games: Dict[str, GameState],
        locks: Dict[str, asyncio.Lock],
        bus: EventBus,
    ) -> None:
        self._games = games
        self._locks = locks
        self._bus = bus

    def _get_lock(self, game_id: str) -> asyncio.Lock:
        if game_id not in self._locks:
            self._locks[game_id] = asyncio.Lock()
        return self._locks[game_id]

    def _get_game(self, game_id: str) -> Optional[GameState]:
        return self._games.get(game_id)
