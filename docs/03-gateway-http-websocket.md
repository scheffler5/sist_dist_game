# 3. Gateway HTTP / WebSocket

O gateway é o ponto de entrada para o navegador. Implementado em [`back-end/gateway.py`](../back-end/gateway.py) com FastAPI + Uvicorn, ele expõe duas interfaces e atua como **cliente gRPC** internamente.

## Diagrama

```
   Browser
     │
     │  fetch(...) JSON                  new WebSocket(...)
     │      ▼                                   ▼
     │   ┌───────────────────────────────────────────────┐
     │   │  Gateway (FastAPI, porta 8000)                │
     │   │                                               │
     │   │  /api/* (REST)         /ws/{game}/{player}    │
     │   │     │                       │                 │
     │   │     ▼                       ▼                 │
     │   │  call_grpc(method)      websocket_relay()     │
     │   │     │                       │                 │
     │   └─────┼───────────────────────┼─────────────────┘
               │                       │
               │ unário                │ server-streaming
               ▼                       ▼
          gRPC GameServer (porta 50051)
```

## Estrutura do código

```
gateway.py
├── Helpers
│   ├── get_stub()             cria channel gRPC
│   └── call_grpc(method, req) chamada unária → resposta
├── Modelos Pydantic           validam/desserializam JSON dos POSTs
│   ├── JoinBody, StartBody, HintBody, GuessBody, ...
├── Lifespan / app             FastAPI com CORS aberto
├── Endpoints HTTP REST        14 rotas /api/*
└── Endpoint WebSocket         relay /ws/{game_id}/{player_id}
```

## Endpoints HTTP REST

Cada rota:

1. Recebe um `BaseModel` Pydantic (validação automática).
2. Monta a `Request` proto correspondente.
3. Chama `call_grpc(<MethodName>, request)`.
4. Re-empacota a resposta como JSON, fazendo `json.loads(resp.data)` quando há payload extra.

### Tabela completa

| Método | Rota | Body / Query | Chama RPC | Devolve |
|---|---|---|---|---|
| `POST` | `/api/join` | `{player_name, game_id?}` | `JoinGame` | `{success, player_id, game_id, message}` |
| `POST` | `/api/start` | `{player_id, game_id, max_turns?}` | `StartGame` | `{success, message}` |
| `GET`  | `/api/state/{game_id}/{player_id}` | — | `GetGameState` | snapshot completo (objeto `state`) |
| `POST` | `/api/hint` | `{player_id, game_id, hint}` | `SendPublicHint` | `{success, message}` |
| `POST` | `/api/guess` | `{guesser_id, game_id, target_player_id, guess}` | `GuessObject` | `{success, message, guess_id?}` |
| `POST` | `/api/validate` | `{validator_id, game_id, guess_id, is_correct}` | `ValidateGuess` | `{success, message}` |
| `POST` | `/api/advance-turn` | `{player_id, game_id}` | `AdvanceTurn` | `{success, message}` |
| `POST` | `/api/exchange/request` | `{from_id, to_id, game_id, hint}` | `RequestPrivateExchange` | `{success, message, exchange_id?}` |
| `POST` | `/api/exchange/respond` | `{responder_id, game_id, exchange_id, accept, hint?}` | `RespondToExchange` | `{success, message}` |
| `POST` | `/api/spy` | `{spy_id, game_id, exchange_id}` | `SpyOnExchange` | `{success, message, discovered?, hint1?, hint2?}` |
| `POST` | `/api/vote` | `{player_id, game_id, continue_game}` | `VoteContinue` | `{success, message}` |
| `POST` | `/api/chat` | `{player_id, player_name, game_id, message}` | `SendChatMessage` | `{success, message}` |
| `GET`  | `/api/chat/{game_id}?limit=50` | — | `GetChatHistory` | `[{player_id, player_name, message, timestamp}, ...]` |
| `GET`  | `/health` | — | (não chama gRPC) | `{status, grpc}` |

### Padrão de uma rota

```python
@app.post("/api/spy")
async def spy_on_exchange(body: SpyBody):
    resp = await call_grpc("SpyOnExchange", game_pb2.SpyRequest(
        spy_id=body.spy_id,
        game_id=body.game_id,
        exchange_id=body.exchange_id,
    ))
    data = json.loads(resp.data) if resp.data else {}
    return {"success": resp.success, "message": resp.message, **data}
```

