# 1. Arquitetura geral

## Componentes

O sistema é composto por **3 containers Docker** orquestrados pelo `docker-compose.yml`. Dentro do container do backend, **dois processos Python** rodam em paralelo: o servidor gRPC (lógica do jogo) e o gateway FastAPI (tradução para o protocolo do navegador).

```
┌─────────────────────────────────────────────────────────────────┐
│  Container: guessgame-frontend  (Nginx)                         │
│                                                                 │
│   • serve HTML/CSS/JS estático em /                             │
│   • proxy reverso /api/* e /ws/* → backend:8000                 │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  Container: guessgame-backend                                   │
│                                                                 │
│   ┌──────────────────────┐         ┌──────────────────────┐     │
│   │ FastAPI Gateway      │  gRPC   │ gRPC GameServer      │     │
│   │ porta 8000           │────────▶│ porta 50051          │     │
│   │ (cliente gRPC)       │  cli/   │ (event_bus em RAM)   │     │
│   │                      │  stream │                      │     │
│   └──────────────────────┘         └──────────┬───────────┘     │
│                                               │                 │
└───────────────────────────────────────────────┼─────────────────┘
                                                │ Motor (async)
                                                ▼
┌─────────────────────────────────────────────────────────────────┐
│  Container: guessgame-mongodb                                   │
│                                                                 │
│   • banco "guessgame", coleção "chat"                           │
│   • índice composto (game_id, timestamp)                        │
└─────────────────────────────────────────────────────────────────┘
```

## Camadas dentro do backend

O servidor gRPC aplica uma divisão clara de responsabilidades:

```
game_server.py          ← traduz mensagens proto → chamadas Python
       │
       ▼
game_manager.py         ← agrega services e expõe interface única
       │
       ├──▶ services/lobby.py       (criar/entrar/iniciar/kick)
       ├──▶ services/gameplay.py    (dicas, palpites, validação, turnos)
       ├──▶ services/exchange.py    (trocas privadas)
       ├──▶ services/spy.py         (espionagem)
       └──▶ services/voting.py      (votação e fim de jogo)
                  │
                  ▼
          core/event_bus.py         (pub/sub em memória)
          core/scoring.py           (sorteio de objetos, pontos)
                  │
                  ▼
          domain/models.py          (GameState, Player, etc.)
          domain/constants.py       (regras: pontos, objetos, status)
```

Cada serviço herda de [`BaseService`](../back-end/services/base.py), que fornece três dependências compartilhadas:

- `_games: Dict[str, GameState]` — todos os jogos ativos.
- `_locks: Dict[str, asyncio.Lock]` — um lock por `game_id`, garantindo serialização de operações que mutam o mesmo jogo.
- `_bus: EventBus` — fila pub/sub usada para enviar eventos a clientes conectados.

## Os três protocolos de comunicação

| Trecho da pilha | Protocolo | Por quê |
|---|---|---|
| Browser ↔ Nginx ↔ Gateway | **HTTP REST** | Ações pontuais request/response (entrar, votar, enviar dica). |
| Browser ↔ Nginx ↔ Gateway | **WebSocket** | Stream contínuo de eventos do jogo até o navegador (alguém entrou, alguém adivinhou, etc.). |
| Gateway ↔ GameServer | **gRPC** | Contrato fortemente tipado por `.proto`, serialização binária eficiente, suporte nativo a streaming server-side. |

O nginx faz proxy:

- `GET /` e estáticos → arquivos do `front-end/static/`
- `* /api/*` → `backend:8000` (HTTP)
- `* /ws/*` → `backend:8000` (HTTP/1.1 com upgrade para WebSocket)

## Fluxo de uma ação típica

Vamos seguir o caminho de uma "tentativa de adivinhação":

