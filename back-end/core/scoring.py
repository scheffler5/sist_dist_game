import random
from typing import List

from domain.constants import (
    OBJECTS,
    OWNER_ALL_PENALTY,
    OWNER_MULTI_POINTS,
    OWNER_SOLO_POINTS,
    SOLO_BONUS_POINTS,
)
from domain.models import GameState


def assign_objects(game: GameState) -> None:
    """Sorteia objetos únicos para cada jogador e reseta flags por rodada."""
    available = [o for o in OBJECTS if o["name"] not in game.used_objects]
    if len(available) < len(game.players):
        game.used_objects = []
        available = list(OBJECTS)

    chosen = random.sample(available, len(game.players))
    for player, obj in zip(game.players.values(), chosen):
        player.object_name = obj["name"]
        player.object_emoji = obj["emoji"]
        player.public_hints = []
        player.object_guessed = False
        player.guessed_by = []
        player.private_exchange_used = False
        player.hint_sent_this_turn = False
        game.used_objects.append(obj["name"])


def calculate_owner_scores(game: GameState) -> None:
    """
    Aplica pontuação dos donos ao fim dos turnos.
    Regras:
      - Ninguém adivinhou  → 0 pts
      - Só 1 adivinhou     → OWNER_SOLO_POINTS
      - Vários adivinharam → OWNER_MULTI_POINTS
      - Todos adivinharam  → OWNER_ALL_PENALTY
    Bônus adicional: quem foi o ÚNICO a adivinhar qualquer objeto ganha SOLO_BONUS_POINTS.
    """
    n_others = len(game.players) - 1
    if n_others <= 0:
        return

    for player in game.players.values():
        n_guessed = len(player.guessed_by)
        if n_guessed == 0:
            pass
        elif n_guessed == n_others:
            player.score += OWNER_ALL_PENALTY
        elif n_guessed == 1:
            player.score += OWNER_SOLO_POINTS
        else:
            player.score += OWNER_MULTI_POINTS

    # Bônus de único acertador
    for pid, guesser in game.players.items():
        for target in game.players.values():
            if target.id == pid:
                continue
            if len(target.guessed_by) == 1 and target.guessed_by[0] == pid:
                guesser.score += SOLO_BONUS_POINTS
