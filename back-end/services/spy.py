import random
from typing import Optional, Tuple

from domain.constants import SPY_CATCH_CHANCE, SPY_CAUGHT_PENALTY
from services.base import BaseService


class SpyService(BaseService):

    async def spy_on_exchange(
        self, game_id: str, spy_id: str, exchange_id: str
    ) -> Tuple[bool, str, bool, Optional[str], Optional[str]]:
        """Retorna (ok, message, discovered, hint1, hint2)."""
        async with self._get_lock(game_id):
            game = self._get_game(game_id)
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

                for pid in [exchange.from_id, exchange.to_id]:
                    await self._bus.broadcast(game_id, "spy_caught", {
                        "spy_id": spy_id,
                        "spy_name": spy.name if spy else "?",
                        "exchange_id": exchange_id,
                        "score_delta": SPY_CAUGHT_PENALTY,
                    }, target=pid)

                await self._bus.broadcast(game_id, "you_were_caught_spying", {
                    "exchange_id": exchange_id,
                    "score_delta": SPY_CAUGHT_PENALTY,
                }, target=spy_id)

                await self._bus.broadcast(game_id, "spy_attempt", {
                    "spy_name": spy.name if spy else "?",
                    "target1_name": exchange.from_name,
                    "target2_name": exchange.to_name,
                    "discovered": True,
                })
                return True, "Você foi descoberto espiando!", True, None, None
            else:
                exchange.spies_succeeded.append(spy_id)

                await self._bus.broadcast(game_id, "spy_attempt", {
                    "spy_name": spy.name if spy else "?",
                    "target1_name": exchange.from_name,
                    "target2_name": exchange.to_name,
                    "discovered": False,
                })
                return True, "Você espionou com sucesso!", False, exchange.from_hint, exchange.to_hint
