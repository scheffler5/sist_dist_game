# 2. RPC e contrato gRPC

O contrato que define toda a comunicação entre o gateway e o servidor de jogo está em [`back-end/protos/game.proto`](../back-end/protos/game.proto). É a fonte da verdade — qualquer mudança regenera os stubs Python automaticamente.

## Geração dos stubs

O entrypoint do container ([`entrypoint.sh`](../back-end/entrypoint.sh)) executa, no boot:

```bash
python -m grpc_tools.protoc \
  -I /app/protos \
  --python_out=/app/generated \
  --grpc_python_out=/app/generated \
  /app/protos/game.proto

# Corrige imports relativos
sed -i 's/^import game_pb2/from generated import game_pb2/' /app/generated/game_pb2_grpc.py
```

Isso produz dois módulos em `/app/generated/`:

- `game_pb2.py` — classes de mensagem (`JoinRequest`, `GameEvent`, etc.).
- `game_pb2_grpc.py` — stubs do servidor (`GameServiceServicer`) e cliente (`GameServiceStub`).

A regeneração é automática a cada boot do container, garantindo que mudanças no `.proto` se propaguem sem etapa manual.

## O serviço

```protobuf
service GameService {
  // Lobby
  rpc JoinGame(JoinRequest) returns (JoinResponse);
  rpc GetGameState(PlayerRequest) returns (GameStateResponse);
  rpc StartGame(StartGameRequest) returns (ActionResponse);
  rpc KickPlayer(KickRequest) returns (ActionResponse);

  // Gameplay
  rpc SendPublicHint(HintRequest) returns (ActionResponse);
  rpc GuessObject(GuessRequest) returns (ActionResponse);
  rpc ValidateGuess(ValidateRequest) returns (ActionResponse);
  rpc AdvanceTurn(PlayerRequest) returns (ActionResponse);

  // Trocas privadas
  rpc RequestPrivateExchange(ExchangeRequest) returns (ActionResponse);
  rpc RespondToExchange(ExchangeResponseRequest) returns (ActionResponse);

  // Espionagem
  rpc SpyOnExchange(SpyRequest) returns (ActionResponse);

  // Votação
  rpc VoteContinue(VoteRequest) returns (ActionResponse);

  // Chat (persistido no MongoDB)
  rpc SendChatMessage(ChatMessageRequest) returns (ActionResponse);
  rpc GetChatHistory(ChatHistoryRequest) returns (ChatHistoryResponse);

  // Streaming server-side
  rpc StreamEvents(StreamRequest) returns (stream GameEvent);
}
```

São **15 RPCs**, sendo 14 **unários** (request/response) e 1 **server-streaming** (`StreamEvents`).

## Padrão de resposta

A maioria das ações retorna `ActionResponse`, que carrega:

```protobuf
message ActionResponse {
  bool   success = 1;   // operação aceita pelo servidor?
  string message = 2;   // mensagem amigável para exibir ao usuário
  string data    = 3;   // payload JSON serializado, opcional
}
```

O campo `data` é uma string JSON em vez de um sub-message tipado. Isso é uma decisão de simplicidade: respostas têm formatos heterogêneos (`{"exchange_id": "..."}`, `{"discovered": false, "hint1": "...", "hint2": "..."}`, `{"guess_id": "..."}`). Tipar cada uma engessaria o proto sem ganho real, já que o consumidor (gateway) faz `json.loads()` e empacota num dict para o JSON do REST.

`GetGameState` foge ao padrão e retorna `GameStateResponse` com `state_json` — o snapshot do estado também é JSON, derivado de `GameState.to_dict(viewer_id=...)`.

## RPCs unários — detalhe

### Lobby

| RPC | Request | Response | O que faz |
|---|---|---|---|
| `JoinGame` | `JoinRequest{player_name, game_id}` | `JoinResponse{success, player_id, game_id, message}` | Cria sala se `game_id` vazio ou inexistente; senão entra. Emite evento `player_joined`. |
| `GetGameState` | `PlayerRequest{player_id, game_id}` | `GameStateResponse{success, state_json, message}` | Retorna o snapshot atual do jogo, com segredos filtrados conforme o `viewer_id`. |
| `StartGame` | `StartGameRequest{player_id, game_id, max_turns}` | `ActionResponse` | Apenas o host pode chamar. Sorteia objetos, vai para status `playing`, emite `game_started` para cada jogador (com seu objeto secreto). |
| `KickPlayer` | `KickRequest{host_id, game_id, target_id}` | `ActionResponse` | Host remove um jogador. Emite `player_kicked`. |

### Gameplay

| RPC | Request | Response | O que faz |
|---|---|---|---|
| `SendPublicHint` | `HintRequest{player_id, game_id, hint}` | `ActionResponse` | Adiciona dica pública (1 palavra) ao jogador. Emite `hint_sent`. Limita a 1 por turno. |
| `GuessObject` | `GuessRequest{guesser_id, game_id, target_player_id, guess}` | `ActionResponse{data: {guess_id}}` | Cria `GuessAttempt`. Emite `guess_pending` (público) e `validate_request` (privado para o dono do objeto). |
| `ValidateGuess` | `ValidateRequest{validator_id, game_id, guess_id, is_correct}` | `ActionResponse` | Apenas o dono do objeto valida. Aplica pontos, emite `guess_result` e potencialmente `all_guessed`. |
| `AdvanceTurn` | `PlayerRequest{player_id, game_id}` | `ActionResponse` | Apenas host. Incrementa o turno. Se passar de `max_turns`, calcula pontos do dono e entra em `voting`. |