```
1. Browser    : POST /api/guess { guesser_id, game_id, target_player_id, guess }
                       │
                       ▼
2. Nginx      : proxy_pass http://backend:8000
                       │
                       ▼
3. Gateway    : recebe HTTP, monta GuessRequest (proto), chama GuessObject() via gRPC
                       │
                       ▼
4. GameServer : delega a game_manager.guess_object() → GameplayService.guess_object()
                       │
                       ├─ valida turno, jogador, alvo
                       ├─ cria GuessAttempt em GameState
                       ├─ broadcast "guess_pending" (público) via EventBus
                       └─ broadcast "validate_request" (privado para o dono) via EventBus
                       │
                       ▼
5. EventBus   : enfileira o evento em todas as queues subscritas (uma por player)
                       │
                       ▼
6. StreamEvents (gRPC server-streaming): consome cada queue, emite GameEvent
                       │
                       ▼
7. Gateway    : relay do GameEvent para o cliente via WebSocket
                       │
                       ▼
8. Browser    : handleEvent("guess_pending", data) → toast + atualiza feed
```

Operações de mutação rodam **dentro do lock por jogo** (`async with self._get_lock(game_id)`), evitando condições de corrida quando dois jogadores mexem no mesmo estado simultaneamente.

## Decisões de design

### Por que separar gateway e gRPC server?

- O navegador não fala gRPC nativamente sem grpc-web (que exige proxy adicional). Manter o navegador no terreno HTTP/WS é simples e familiar.
- O gRPC server fica isolado da camada de transporte web, focado só em lógica de jogo.
- Permite trocar o front por outro cliente (CLI, mobile nativo) reaproveitando o mesmo gRPC.

### Por que estado em memória?

- Latência mínima nas operações.
- A natureza de "sessão de jogo" é efêmera: ninguém espera retomar uma partida depois de um restart.
- Simplicidade — não há ORM, migrations ou contention de locking distribuído.

O preço: o backend não escala horizontalmente. Para múltiplas instâncias seria necessário um broker (Redis pub/sub, NATS) e um store compartilhado. Para o escopo (LAN, dezenas de jogadores), uma instância é suficiente.

### Por que MongoDB só para chat?

- O chat é o único dado que faz sentido **persistir durante** a sessão (alguém entrar tarde e ver o que foi dito). O resto vive na memória dos clientes (snapshot inicial via `GetGameState` + eventos).
- Mongo é simples para documentos não estruturados como mensagens com timestamp.
- O chat é apagado ao final do jogo — ver [05-persistencia.md](05-persistencia.md).

### Concorrência

- Tudo no backend é `async` (asyncio).
- Cada partida tem seu próprio `asyncio.Lock`, então ações em jogos diferentes nunca disputam.
- O EventBus usa filas com tamanho máximo (`asyncio.Queue(maxsize=200)`); se um cliente lento entupir a fila, eventos novos são descartados em vez de bloquear o broadcast.
- O WebSocket tem heartbeat de 25s para detectar conexões mortas atrás de proxies.

## Resumo das responsabilidades

| Arquivo | Responsabilidade |
|---|---|
| `front-end/static/` | UI: telas, render, ações HTTP, consumo do WebSocket |
| `front-end/nginx.conf` | Roteamento e proxy reverso |
| `back-end/gateway.py` | HTTP REST + WebSocket → cliente gRPC |
| `back-end/game_server.py` | Implementação do `GameService` (gRPC) |
| `back-end/game_manager.py` | Singleton: agrega services e estado global |
| `back-end/services/*.py` | Lógica de cada feature (lobby, gameplay, exchange, spy, voting) |
| `back-end/core/event_bus.py` | Broadcast/pub-sub de eventos por jogo |
| `back-end/core/scoring.py` | Sorteio de objetos e cálculo de pontos |
| `back-end/domain/models.py` | Estruturas de dados (`GameState`, `Player`, etc.) |
| `back-end/domain/constants.py` | Regras hard-coded: pontos, status, lista de objetos |
| `back-end/database.py` | MongoDB (chat) |
