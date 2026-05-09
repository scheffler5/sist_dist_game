import uuid
from typing import Optional, Tuple

from core.scoring import assign_objects
from database import db
from domain.constants import GameStatus
from domain.models import GameState, Player
from services.base import BaseService


class LobbyService(BaseService):

    async def create_or_join_game(
        self, game_id: str, player_name: str
    ) -> Tuple[Optional[str], Optional[str], str]:
        """Cria uma partida nova ou entra numa existente.
        Retorna (player_id, game_id, message)."""
        async with self._get_lock(game_id):
            creating = game_id not in self._games
            if creating:
                self._games[game_id] = GameState(game_id=game_id)
                await db.delete_chat(game_id)

            game = self._games[game_id]

            if game.status != GameStatus.WAITING:
                return None, None, "Jogo já em andamento"

            if any(p.name == player_name for p in game.players.values()):
                return None, None, f"Nome '{player_name}' já está em uso neste jogo"

            player_id = str(uuid.uuid4())[:8]
            is_host = len(game.players) == 0
            game.players[player_id] = Player(id=player_id, name=player_name, is_host=is_host)

            await self._bus.broadcast(game_id, "player_joined", {
                "player_id": player_id,
                "player_name": player_name,
                "is_host": is_host,
                "total_players": len(game.players),
            })

            msg = "Jogo criado!" if creating else "Você entrou no jogo!"
            return player_id, game_id, msg

    async def start_game(
        self, game_id: str, player_id: str, max_turns: int = 5
    ) -> Tuple[bool, str]:
        async with self._get_lock(game_id):
            game = self._get_game(game_id)
            if not game:
                return False, "Jogo não encontrado"
            if player_id not in game.players:
                return False, "Jogador não encontrado"
            if not game.players[player_id].is_host:
                return False, "Apenas o host pode iniciar o jogo"
            if len(game.players) < 2:
                return False, "Precisa de pelo menos 2 jogadores"
            if game.status != GameStatus.WAITING:
                return False, "Jogo já iniciado"

            game.max_turns = max_turns
            game.current_turn = 1
            game.status = GameStatus.PLAYING
            assign_objects(game)

            for pid, player in game.players.items():
                await self._bus.broadcast(game_id, "game_started", {
                    "your_object_name": player.object_name,
                    "your_object_emoji": player.object_emoji,
                    "max_turns": max_turns,
                    "current_turn": 1,
                    "state": game.to_dict(viewer_id=pid),
                }, target=pid)

            return True, "Jogo iniciado!"

    async def kick_player(
        self, game_id: str, host_id: str, target_id: str
    ) -> Tuple[bool, str]:
        game = self._get_game(game_id)
        if not game:
            return False, "Jogo não encontrado"

        host = game.players.get(host_id)
        if not host or not host.is_host:
            return False, "Apenas o host pode remover jogadores"

        target = game.players.get(target_id)
        if not target:
            return False, "Jogador não encontrado"

        del game.players[target_id]
        await self._bus.broadcast(game_id, "player_kicked", {
            "player_id": target_id,
            "player_name": target.name,
        })
        return True, f"{target.name} removido do jogo"