A simplicidade é proposital: o gateway é uma fina camada de tradução. Toda regra de negócio vive no gRPC server.

### `call_grpc` — abertura de canal por chamada

```python
async def call_grpc(method_name: str, request_obj):
    async with grpc.aio.insecure_channel(GRPC_ADDRESS) as channel:
        stub = game_pb2_grpc.GameServiceStub(channel)
        method = getattr(stub, method_name)
        return await method(request_obj)
```

Cada chamada cria e fecha um channel. Para um servidor de tráfego baixo (uma LAN com poucos jogadores) isso é aceitável. Em uma versão mais otimizada, manteria-se um channel global e estaria reusando o stub.

## WebSocket — relay do streaming gRPC

A rota `/ws/{game_id}/{player_id}` em [`gateway.py:292`](../back-end/gateway.py) faz a **bridge** entre o servidor de jogo (server-streaming gRPC) e o navegador (WebSocket).

```python
@app.websocket("/ws/{game_id}/{player_id}")
async def websocket_relay(websocket: WebSocket, game_id: str, player_id: str):
    await websocket.accept()
    try:
        async with grpc.aio.insecure_channel(GRPC_ADDRESS) as channel:
            stub = game_pb2_grpc.GameServiceStub(channel)
            stream = stub.StreamEvents(game_pb2.StreamRequest(
                player_id=player_id,
                game_id=game_id,
            ))

            async for event in stream:
                payload = {
                    "event_type": event.event_type,
                    "data": json.loads(event.data) if event.data else {},
                    "timestamp": event.timestamp,
                    "target_player_id": event.target_player_id,
                }
                await websocket.send_json(payload)
    except WebSocketDisconnect:
        ...
```

### Garantias e comportamento

- **1 WebSocket por jogador** — o front fecha o WS anterior antes de abrir um novo.
- **Snapshot inicial** — o servidor envia `initial_state` como primeiro evento, com o objeto secreto e o estado completo.
- **Heartbeat** — a cada 25s sem eventos, o servidor envia `{"event_type": "heartbeat", ...}` para manter a conexão viva atrás de proxies (incluindo o nginx, configurado com `proxy_read_timeout 3600s`).
- **Reconexão automática no cliente** — em `app.js`, o `onclose` reagenda `connectWS()` em 3s.
- **Decodificação de payload** — `event.data` chega do gRPC como string JSON; o gateway desserializa antes de enviar ao navegador.

### Roteamento privado

Quando um evento tem `target_player_id` preenchido, ele só foi enfileirado na queue daquele jogador (filtragem no `EventBus.broadcast`). Mesmo assim, o cliente também ignora eventos cujo `target_player_id` não bate (defensivo, em `app.js:113-114`):

```javascript
function handleEvent(type, data) {
  if (data && data.target_player_id && data.target_player_id !== state.playerId) return;
  ...
}
```

## CORS e segurança

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
```

CORS aberto. **Não há autenticação**: o `player_id` é gerado no `JoinGame` e usado como token implícito. Qualquer cliente que conheça o `player_id` e o `game_id` pode agir em nome daquele jogador. Para o escopo (LAN, jogo casual) isso é suficiente; em produção, seria preciso assinar tokens.

## Variáveis de ambiente

| Variável | Padrão | Uso |
|---|---|---|
| `GRPC_HOST` | `localhost` | Host do gRPC server (mesmo container, então loopback) |
| `GRPC_PORT` | `50051` | Porta do gRPC server |
| `HTTP_PORT` | `8000` | Porta do gateway |

## Health check

`GET /health` retorna `{"status": "ok", "grpc": "<host>:<port>"}` sem efetivamente checar a conexão gRPC. O Compose usa um healthcheck no Mongo, mas não no backend — restarts automáticos vêm da policy `restart: unless-stopped`.

## Por que duas interfaces (REST + WebSocket)

- **REST** é o canal de **comando**: o cliente fala "faz isso" e recebe ack. Naturalmente request/response.
- **WebSocket** é o canal de **notificação**: o servidor empurra o que muda quando muda. Sem polling.

Os dois canais convergem no mesmo gateway, na mesma porta, no mesmo processo. Compartilham o estado do jogo via gRPC (que é a única coisa que de fato mantém estado).
