import asyncio
import json
import logging
import os
import sys
import time

import grpc
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from contextlib import asynccontextmanager

sys.path.insert(0, os.path.dirname(__file__))
from generated import game_pb2, game_pb2_grpc

logging.basicConfig(level=logging.INFO, format="%(asctime)s [GATEWAY] %(message)s")
logger = logging.getLogger(__name__)

GRPC_HOST = os.environ.get("GRPC_HOST", "localhost")
GRPC_PORT = os.environ.get("GRPC_PORT", "50051")
GRPC_ADDRESS = f"{GRPC_HOST}:{GRPC_PORT}"
HTTP_PORT = int(os.environ.get("HTTP_PORT", "8000"))


def get_stub():
    channel = grpc.aio.insecure_channel(GRPC_ADDRESS)
    return game_pb2_grpc.GameServiceStub(channel), channel


async def call_grpc(method_name: str, request_obj):
    async with grpc.aio.insecure_channel(GRPC_ADDRESS) as channel:
        stub = game_pb2_grpc.GameServiceStub(channel)
        method = getattr(stub, method_name)
        return await method(request_obj)


class JoinBody(BaseModel):
    player_name: str
    game_id: str = ""

class StartBody(BaseModel):
    player_id: str
    game_id: str
    max_turns: int = 5

class HintBody(BaseModel):
    player_id: str
    game_id: str
    hint: str

class GuessBody(BaseModel):
    guesser_id: str
    game_id: str
    target_player_id: str
    guess: str

class ValidateBody(BaseModel):
    validator_id: str
    game_id: str
    guess_id: str
    is_correct: bool

class AdvanceTurnBody(BaseModel):
    player_id: str
    game_id: str

class ExchangeBody(BaseModel):
    from_id: str
    to_id: str
    game_id: str
    hint: str

class ExchangeRespondBody(BaseModel):
    responder_id: str
    game_id: str
    exchange_id: str
    accept: bool
    hint: str = ""

class SpyBody(BaseModel):
    spy_id: str
    game_id: str
    exchange_id: str

class VoteBody(BaseModel):
    player_id: str
    game_id: str
    continue_game: bool

class ChatBody(BaseModel):
    player_id: str
    player_name: str
    game_id: str
    message: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Gateway iniciado, conectando ao gRPC em {GRPC_ADDRESS}")
    yield
    logger.info("Gateway encerrando")


