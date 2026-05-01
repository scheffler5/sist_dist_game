"""
Servidor gRPC do jogo de adivinhação.
Implementa todos os RPCs definidos em game.proto usando grpc.aio (async).
"""

import asyncio
import json
import logging
import time
import os
import sys

import grpc

# Importa os módulos gerados pelo protoc
sys.path.insert(0, os.path.dirname(__file__))
from generated import game_pb2, game_pb2_grpc
from game_logic import game_manager
from database import db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [SERVER] %(message)s")
logger = logging.getLogger(__name__)

GRPC_PORT = int(os.environ.get("GRPC_PORT", "50051"))


class GameServiceServicer(game_pb2_grpc.GameServiceServicer):

    # ==================== Lobby ====================

    async def JoinGame(self, request, context):
        player_id, game_id, message = await game_manager.create_or_join_game(
            game_id=request.game_id or _generate_game_id(),
            player_name=request.player_name,
        )
        if player_id is None:
            return game_pb2.JoinResponse(success=False, message=message)

        logger.info(f"Player '{request.player_name}' joined game {game_id}")
        return game_pb2.JoinResponse(
            success=True,
            player_id=player_id,
            game_id=game_id,
            message=message,
        )

    async def GetGameState(self, request, context):
        game = game_manager.get_game(request.game_id)
        if not game:
            return game_pb2.GameStateResponse(success=False, message="Jogo não encontrado")

        state = game.to_dict(viewer_id=request.player_id)
        return game_pb2.GameStateResponse(
            success=True,
            state_json=json.dumps(state, ensure_ascii=False),
        )

    async def StartGame(self, request, context):
        max_turns = request.max_turns if request.max_turns > 0 else 5
        ok, msg = await game_manager.start_game(
            game_id=request.game_id,
            player_id=request.player_id,
            max_turns=max_turns,
        )
        return game_pb2.ActionResponse(success=ok, message=msg)

    async def KickPlayer(self, request, context):
        game = game_manager.get_game(request.game_id)
        if not game:
            return game_pb2.ActionResponse(success=False, message="Jogo não encontrado")

        host = game.players.get(request.host_id)
        if not host or not host.is_host:
            return game_pb2.ActionResponse(success=False, message="Apenas o host pode remover jogadores")

        target = game.players.get(request.target_id)
        if not target:
            return game_pb2.ActionResponse(success=False, message="Jogador não encontrado")

        del game.players[request.target_id]
        await game_manager._broadcast(request.game_id, "player_kicked", {
            "player_id": request.target_id,
            "player_name": target.name,
        })
        return game_pb2.ActionResponse(success=True, message=f"{target.name} removido do jogo")

    # ==================== Gameplay ====================

    async def SendPublicHint(self, request, context):
        ok, msg = await game_manager.send_public_hint(
            game_id=request.game_id,
            player_id=request.player_id,
            hint=request.hint,
        )
        return game_pb2.ActionResponse(success=ok, message=msg)

    async def GuessObject(self, request, context):
        ok, msg, guess_id = await game_manager.guess_object(
            game_id=request.game_id,
            guesser_id=request.guesser_id,
            target_id=request.target_player_id,
            guess=request.guess,
        )
        data = json.dumps({"guess_id": guess_id}) if guess_id else ""
        return game_pb2.ActionResponse(success=ok, message=msg, data=data)

    async def ValidateGuess(self, request, context):
        ok, msg = await game_manager.validate_guess(
            game_id=request.game_id,
            validator_id=request.validator_id,
            guess_id=request.guess_id,
            is_correct=request.is_correct,
        )
        return game_pb2.ActionResponse(success=ok, message=msg)

    async def AdvanceTurn(self, request, context):
        ok, msg = await game_manager.advance_turn(
            game_id=request.game_id,
            player_id=request.player_id,
        )
        return game_pb2.ActionResponse(success=ok, message=msg)

    # ==================== Troca Privada ====================

    async def RequestPrivateExchange(self, request, context):
        ok, msg, exchange_id = await game_manager.request_private_exchange(
            game_id=request.game_id,
            from_id=request.from_id,
            to_id=request.to_id,
            hint=request.hint,
        )
        data = json.dumps({"exchange_id": exchange_id}) if exchange_id else ""
        return game_pb2.ActionResponse(success=ok, message=msg, data=data)

    async def RespondToExchange(self, request, context):
        ok, msg = await game_manager.respond_to_exchange(
            game_id=request.game_id,
            responder_id=request.responder_id,
            exchange_id=request.exchange_id,
            accept=request.accept,
            hint=request.hint,
        )
        return game_pb2.ActionResponse(success=ok, message=msg)

    # ==================== Espionagem ====================

    async def SpyOnExchange(self, request, context):
        ok, msg, discovered, hint1, hint2 = await game_manager.spy_on_exchange(
            game_id=request.game_id,
            spy_id=request.spy_id,
            exchange_id=request.exchange_id,
        )
        data = ""
        if ok:
            data = json.dumps({
                "discovered": discovered,
                "hint1": hint1 or "",
                "hint2": hint2 or "",
            })
        return game_pb2.ActionResponse(success=ok, message=msg, data=data)

    # ==================== Votação ====================

    async def VoteContinue(self, request, context):
        ok, msg = await game_manager.vote_continue(
            game_id=request.game_id,
            player_id=request.player_id,
            continue_game=request.continue_game,
        )
        return game_pb2.ActionResponse(success=ok, message=msg)

    # ==================== Chat ====================

    async def SendChatMessage(self, request, context):
        try:
            await db.save_chat_message(
                game_id=request.game_id,
                player_id=request.player_id,
                player_name=request.player_name,
                message=request.message,
            )
            await game_manager._broadcast(request.game_id, "chat_message", {
                "player_id": request.player_id,
                "player_name": request.player_name,
                "message": request.message,
                "timestamp": int(time.time() * 1000),
            })
            return game_pb2.ActionResponse(success=True, message="Mensagem enviada")
        except Exception as e:
            logger.error(f"Erro ao salvar chat: {e}")
            return game_pb2.ActionResponse(success=False, message=str(e))

    async def GetChatHistory(self, request, context):
        try:
            messages = await db.get_chat_history(
                game_id=request.game_id,
                limit=request.limit or 50,
            )
            proto_msgs = [
                game_pb2.ChatMessage(
                    player_id=m["player_id"],
                    player_name=m["player_name"],
                    message=m["message"],
                    timestamp=m["timestamp"],
                )
                for m in messages
            ]
            return game_pb2.ChatHistoryResponse(messages=proto_msgs)
        except Exception as e:
            logger.error(f"Erro ao buscar histórico: {e}")
            return game_pb2.ChatHistoryResponse()

    # ==================== Stream de Eventos ====================

    async def StreamEvents(self, request, context):
        """Server-side streaming: envia eventos em tempo real para o cliente."""
        game_id = request.game_id
        player_id = request.player_id

        logger.info(f"Player {player_id} subscribed to events for game {game_id}")

        queue = await game_manager.subscribe(game_id, player_id)

        try:
            # Envia estado inicial
            game = game_manager.get_game(game_id)
            if game:
                state = game.to_dict(viewer_id=player_id)
                player = game.players.get(player_id)
                yield game_pb2.GameEvent(
                    event_type="initial_state",
                    data=json.dumps({
                        "state": state,
                        "your_object_name": player.object_name if player and game.status != "waiting" else "",
                        "your_object_emoji": player.object_emoji if player and game.status != "waiting" else "",
                    }, ensure_ascii=False),
                    timestamp=int(time.time() * 1000),
                )

            # Stream contínuo
            while True:
                if context.cancelled():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=25.0)
                    yield game_pb2.GameEvent(
                        event_type=event["event_type"],
                        data=json.dumps(event["data"], ensure_ascii=False),
                        timestamp=event["timestamp"],
                        target_player_id=event.get("target_player_id", ""),
                    )
                except asyncio.TimeoutError:
                    # Heartbeat para manter a conexão viva
                    yield game_pb2.GameEvent(
                        event_type="heartbeat",
                        data="{}",
                        timestamp=int(time.time() * 1000),
                    )
        except Exception as e:
            logger.error(f"Stream error for {player_id}: {e}")
        finally:
            game_manager.unsubscribe(game_id, player_id)
            logger.info(f"Player {player_id} unsubscribed from game {game_id}")


def _generate_game_id() -> str:
    import random
    import string
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


async def serve():
    await db.connect()

    server = grpc.aio.server()
    game_pb2_grpc.add_GameServiceServicer_to_server(GameServiceServicer(), server)
    listen_addr = f"0.0.0.0:{GRPC_PORT}"
    server.add_insecure_port(listen_addr)
    logger.info(f"gRPC server starting on {listen_addr}")
    await server.start()
    await server.wait_for_termination()


if __name__ == "__main__":
    asyncio.run(serve())
