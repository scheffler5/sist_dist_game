"""
Lógica central do jogo de adivinhação.
Estado mantido em memória com locks asyncio para concorrência.
"""

import uuid
import random
import json
import asyncio
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Any
from enum import Enum

# --------------- Constantes de Pontuação ---------------
FIRST_GUESS_POINTS = 15
OTHER_GUESS_POINTS = 10
SOLO_BONUS_POINTS = 5      # bônus para quem foi o único a adivinhar
OWNER_SOLO_POINTS = 20     # dono ganha se só 1 adivinhou
OWNER_MULTI_POINTS = 10    # dono ganha se vários adivinharam
OWNER_ALL_PENALTY = -5     # dono perde se todos adivinharam
SPY_CAUGHT_PENALTY = -5    # penalidade por ser pego espiando
SPY_CATCH_CHANCE = 0.4     # 40% de chance de ser descoberto


# --------------- Objetos do Jogo ---------------
OBJECTS = [
    {"name": "bicicleta",  "emoji": "🚲"},
    {"name": "piano",      "emoji": "🎹"},
    {"name": "telescópio", "emoji": "🔭"},
    {"name": "guitarra",   "emoji": "🎸"},
    {"name": "foguete",    "emoji": "🚀"},
    {"name": "montanha",   "emoji": "⛰️"},
    {"name": "borboleta",  "emoji": "🦋"},
    {"name": "castelo",    "emoji": "🏰"},
    {"name": "helicóptero","emoji": "🚁"},
    {"name": "polvo",      "emoji": "🐙"},
    {"name": "girassol",   "emoji": "🌻"},
    {"name": "trompete",   "emoji": "🎺"},
    {"name": "coroa",      "emoji": "👑"},
    {"name": "microscópio","emoji": "🔬"},
    {"name": "âncora",     "emoji": "⚓"},
    {"name": "dragão",     "emoji": "🐉"},
    {"name": "vulcão",     "emoji": "🌋"},
    {"name": "cacto",      "emoji": "🌵"},
    {"name": "cogumelo",   "emoji": "🍄"},
    {"name": "cristal",    "emoji": "💎"},
    {"name": "faro",       "emoji": "🏯"},
    {"name": "tartaruga",  "emoji": "🐢"},
    {"name": "trovoada",   "emoji": "⛈️"},
    {"name": "harpa",      "emoji": "🎵"},
]


class GameStatus(str, Enum):
    WAITING = "waiting"
    PLAYING = "playing"
    VOTING = "voting"
    FINISHED = "finished"


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
    status: str = "pending"   # pending | correct | incorrect
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
    status: str = "pending"   # pending | accepted | rejected
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
        """Serializa o estado, ocultando segredos conforme o espectador."""
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

        guesses_data = []
        for ga in self.guess_attempts.values():
            guesses_data.append({
                "id": ga.id,
                "guesser_id": ga.guesser_id,
                "guesser_name": ga.guesser_name,
                "target_player_id": ga.target_player_id,
                "guess": ga.guess,
                "status": ga.status,
                "timestamp": ga.timestamp,
            })

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


# --------------- Gerenciador de Jogos ---------------