app = FastAPI(title="GuessingGame Gateway", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok", "grpc": GRPC_ADDRESS}


@app.post("/api/join")
async def join_game(body: JoinBody):
    resp = await call_grpc("JoinGame", game_pb2.JoinRequest(
        player_name=body.player_name,
        game_id=body.game_id,
    ))
    return {
        "success": resp.success,
        "player_id": resp.player_id,
        "game_id": resp.game_id,
        "message": resp.message,
    }


@app.post("/api/start")
async def start_game(body: StartBody):
    resp = await call_grpc("StartGame", game_pb2.StartGameRequest(
        player_id=body.player_id,
        game_id=body.game_id,
        max_turns=body.max_turns,
    ))
    return {"success": resp.success, "message": resp.message}


@app.get("/api/state/{game_id}/{player_id}")
async def get_state(game_id: str, player_id: str):
    resp = await call_grpc("GetGameState", game_pb2.PlayerRequest(
        player_id=player_id,
        game_id=game_id,
    ))
    if not resp.success:
        raise HTTPException(status_code=404, detail=resp.message)
    return json.loads(resp.state_json)


@app.post("/api/hint")
async def send_hint(body: HintBody):
    resp = await call_grpc("SendPublicHint", game_pb2.HintRequest(
        player_id=body.player_id,
        game_id=body.game_id,
        hint=body.hint,
    ))
    return {"success": resp.success, "message": resp.message}


@app.post("/api/guess")
async def guess_object(body: GuessBody):
    resp = await call_grpc("GuessObject", game_pb2.GuessRequest(
        guesser_id=body.guesser_id,
        game_id=body.game_id,
        target_player_id=body.target_player_id,
        guess=body.guess,
    ))
    data = json.loads(resp.data) if resp.data else {}
    return {"success": resp.success, "message": resp.message, **data}


@app.post("/api/validate")
async def validate_guess(body: ValidateBody):
    resp = await call_grpc("ValidateGuess", game_pb2.ValidateRequest(
        validator_id=body.validator_id,
        game_id=body.game_id,
        guess_id=body.guess_id,
        is_correct=body.is_correct,
    ))
    return {"success": resp.success, "message": resp.message}


@app.post("/api/advance-turn")
async def advance_turn(body: AdvanceTurnBody):
    resp = await call_grpc("AdvanceTurn", game_pb2.PlayerRequest(
        player_id=body.player_id,
        game_id=body.game_id,
    ))
    return {"success": resp.success, "message": resp.message}


@app.post("/api/exchange/request")
async def request_exchange(body: ExchangeBody):
    resp = await call_grpc("RequestPrivateExchange", game_pb2.ExchangeRequest(
        from_id=body.from_id,
        to_id=body.to_id,
        game_id=body.game_id,
        hint=body.hint,
    ))
    data = json.loads(resp.data) if resp.data else {}
    return {"success": resp.success, "message": resp.message, **data}


@app.post("/api/exchange/respond")
async def respond_exchange(body: ExchangeRespondBody):
    resp = await call_grpc("RespondToExchange", game_pb2.ExchangeResponseRequest(
        responder_id=body.responder_id,
        game_id=body.game_id,
        exchange_id=body.exchange_id,
        accept=body.accept,
        hint=body.hint,
    ))
    return {"success": resp.success, "message": resp.message}


@app.post("/api/spy")
async def spy_on_exchange(body: SpyBody):
    resp = await call_grpc("SpyOnExchange", game_pb2.SpyRequest(
        spy_id=body.spy_id,
        game_id=body.game_id,
        exchange_id=body.exchange_id,
    ))
    data = json.loads(resp.data) if resp.data else {}
    return {"success": resp.success, "message": resp.message, **data}


@app.post("/api/vote")
async def vote_continue(body: VoteBody):
    resp = await call_grpc("VoteContinue", game_pb2.VoteRequest(
        player_id=body.player_id,
        game_id=body.game_id,
        continue_game=body.continue_game,
    ))
    return {"success": resp.success, "message": resp.message}


@app.post("/api/chat")
async def send_chat(body: ChatBody):
    resp = await call_grpc("SendChatMessage", game_pb2.ChatMessageRequest(
        player_id=body.player_id,
        player_name=body.player_name,
        game_id=body.game_id,
        message=body.message,
    ))
    return {"success": resp.success, "message": resp.message}


@app.get("/api/chat/{game_id}")
async def get_chat(game_id: str, limit: int = 50):
    resp = await call_grpc("GetChatHistory", game_pb2.ChatHistoryRequest(
        game_id=game_id,
        limit=limit,
    ))
    return [
        {
            "player_id": m.player_id,
            "player_name": m.player_name,
            "message": m.message,
            "timestamp": m.timestamp,
        }
        for m in resp.messages
    ]


@app.websocket("/ws/{game_id}/{player_id}")
async def websocket_relay(websocket: WebSocket, game_id: str, player_id: str):
    await websocket.accept()
    logger.info(f"WebSocket conectado: player={player_id}, game={game_id}")

    try:
        async with grpc.aio.insecure_channel(GRPC_ADDRESS) as channel:
            stub = game_pb2_grpc.GameServiceStub(channel)

            stream = stub.StreamEvents(game_pb2.StreamRequest(
                player_id=player_id,
                game_id=game_id,
            ))

            async for event in stream:
                try:
                    payload = {
                        "event_type": event.event_type,
                        "data": json.loads(event.data) if event.data else {},
                        "timestamp": event.timestamp,
                        "target_player_id": event.target_player_id,
                    }
                    await websocket.send_json(payload)
                except WebSocketDisconnect:
                    break
                except Exception as e:
                    logger.error(f"Erro ao enviar evento: {e}")
                    break

    except WebSocketDisconnect:
        logger.info(f"WebSocket desconectado: player={player_id}")
    except Exception as e:
        logger.error(f"Erro no WebSocket {player_id}: {e}")
    finally:
        logger.info(f"WebSocket encerrado: player={player_id}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=HTTP_PORT, log_level="info")
