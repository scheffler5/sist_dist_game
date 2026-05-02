import uuid
from typing import Optional, Tuple

from domain.constants import GameStatus
from domain.models import PrivateExchange
from services.base import BaseService


class ExchangeService(BaseService):

    async def request_private_exchange(
        self, game_id: str, from_id: str, to_id: str, hint: str
    ) -> Tuple[bool, str, Optional[str]]:
        hint = hint.strip().lower()
        if not hint or " " in hint:
            return False, "A dica deve ser uma única palavra", None

        async with self._get_lock(game_id):
            game = self._get_game(game_id)
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

            pending = any(
                ex.status == "pending" and (
                    (ex.from_id == from_id and ex.to_id == to_id) or
                    (ex.from_id == to_id and ex.to_id == from_id)
                )
                for ex in game.private_exchanges.values()
            )
            if pending:
                return False, "Já existe uma troca pendente com este jogador", None

            exchange_id = str(uuid.uuid4())[:8]
            game.private_exchanges[exchange_id] = PrivateExchange(
                id=exchange_id,
                from_id=from_id,
                from_name=from_player.name,
                to_id=to_id,
                to_name=to_player.name,
                from_hint=hint,
                round=game.current_round,
            )

            await self._bus.broadcast(game_id, "exchange_request", {
                "exchange_id": exchange_id,
                "from_id": from_id,
                "from_name": from_player.name,
                "to_id": to_id,
                "to_name": to_player.name,
            }, target=to_id)

            await self._bus.broadcast(game_id, "exchange_announced", {
                "exchange_id": exchange_id,
                "from_name": from_player.name,
                "to_name": to_player.name,
            })

            return True, "Solicitação de troca enviada!", exchange_id

    async def respond_to_exchange(
        self,
        game_id: str,
        responder_id: str,
        exchange_id: str,
        accept: bool,
        hint: str = "",
    ) -> Tuple[bool, str]:
        hint = hint.strip().lower() if hint else ""
        if accept and (not hint or " " in hint):
            return False, "A dica deve ser uma única palavra"

        async with self._get_lock(game_id):
            game = self._get_game(game_id)
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

                await self._bus.broadcast(game_id, "exchange_accepted", {
                    "exchange_id": exchange_id,
                    "from_name": exchange.from_name,
                    "to_name": exchange.to_name,
                    "your_hint_received": exchange.to_hint,
                    "other_hint": exchange.from_hint,
                }, target=exchange.from_id)

                await self._bus.broadcast(game_id, "exchange_accepted", {
                    "exchange_id": exchange_id,
                    "from_name": exchange.from_name,
                    "to_name": exchange.to_name,
                    "your_hint_received": exchange.from_hint,
                    "other_hint": exchange.to_hint,
                }, target=exchange.to_id)

                await self._bus.broadcast(game_id, "exchange_completed", {
                    "exchange_id": exchange_id,
                    "from_name": exchange.from_name,
                    "to_name": exchange.to_name,
                })
                return True, "Aceito!"
            else:
                exchange.status = "rejected"
                await self._bus.broadcast(game_id, "exchange_rejected", {
                    "exchange_id": exchange_id,
                    "from_name": exchange.from_name,
                    "to_name": exchange.to_name,
                })
                return True, "Recusado."
