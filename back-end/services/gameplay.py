import uuid
from typing import Optional, Tuple

from core.scoring import assign_objects, calculate_owner_scores
from domain.constants import (
    FIRST_GUESS_POINTS,
    OTHER_GUESS_POINTS,
    GameStatus,
)
from domain.models import GuessAttempt
from services.base import BaseService


class GameplayService(BaseService):

    async def send_public_hint(
        self, game_id: str, player_id: str, hint: str
    ) -> Tuple[bool, str]:
        hint = hint.strip().lower()
        if not hint or " " in hint:
            return False, "A dica deve ser uma única palavra"

        async with self._get_lock(game_id):
            game = self._get_game(game_id)
            if not game or game.status != GameStatus.PLAYING:
                return False, "Jogo não está em andamento"

            player = game.players.get(player_id)
            if not player:
                return False, "Jogador não encontrado"
            if player.hint_sent_this_turn:
                return False, "Você já enviou uma dica neste turno"

            player.public_hints.append(hint)
            player.hint_sent_this_turn = True

            await self._bus.broadcast(game_id, "hint_sent", {
                "player_id": player_id,
                "player_name": player.name,
                "hint": hint,
                "turn": game.current_turn,
                "hint_number": len(player.public_hints),
            })
            return True, "Dica enviada!"

    async def guess_object(
        self, game_id: str, guesser_id: str, target_id: str, guess: str
    ) -> Tuple[bool, str, Optional[str]]:
        guess = guess.strip().lower()
        if not guess:
            return False, "Palpite não pode ser vazio", None

        async with self._get_lock(game_id):
            game = self._get_game(game_id)
            if not game or game.status != GameStatus.PLAYING:
                return False, "Jogo não está em andamento", None

            guesser = game.players.get(guesser_id)
            target = game.players.get(target_id)
            if not guesser or not target:
                return False, "Jogador não encontrado", None
            if guesser_id == target_id:
                return False, "Você não pode adivinhar seu próprio objeto", None
            if target.object_guessed:
                return False, "Este objeto já foi adivinhado", None

            already = any(
                ga.guesser_id == guesser_id and ga.target_player_id == target_id
                for ga in game.guess_attempts.values()
            )
            if already:
                return False, "Você já tentou adivinhar o objeto deste jogador", None

            guess_id = str(uuid.uuid4())[:8]
            game.guess_attempts[guess_id] = GuessAttempt(
                id=guess_id,
                guesser_id=guesser_id,
                guesser_name=guesser.name,
                target_player_id=target_id,
                guess=guess,
            )

            await self._bus.broadcast(game_id, "guess_pending", {
                "guess_id": guess_id,
                "guesser_id": guesser_id,
                "guesser_name": guesser.name,
                "target_player_id": target_id,
                "target_name": target.name,
                "guess": guess,
            })
            await self._bus.broadcast(game_id, "validate_request", {
                "guess_id": guess_id,
                "guesser_name": guesser.name,
                "guess": guess,
            }, target=target_id)

            return True, "Palpite enviado! Aguardando validação do dono do objeto.", guess_id

    async def validate_guess(
        self, game_id: str, validator_id: str, guess_id: str, is_correct: bool
    ) -> Tuple[bool, str]:
        async with self._get_lock(game_id):
            game = self._get_game(game_id)
            if not game:
                return False, "Jogo não encontrado"

            attempt = game.guess_attempts.get(guess_id)
            if not attempt:
                return False, "Palpite não encontrado"
            if attempt.target_player_id != validator_id:
                return False, "Apenas o dono do objeto pode validar"
            if attempt.status != "pending":
                return False, "Este palpite já foi validado"

            guesser = game.players.get(attempt.guesser_id)
            target = game.players.get(attempt.target_player_id)

            if is_correct:
                attempt.status = "correct"
                first_correct = not target.object_guessed
                target.guessed_by.append(attempt.guesser_id)

                points = FIRST_GUESS_POINTS if first_correct else OTHER_GUESS_POINTS
                guesser.score += points

                if first_correct:
                    target.object_guessed = True

                await self._bus.broadcast(game_id, "guess_result", {
                    "guess_id": guess_id,
                    "guesser_id": attempt.guesser_id,
                    "guesser_name": guesser.name if guesser else "?",
                    "target_player_id": validator_id,
                    "target_name": target.name if target else "?",
                    "guess": attempt.guess,
                    "correct": True,
                    "points": points,
                    "object_name": target.object_name if target else "",
                    "object_emoji": target.object_emoji if target else "",
                    "first_correct": first_correct,
                })

                n_others = len(game.players) - 1
                if len(target.guessed_by) == n_others:
                    await self._bus.broadcast(game_id, "all_guessed", {
                        "target_player_id": validator_id,
                        "target_name": target.name if target else "?",
                        "object_name": target.object_name if target else "",
                    })
            else:
                attempt.status = "incorrect"
                await self._bus.broadcast(game_id, "guess_result", {
                    "guess_id": guess_id,
                    "guesser_id": attempt.guesser_id,
                    "guesser_name": guesser.name if guesser else "?",
                    "target_player_id": validator_id,
                    "correct": False,
                    "guess": attempt.guess,
                })

            return True, "Validação registrada"

    async def advance_turn(
        self, game_id: str, player_id: str
    ) -> Tuple[bool, str]:
        async with self._get_lock(game_id):
            game = self._get_game(game_id)
            if not game or game.status != GameStatus.PLAYING:
                return False, "Jogo não está em andamento"

            player = game.players.get(player_id)
            if not player or not player.is_host:
                return False, "Apenas o host pode avançar o turno"

            if game.current_turn >= game.max_turns:
                calculate_owner_scores(game)
                game.status = GameStatus.VOTING
                await self._bus.broadcast(game_id, "voting_started", {
                    "scores": {pid: p.score for pid, p in game.players.items()},
                    "state": game.to_dict(),
                })
                return True, "Limite de turnos atingido! Votação iniciada."

            game.current_turn += 1
            for p in game.players.values():
                p.hint_sent_this_turn = False

            await self._bus.broadcast(game_id, "turn_advanced", {
                "current_turn": game.current_turn,
                "max_turns": game.max_turns,
            })
            return True, f"Turno {game.current_turn} iniciado!"
