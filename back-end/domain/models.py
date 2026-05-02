import time
from dataclasses import dataclass, field
from typing import Dict, List, Set

from domain.constants import GameStatus


@dataclass
class Player:
    id: str
    name: str
    object_name: str = ""
    object_emoji: str = ""
    public_hints: List[str] = field(default_factory=list)
    object_guessed: bool = False
    guessed_by: List[str] = field(default_factory=list)
    private_exchange_used: bool = False
    score: int = 0
    hint_sent_this_turn: bool = False
    is_host: bool = False
    connected: bool = True


@dataclass
class GuessAttempt:
    id: str
    guesser_id: str
    guesser_name: str
    target_player_id: str
    guess: str
    status: str = "pending"     # pending | correct | incorrect
    timestamp: float = field(default_factory=time.time)
    first_correct: bool = False


@dataclass
class PrivateExchange:
    id: str
    from_id: str
    from_name: str
    to_id: str
    to_name: str
    from_hint: str
    to_hint: str = ""
    status: str = "pending"     # pending | accepted | rejected
    round: int = 0
    spies_caught: List[str] = field(default_factory=list)
    spies_succeeded: List[str] = field(default_factory=list)


@dataclass
class GameState:
    game_id: str
    status: str = GameStatus.WAITING
    players: Dict[str, Player] = field(default_factory=dict)
    current_turn: int = 0
    max_turns: int = 5
    current_round: int = 1
    guess_attempts: Dict[str, GuessAttempt] = field(default_factory=dict)
    private_exchanges: Dict[str, PrivateExchange] = field(default_factory=dict)
    votes_continue: Set[str] = field(default_factory=set)
    votes_end: Set[str] = field(default_factory=set)
    used_objects: List[str] = field(default_factory=list)

    def to_dict(self, viewer_id: str = None) -> dict:
        """Serializa o estado ocultando segredos conforme o espectador."""
        players_data = {}
        for pid, p in self.players.items():
            pd = {
                "id": p.id,
                "name": p.name,
                "public_hints": p.public_hints,
                "object_guessed": p.object_guessed,
                "guessed_by": p.guessed_by,
                "score": p.score,
                "hint_sent_this_turn": p.hint_sent_this_turn,
                "is_host": p.is_host,
                "private_exchange_used": p.private_exchange_used,
                "connected": p.connected,
            }
            if viewer_id == pid:
                pd["object_name"] = p.object_name
                pd["object_emoji"] = p.object_emoji
                pd["is_you"] = True
            else:
                pd["object_name"] = p.object_name if p.object_guessed else "???"
                pd["object_emoji"] = p.object_emoji if p.object_guessed else "❓"
                pd["is_you"] = False
            players_data[pid] = pd

        exchanges_data = []
        for ex in self.private_exchanges.values():
            if ex.status == "pending" and viewer_id not in [ex.from_id, ex.to_id]:
                continue
            ed = {
                "id": ex.id,
                "from_id": ex.from_id,
                "from_name": ex.from_name,
                "to_id": ex.to_id,
                "to_name": ex.to_name,
                "status": ex.status,
                "round": ex.round,
            }
            if viewer_id in [ex.from_id, ex.to_id]:
                ed["from_hint"] = ex.from_hint
                ed["to_hint"] = ex.to_hint
            elif viewer_id in ex.spies_succeeded:
                ed["from_hint"] = ex.from_hint
                ed["to_hint"] = ex.to_hint
                ed["spied"] = True
            else:
                ed["from_hint"] = "(privado)"
                ed["to_hint"] = "(privado)"
            exchanges_data.append(ed)

        guesses_data = [
            {
                "id": ga.id,
                "guesser_id": ga.guesser_id,
                "guesser_name": ga.guesser_name,
                "target_player_id": ga.target_player_id,
                "guess": ga.guess,
                "status": ga.status,
                "timestamp": ga.timestamp,
            }
            for ga in self.guess_attempts.values()
        ]

        return {
            "game_id": self.game_id,
            "status": self.status,
            "players": players_data,
            "current_turn": self.current_turn,
            "max_turns": self.max_turns,
            "current_round": self.current_round,
            "guess_attempts": guesses_data,
            "private_exchanges": exchanges_data,
            "votes_continue": list(self.votes_continue),
            "votes_end": list(self.votes_end),
        }
