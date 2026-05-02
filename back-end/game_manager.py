"""
GameManager: orquestrador fino que agrega os services e expõe
a mesma interface pública usada pelo game_server.py.
"""

import asyncio
from typing import Dict, Optional

from core.event_bus import EventBus
from domain.models import GameState
from services.exchange import ExchangeService
from services.gameplay import GameplayService
from services.lobby import LobbyService
from services.spy import SpyService
from services.voting import VotingService


class GameManager:
    def __init__(self):
        self._games: Dict[str, GameState] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self._bus = EventBus()

        deps = (self._games, self._locks, self._bus)
        self._lobby    = LobbyService(*deps)
        self._gameplay = GameplayService(*deps)
        self._exchange = ExchangeService(*deps)
        self._spy      = SpyService(*deps)
        self._voting   = VotingService(*deps)

    # ── Event Bus ──────────────────────────────────────────────────────────

    async def subscribe(self, game_id: str, player_id: str) -> asyncio.Queue:
        return await self._bus.subscribe(game_id, player_id)

    def unsubscribe(self, game_id: str, player_id: str) -> None:
        self._bus.unsubscribe(game_id, player_id)

    async def _broadcast(self, game_id: str, event_type: str, data: dict, target: str = None):
        await self._bus.broadcast(game_id, event_type, data, target)

    # ── State ──────────────────────────────────────────────────────────────

    def get_game(self, game_id: str) -> Optional[GameState]:
        return self._games.get(game_id)

    def game_exists(self, game_id: str) -> bool:
        return game_id in self._games

    # ── Lobby ──────────────────────────────────────────────────────────────

    async def create_or_join_game(self, game_id: str, player_name: str):
        return await self._lobby.create_or_join_game(game_id, player_name)

    async def start_game(self, game_id: str, player_id: str, max_turns: int = 5):
        return await self._lobby.start_game(game_id, player_id, max_turns)

    async def kick_player(self, game_id: str, host_id: str, target_id: str):
        return await self._lobby.kick_player(game_id, host_id, target_id)

    # ── Gameplay ───────────────────────────────────────────────────────────

    async def send_public_hint(self, game_id: str, player_id: str, hint: str):
        return await self._gameplay.send_public_hint(game_id, player_id, hint)

    async def guess_object(self, game_id: str, guesser_id: str, target_id: str, guess: str):
        return await self._gameplay.guess_object(game_id, guesser_id, target_id, guess)

    async def validate_guess(self, game_id: str, validator_id: str, guess_id: str, is_correct: bool):
        return await self._gameplay.validate_guess(game_id, validator_id, guess_id, is_correct)

    async def advance_turn(self, game_id: str, player_id: str):
        return await self._gameplay.advance_turn(game_id, player_id)

    # ── Troca Privada ──────────────────────────────────────────────────────

    async def request_private_exchange(self, game_id: str, from_id: str, to_id: str, hint: str):
        return await self._exchange.request_private_exchange(game_id, from_id, to_id, hint)

    async def respond_to_exchange(self, game_id: str, responder_id: str, exchange_id: str, accept: bool, hint: str = ""):
        return await self._exchange.respond_to_exchange(game_id, responder_id, exchange_id, accept, hint)

    # ── Espionagem ─────────────────────────────────────────────────────────

    async def spy_on_exchange(self, game_id: str, spy_id: str, exchange_id: str):
        return await self._spy.spy_on_exchange(game_id, spy_id, exchange_id)

    # ── Votação ────────────────────────────────────────────────────────────

    async def vote_continue(self, game_id: str, player_id: str, continue_game: bool):
        return await self._voting.vote_continue(game_id, player_id, continue_game)


# Singleton global consumido pelo game_server.py
game_manager = GameManager()