class GameManager:
    def __init__(self):
        self._games: Dict[str, GameState] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        # Filas de eventos por (game_id, player_id)
        self._event_queues: Dict[str, Dict[str, asyncio.Queue]] = {}

    def _get_or_create_lock(self, game_id: str) -> asyncio.Lock:
        if game_id not in self._locks:
            self._locks[game_id] = asyncio.Lock()
        return self._locks[game_id]

    async def subscribe(self, game_id: str, player_id: str) -> asyncio.Queue:
        """Cria uma fila de eventos para um jogador."""
        if game_id not in self._event_queues:
            self._event_queues[game_id] = {}
        q = asyncio.Queue(maxsize=200)
        self._event_queues[game_id][player_id] = q
        return q

    def unsubscribe(self, game_id: str, player_id: str):
        if game_id in self._event_queues:
            self._event_queues[game_id].pop(player_id, None)

    async def _broadcast(self, game_id: str, event_type: str, data: dict, target: str = None):
        """Envia evento para todos (ou para um jogador específico)."""
        event = {
            "event_type": event_type,
            "data": data,
            "timestamp": int(time.time() * 1000),
            "target_player_id": target or "",
        }
        queues = self._event_queues.get(game_id, {})
        for pid, q in queues.items():
            if target is None or target == pid:
                try:
                    q.put_nowait(event)
                except asyncio.QueueFull:
                    pass

    # --------------- Lobby ---------------

    async def create_or_join_game(self, game_id: str, player_name: str):
        """Cria um novo jogo ou entra em um existente. Retorna (player_id, game_id, message)."""
        lock = self._get_or_create_lock(game_id)
        async with lock:
            creating = game_id not in self._games
            if creating:
                game = GameState(game_id=game_id)
                self._games[game_id] = game
            else:
                game = self._games[game_id]

            if game.status != GameStatus.WAITING:
                return None, None, "Jogo já em andamento"

            if any(p.name == player_name for p in game.players.values()):
                return None, None, f"Nome '{player_name}' já está em uso neste jogo"

            player_id = str(uuid.uuid4())[:8]
            is_host = len(game.players) == 0
            player = Player(id=player_id, name=player_name, is_host=is_host)
            game.players[player_id] = player

            await self._broadcast(game_id, "player_joined", {
                "player_id": player_id,
                "player_name": player_name,
                "is_host": is_host,
                "total_players": len(game.players),
            })

            msg = "Jogo criado!" if creating else "Você entrou no jogo!"
            return player_id, game_id, msg

    async def start_game(self, game_id: str, player_id: str, max_turns: int = 5):
        lock = self._get_or_create_lock(game_id)
        async with lock:
            game = self._games.get(game_id)
            if not game:
                return False, "Jogo não encontrado"
            if game.players.get(player_id, None) is None:
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

            self._assign_objects(game)

            # Notifica cada jogador com seu objeto secreto
            for pid, player in game.players.items():
                await self._broadcast(game_id, "game_started", {
                    "your_object_name": player.object_name,
                    "your_object_emoji": player.object_emoji,
                    "max_turns": max_turns,
                    "current_turn": 1,
                    "state": game.to_dict(viewer_id=pid),
                }, target=pid)

            return True, "Jogo iniciado!"

    def _assign_objects(self, game: GameState):
        available = [o for o in OBJECTS if o["name"] not in game.used_objects]
        if len(available) < len(game.players):
            game.used_objects = []
            available = OBJECTS.copy()

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

    # --------------- Hints e Palpites ---------------

    async def send_public_hint(self, game_id: str, player_id: str, hint: str):
        hint = hint.strip().lower()
        if not hint or " " in hint:
            return False, "A dica deve ser uma única palavra"

        lock = self._get_or_create_lock(game_id)
        async with lock:
            game = self._games.get(game_id)
            if not game or game.status != GameStatus.PLAYING:
                return False, "Jogo não está em andamento"

            player = game.players.get(player_id)
            if not player:
                return False, "Jogador não encontrado"
            if player.hint_sent_this_turn:
                return False, "Você já enviou uma dica neste turno"

            player.public_hints.append(hint)
            player.hint_sent_this_turn = True

            await self._broadcast(game_id, "hint_sent", {
                "player_id": player_id,
                "player_name": player.name,
                "hint": hint,
                "turn": game.current_turn,
                "hint_number": len(player.public_hints),
            })
            return True, "Dica enviada!"

    async def guess_object(self, game_id: str, guesser_id: str, target_id: str, guess: str):
        guess = guess.strip().lower()
        if not guess:
            return False, "Palpite não pode ser vazio", None

        lock = self._get_or_create_lock(game_id)
        async with lock:
            game = self._games.get(game_id)
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

            # Verifica se este jogador já tentou adivinhar este alvo
            already_guessed = any(
                ga.guesser_id == guesser_id and ga.target_player_id == target_id
                for ga in game.guess_attempts.values()
            )
            if already_guessed:
                return False, "Você já tentou adivinhar o objeto deste jogador", None

            guess_id = str(uuid.uuid4())[:8]
            attempt = GuessAttempt(
                id=guess_id,
                guesser_id=guesser_id,
                guesser_name=guesser.name,
                target_player_id=target_id,
                guess=guess,
            )
            game.guess_attempts[guess_id] = attempt

            await self._broadcast(game_id, "guess_pending", {
                "guess_id": guess_id,
                "guesser_id": guesser_id,
                "guesser_name": guesser.name,
                "target_player_id": target_id,
                "target_name": target.name,
                "guess": guess,
            })

            # Notifica o dono para validar
            await self._broadcast(game_id, "validate_request", {
                "guess_id": guess_id,
                "guesser_name": guesser.name,
                "guess": guess,
            }, target=target_id)

            return True, "Palpite enviado! Aguardando validação do dono do objeto.", guess_id

    async def validate_guess(self, game_id: str, validator_id: str, guess_id: str, is_correct: bool):
        lock = self._get_or_create_lock(game_id)
        async with lock:
            game = self._games.get(game_id)
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

                # Pontos do adivinhador (imediatos)
                points = FIRST_GUESS_POINTS if first_correct else OTHER_GUESS_POINTS
                guesser.score += points

                if first_correct:
                    target.object_guessed = True

                await self._broadcast(game_id, "guess_result", {
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

                # Avisa se todos adivinharam (pontuação do dono calculada ao final dos turnos)
                n_others = len(game.players) - 1
                if len(target.guessed_by) == n_others:
                    await self._broadcast(game_id, "all_guessed", {
                        "target_player_id": validator_id,
                        "target_name": target.name if target else "?",
                        "object_name": target.object_name if target else "",
                    })
            else:
                attempt.status = "incorrect"
                await self._broadcast(game_id, "guess_result", {
                    "guess_id": guess_id,
                    "guesser_id": attempt.guesser_id,
                    "guesser_name": guesser.name if guesser else "?",
                    "target_player_id": validator_id,
                    "correct": False,
                    "guess": attempt.guess,
                })

            return True, "Validação registrada"

    # --------------- Troca Privada ---------------

    async def request_private_exchange(self, game_id: str, from_id: str, to_id: str, hint: str):
        hint = hint.strip().lower()
        if not hint or " " in hint:
            return False, "A dica deve ser uma única palavra", None

        lock = self._get_or_create_lock(game_id)
        async with lock:
            game = self._games.get(game_id)
            if not game or game.status != GameStatus.PLAYING:
                return False, "Jogo não está em andamento", None

            from_player = game.players.get(from_id)
            to_player = game.players.get(to_id)
            if not from_player or not to_player:
                return False, "Jogador não encontrado", None
            if from_id == to_id:
                return False, "Não pode trocar dicas consigo mesmo", None
            if from_player.private_exchange_used:
                return False, "Você já usou sua troca privada nesta rodada", None

            # Verifica se já existe uma troca pendente entre esses jogadores
            pending = any(
                ex.status == "pending" and
                ((ex.from_id == from_id and ex.to_id == to_id) or
                 (ex.from_id == to_id and ex.to_id == from_id))
                for ex in game.private_exchanges.values()
            )
            if pending:
                return False, "Já existe uma troca pendente com este jogador", None

            exchange_id = str(uuid.uuid4())[:8]
            exchange = PrivateExchange(
                id=exchange_id,
                from_id=from_id,
                from_name=from_player.name,
                to_id=to_id,
                to_name=to_player.name,
                from_hint=hint,
                round=game.current_round,
            )
            game.private_exchanges[exchange_id] = exchange

            # Notifica o alvo
            await self._broadcast(game_id, "exchange_request", {
                "exchange_id": exchange_id,
                "from_id": from_id,
                "from_name": from_player.name,
                "to_id": to_id,
                "to_name": to_player.name,
            }, target=to_id)

            # Avisa outros que uma troca foi solicitada (sem revelar dica)
            await self._broadcast(game_id, "exchange_announced", {
                "exchange_id": exchange_id,
                "from_name": from_player.name,
                "to_name": to_player.name,
            })

            return True, "Solicitação de troca enviada!", exchange_id

    async def respond_to_exchange(self, game_id: str, responder_id: str, exchange_id: str, accept: bool, hint: str = ""):
        hint = hint.strip().lower() if hint else ""
        if accept and (not hint or " " in hint):
            return False, "A dica deve ser uma única palavra"

        lock = self._get_or_create_lock(game_id)
        async with lock:
            game = self._games.get(game_id)
            if not game:
                return False, "Jogo não encontrado"

            exchange = game.private_exchanges.get(exchange_id)
            if not exchange:
                return False, "Troca não encontrada"
            if exchange.to_id != responder_id:
                return False, "Você não é o destinatário desta troca"
            if exchange.status != "pending":
                return False, "Esta troca já foi resolvida"

            from_player = game.players.get(exchange.from_id)
            to_player = game.players.get(exchange.to_id)

            if accept:
                exchange.status = "accepted"
                exchange.to_hint = hint

                if from_player:
                    from_player.private_exchange_used = True
                if to_player:
                    to_player.private_exchange_used = True

                # Envia as dicas para cada participante
                await self._broadcast(game_id, "exchange_accepted", {
                    "exchange_id": exchange_id,
                    "from_name": exchange.from_name,
                    "to_name": exchange.to_name,
                    "your_hint_received": exchange.to_hint,
                    "other_hint": exchange.from_hint,
                }, target=exchange.from_id)

                await self._broadcast(game_id, "exchange_accepted", {
                    "exchange_id": exchange_id,
                    "from_name": exchange.from_name,
                    "to_name": exchange.to_name,
                    "your_hint_received": exchange.from_hint,
                    "other_hint": exchange.to_hint,
                }, target=exchange.to_id)

                # Avisa demais jogadores (sem revelar as dicas)
                await self._broadcast(game_id, "exchange_completed", {
                    "exchange_id": exchange_id,
                    "from_name": exchange.from_name,
                    "to_name": exchange.to_name,
                })
            else:
                exchange.status = "rejected"
                await self._broadcast(game_id, "exchange_rejected", {
                    "exchange_id": exchange_id,
                    "from_name": exchange.from_name,
                    "to_name": exchange.to_name,
                })

            return True, "Aceito!" if accept else "Recusado."

    # --------------- Espionagem ---------------

    async def spy_on_exchange(self, game_id: str, spy_id: str, exchange_id: str):
        lock = self._get_or_create_lock(game_id)
        async with lock:
            game = self._games.get(game_id)
            if not game:
                return False, "Jogo não encontrado", False, None, None

            exchange = game.private_exchanges.get(exchange_id)
            if not exchange:
                return False, "Troca não encontrada", False, None, None
            if exchange.status != "accepted":
                return False, "Só é possível espionar trocas concluídas", False, None, None
            if spy_id in [exchange.from_id, exchange.to_id]:
                return False, "Você não pode espionar sua própria troca", False, None, None
            if spy_id in exchange.spies_succeeded or spy_id in exchange.spies_caught:
                return False, "Você já tentou espionar esta troca", False, None, None

            spy = game.players.get(spy_id)
            discovered = random.random() < SPY_CATCH_CHANCE

            if discovered:
                exchange.spies_caught.append(spy_id)
                if spy:
                    spy.score += SPY_CAUGHT_PENALTY

                # Notifica os participantes da troca que foram espionados
                for pid in [exchange.from_id, exchange.to_id]:
                    await self._broadcast(game_id, "spy_caught", {
                        "spy_id": spy_id,
                        "spy_name": spy.name if spy else "?",
                        "exchange_id": exchange_id,
                        "score_delta": SPY_CAUGHT_PENALTY,
                    }, target=pid)

                # Notifica o espião
                await self._broadcast(game_id, "you_were_caught_spying", {
                    "exchange_id": exchange_id,
                    "score_delta": SPY_CAUGHT_PENALTY,
                }, target=spy_id)

                # Avisa todos sobre a tentativa
                await self._broadcast(game_id, "spy_attempt", {
                    "spy_name": spy.name if spy else "?",
                    "target1_name": exchange.from_name,
                    "target2_name": exchange.to_name,
                    "discovered": True,
                })

                return True, "Você foi descoberto espiando!", True, None, None
            else:
                exchange.spies_succeeded.append(spy_id)

                await self._broadcast(game_id, "spy_attempt", {
                    "spy_name": spy.name if spy else "?",
                    "target1_name": exchange.from_name,
                    "target2_name": exchange.to_name,
                    "discovered": False,
                })

                return True, "Você espionou com sucesso!", False, exchange.from_hint, exchange.to_hint

    # --------------- Avanço de Turno ---------------

    async def advance_turn(self, game_id: str, player_id: str):
        lock = self._get_or_create_lock(game_id)
        async with lock:
            game = self._games.get(game_id)
            if not game or game.status != GameStatus.PLAYING:
                return False, "Jogo não está em andamento"

            player = game.players.get(player_id)
            if not player or not player.is_host:
                return False, "Apenas o host pode avançar o turno"

            if game.current_turn >= game.max_turns:
                # Fim dos turnos, calcula pontuação do dono
                self._calculate_owner_scores(game)
                game.status = GameStatus.VOTING
                await self._broadcast(game_id, "voting_started", {
                    "scores": {pid: p.score for pid, p in game.players.items()},
                    "state": game.to_dict(),
                })
                return True, "Limite de turnos atingido! Votação iniciada."

            game.current_turn += 1
            # Reset hint_sent_this_turn para todos
            for p in game.players.values():
                p.hint_sent_this_turn = False

            await self._broadcast(game_id, "turn_advanced", {
                "current_turn": game.current_turn,
                "max_turns": game.max_turns,
            })
            return True, f"Turno {game.current_turn} iniciado!"

    def _calculate_owner_scores(self, game: GameState):
        """
        Calcula pontos do dono com base em quantos adivinharam seu objeto.
        Também aplica bônus de único acertador.
        Chamado apenas uma vez, ao fim dos turnos.
        """
        n_others = len(game.players) - 1
        if n_others <= 0:
            return

        # Pontuação dos donos
        for pid, player in game.players.items():
            n_guessed = len(player.guessed_by)
            if n_guessed == 0:
                pass  # sem pontos
            elif n_guessed == n_others:
                player.score += OWNER_ALL_PENALTY
            elif n_guessed == 1:
                player.score += OWNER_SOLO_POINTS
            else:
                player.score += OWNER_MULTI_POINTS

        # Bônus de único acertador: jogador que foi o único a adivinhar algum objeto
        for pid, player in game.players.items():
            for target_id, target in game.players.items():
                if target_id == pid:
                    continue
                if len(target.guessed_by) == 1 and target.guessed_by[0] == pid:
                    player.score += SOLO_BONUS_POINTS

    # --------------- Votação ---------------

    async def vote_continue(self, game_id: str, player_id: str, continue_game: bool):
        lock = self._get_or_create_lock(game_id)
        async with lock:
            game = self._games.get(game_id)
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

            await self._broadcast(game_id, "vote_update", {
                "votes_continue": len(game.votes_continue),
                "votes_end": len(game.votes_end),
                "total_players": n_players,
            })

            if votes_in == n_players:
                if len(game.votes_continue) > len(game.votes_end):
                    # Nova rodada
                    game.current_round += 1
                    game.current_turn = 1
                    game.status = GameStatus.PLAYING
                    game.votes_continue.clear()
                    game.votes_end.clear()
                    game.guess_attempts.clear()
                    game.private_exchanges.clear()
                    self._assign_objects(game)

                    for pid, p in game.players.items():
                        p.hint_sent_this_turn = False
                        await self._broadcast(game_id, "new_round", {
                            "round": game.current_round,
                            "your_object_name": p.object_name,
                            "your_object_emoji": p.object_emoji,
                            "state": game.to_dict(viewer_id=pid),
                        }, target=pid)
                else:
                    game.status = GameStatus.FINISHED
                    scores = sorted(
                        [{"id": pid, "name": p.name, "score": p.score} for pid, p in game.players.items()],
                        key=lambda x: x["score"], reverse=True
                    )
                    await self._broadcast(game_id, "game_finished", {
                        "final_scores": scores,
                        "state": game.to_dict(),
                    })

            return True, "Voto registrado"

    # --------------- Estado ---------------

    def get_game(self, game_id: str) -> Optional[GameState]:
        return self._games.get(game_id)

    def game_exists(self, game_id: str) -> bool:
        return game_id in self._games


# Singleton global
game_manager = GameManager()