### Trocas privadas

| RPC | Request | Response | O que faz |
|---|---|---|---|
| `RequestPrivateExchange` | `ExchangeRequest{from_id, to_id, game_id, hint}` | `ActionResponse{data: {exchange_id}}` | Cria troca pendente. Emite `exchange_request` (privado para `to_id`) e `exchange_announced` (público). |
| `RespondToExchange` | `ExchangeResponseRequest{responder_id, game_id, exchange_id, accept, hint}` | `ActionResponse` | Aceita (com dica de retorno) ou recusa. Marca `private_exchange_used` em ambos. Emite `exchange_accepted` (privado para cada participante, com a dica do outro) e `exchange_completed` (público). |

### Espionagem

| RPC | Request | Response | O que faz |
|---|---|---|---|
| `SpyOnExchange` | `SpyRequest{spy_id, game_id, exchange_id}` | `ActionResponse{data: {discovered, hint1, hint2}}` | Sorteia 40% chance de ser pego. Se pego: `−5` no espião, `spy_caught` para participantes, `you_were_caught_spying` privado para o espião, `spy_attempt {discovered:true}` público. Se não pego: dicas reveladas só na resposta REST + `spy_attempt {discovered:false}` público. |

### Votação

| RPC | Request | Response | O que faz |
|---|---|---|---|
| `VoteContinue` | `VoteRequest{player_id, game_id, continue_game}` | `ActionResponse` | Registra voto. Emite `vote_update`. Quando todos votam, resolve: ou `new_round` ou `game_finished` (apaga chat). |

### Chat

| RPC | Request | Response | O que faz |
|---|---|---|---|
| `SendChatMessage` | `ChatMessageRequest{player_id, player_name, game_id, message}` | `ActionResponse` | Persiste no Mongo e faz broadcast `chat_message`. |
| `GetChatHistory` | `ChatHistoryRequest{game_id, limit}` | `ChatHistoryResponse{messages: ChatMessage[]}` | Histórico ordenado por `timestamp`. |

## Streaming — `StreamEvents`

```protobuf
rpc StreamEvents(StreamRequest) returns (stream GameEvent);

message StreamRequest {
  string player_id = 1;
  string game_id   = 2;
}

message GameEvent {
  string event_type        = 1;  // "guess_result", "exchange_accepted", ...
  string data              = 2;  // payload JSON
  int64  timestamp         = 3;  // ms desde epoch
  string target_player_id  = 4;  // "" = público; senão = privado para esse player
}
```

Implementado em [`game_server.py:201-251`](../back-end/game_server.py). O fluxo:

```
1. Cliente chama StreamEvents → servidor cria asyncio.Queue para (game_id, player_id)
2. Envia GameEvent("initial_state", ...) com snapshot e objeto secreto
3. Loop:
     - context.cancelled()? → encerra
     - await queue.get() com timeout 25s
     - se chega evento → yield GameEvent(...)
     - se timeout → yield GameEvent("heartbeat", "{}")
4. Quando o stream encerra (cliente desconectou) → unsubscribe da queue
```

A cada operação que altera estado, o serviço relevante chama `EventBus.broadcast(...)`, que enfileira o evento em todas as filas do jogo (ou só na do `target`, se privado). Cada `StreamEvents` rodando consome sua própria queue.

### Eventos privados

Quando um RPC chama `_bus.broadcast(..., target=player_id)`, o evento só vai para a queue daquele jogador. Mas, no padrão atual, **o filtro é redundante no cliente também**: o gateway passa o `target_player_id` no JSON do WebSocket, e o `app.js` ignora eventos cujo target não bate com o próprio playerId. Isso protege contra mudanças futuras no roteamento.

## Mensagens auxiliares

```protobuf
message PlayerRequest    { string player_id; string game_id; }
message StartGameRequest { string player_id; string game_id; int32 max_turns; }
message KickRequest      { string host_id;   string game_id; string target_id; }
message HintRequest      { string player_id; string game_id; string hint; }
message GuessRequest     { string guesser_id; string game_id; string target_player_id; string guess; }
message ValidateRequest  { string validator_id; string game_id; string guess_id; bool is_correct; }
message ExchangeRequest  { string from_id; string to_id; string game_id; string hint; }
message ExchangeResponseRequest { string responder_id; string game_id; string exchange_id; bool accept; string hint; }
message SpyRequest       { string spy_id; string game_id; string exchange_id; }
message VoteRequest      { string player_id; string game_id; bool continue_game; }
```

## Por que gRPC e não outro RPC

- **Tipagem forte** com geração automática de stubs em ambos os lados (o gateway é cliente, o GameServer é servidor).
- **Streaming server-side nativo** — fundamental para o `StreamEvents`. Em REST puro precisaria de SSE ou polling; com gRPC sai de graça.
- **Performance** — serialização binária Protobuf, multiplexação HTTP/2.
- **Boundary explícito** entre transporte (gateway) e domínio (game server). Mudar o transporte para outra coisa (CLI, app nativo) não toca a lógica.

## Padrão de tratamento de erros

Todos os RPCs unários **retornam erros como dado** via `ActionResponse{success: false, message: "..."}`, em vez de levantar `grpc.StatusCode`. Razão: o gateway repassa essa estrutura tal e qual no JSON do REST, e o front exibe a mensagem como toast. Erros gRPC genuínos (timeout, conexão caiu) ainda viram exceções e são tratados em try/except no gateway.
