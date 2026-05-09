from typing import Tuple

from core.scoring import assign_objects
from database import db
from domain.constants import GameStatus
from services.base import BaseService


class VotingService(BaseService):

    async def vote_continue(
        self, game_id: str, player_id: str, continue_game: bool
    ) -> Tuple[bool, str]:
        async with self._get_lock(game_id):
            game = self._get_game(game_id)
            if not game or game.status != GameStatus.VOTING:
                return False, "Votação não está ativa"

            if continue_game:
                game.votes_continue.add(player_id)
                game.votes_end.discard(player_id)
            else:
                game.votes_end.add(player_id)
                game.votes_continue.discard(player_id)

            n_players = len(game.players)
            votes_in = len(game.votes_continue) + len(game.votes_end)

            await self._bus.broadcast(game_id, "vote_update", {
                "votes_continue": len(game.votes_continue),
                "votes_end": len(game.votes_end),
                "total_players": n_players,
            })

            if votes_in == n_players:
                await self._resolve_vote(game_id, game)

            return True, "Voto registrado"

    async def _resolve_vote(self, game_id: str, game) -> None:
        if len(game.votes_continue) > len(game.votes_end):
            game.current_round += 1
            game.current_turn = 1
            game.status = GameStatus.PLAYING
            game.votes_continue.clear()
            game.votes_end.clear()
            game.guess_attempts.clear()
            game.private_exchanges.clear()
            assign_objects(game)

            for pid, p in game.players.items():
                p.hint_sent_this_turn = False
                await self._bus.broadcast(game_id, "new_round", {
                    "round": game.current_round,
                    "your_object_name": p.object_name,
                    "your_object_emoji": p.object_emoji,
                    "state": game.to_dict(viewer_id=pid),
                }, target=pid)
        else:
            game.status = GameStatus.FINISHED
            scores = sorted(
                [{"id": pid, "name": p.name, "score": p.score}
                 for pid, p in game.players.items()],
                key=lambda x: x["score"],
                reverse=True,
            )
            await self._bus.broadcast(game_id, "game_finished", {
                "final_scores": scores,
                "state": game.to_dict(),
            })
            await db.delete_chat(game_id)
