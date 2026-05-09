# 5. Persistência e estado

## Resumo de uma linha

> Tudo vive em memória; só o **chat** é persistido em MongoDB; o chat é apagado quando o jogo termina ou quando uma sala nova reusa um `game_id` antigo.

## O que vive onde

| Dado | Onde | Persiste entre restart? |
|---|---|---|
| `GameState` (jogadores, objetos, turnos, dicas, trocas, votos) | RAM do processo gRPC server (`game_manager._games`) | ❌ |
| `EventBus` (filas pub/sub por player) | RAM do mesmo processo (`event_bus._queues`) | ❌ |
| Histórico de chat por sala | MongoDB, coleção `chat` | ✅ enquanto o volume Mongo viver, **mas** apagado por evento de jogo |
| Tokens / sessões | não existem | — |

## Estado em memória

Implementado em [`game_manager.py`](../back-end/game_manager.py):

```python
class GameManager:
    def __init__(self):
        self._games: Dict[str, GameState] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self._bus  = EventBus()
```

- `_games` — dicionário `game_id → GameState`. Toda mutação de jogo passa por aqui.
- `_locks` — um `asyncio.Lock` por jogo. Toda action acessa via `async with self._get_lock(game_id):`.
- `_bus` — único `EventBus` para todos os jogos; fila por `(game_id, player_id)`.

### Por que tudo na RAM?

- **Latência**: nenhum I/O em ações de jogo (só na hora do chat).
- **Simplicidade**: zero ORM, zero migrations, zero schema.
- **Ciclo de vida natural**: a sessão de um jogo é efêmera — ninguém espera retomar uma partida no dia seguinte.

### Implicações

- Restart do backend → **todos os jogos ativos somem**. Os clientes vão reconectar (auto-reconnect do WebSocket em `app.js`) e cair em "Jogo não encontrado" no próximo `refreshState`.
- Não há recuperação. Para um exercício acadêmico em LAN é aceitável; em produção exigiria persistir o `GameState` (Postgres com JSONB? Redis?).
- Não escala horizontalmente — múltiplas instâncias do backend não compartilhariam estado. Seria necessário broker (Redis pub/sub, NATS) + store comum.

## EventBus

[`core/event_bus.py`](../back-end/core/event_bus.py):

```python
class EventBus:
    def __init__(self):
        # game_id → { player_id → asyncio.Queue(maxsize=200) }
        self._queues: Dict[str, Dict[str, asyncio.Queue]] = {}

    async def subscribe(self, game_id, player_id) -> Queue
    def     unsubscribe(self, game_id, player_id)
    async def broadcast(self, game_id, event_type, data, target=None)
```

- O `subscribe` é chamado quando o WebSocket abre — em `game_server.StreamEvents`.
- O `unsubscribe` no `finally` do stream, sempre.
- `broadcast(target=None)` enfileira em todas as filas do jogo. `broadcast(target=pid)` enfileira só naquele.
- `maxsize=200` por fila — se um cliente lento entupir a fila, eventos novos são silenciosamente descartados (`QueueFull` em `put_nowait` → `pass`). Isso preserva responsividade dos outros jogadores.

## MongoDB — o que é persistido

Há **uma única coleção**: `guessgame.chat`. Documentos têm o formato:

```json
{
  "game_id":     "ABC123",
  "player_id":   "78f49c97",
  "player_name": "Alice",
  "message":     "boa sorte pessoal",
  "timestamp":   1714679823000
}
```

Índice composto criado em `db.connect()`:

```python
await self._db.chat.create_index([("game_id", 1), ("timestamp", -1)])
```

Isso torna `find({"game_id": ...}).sort("timestamp", 1).limit(50)` eficiente.

## Lifecycle do chat

A camada de persistência está em [`back-end/database.py`](../back-end/database.py) com 3 métodos relevantes:

```python
async def save_chat_message(game_id, player_id, player_name, message)
async def get_chat_history(game_id, limit=50)  -> List[Dict]
async def delete_chat(game_id)                 -> int  # quantos foram deletados
```

### Onde o chat é gravado

`SendChatMessage` em [`game_server.py`](../back-end/game_server.py):

```python
await db.save_chat_message(...)
await game_manager._broadcast(request.game_id, "chat_message", {...})
```

A gravação acontece **antes** do broadcast. Se o save falhar, o broadcast não vai (a função vê a exceção e retorna `success=False`).

### Onde o chat é apagado

Há **dois pontos** de exclusão automática:

#### 1. Fim do jogo — [`services/voting.py:_resolve_vote`](../back-end/services/voting.py)

```python
else:  # encerrar venceu (ou empate)
    game.status = GameStatus.FINISHED
    ...
    await self._bus.broadcast(game_id, "game_finished", {...})
    await db.delete_chat(game_id)
```

Quando a votação resolve para "encerrar", o chat é varrido imediatamente.

#### 2. Criação de sala nova — [`services/lobby.py:create_or_join_game`](../back-end/services/lobby.py)

```python
async with self._get_lock(game_id):
    creating = game_id not in self._games
    if creating:
        self._games[game_id] = GameState(game_id=game_id)
        await db.delete_chat(game_id)   # ← limpa lixo de sessão antiga
```

Por quê? Se o backend foi reiniciado, o `_games` está vazio mas o Mongo ainda guarda mensagens da sessão antiga. Ao criar uma sala **nova** com um `game_id` qualquer, garante-se que ela começa zerada.

### Quando o chat NÃO é apagado

- Ao mudar de rodada (`new_round`) — chat de rodadas anteriores na mesma partida persiste, intencional.
- Ao um jogador sair (kick ou desconexão) — só ele perde acesso ao stream; o chat continua.

## Volume Docker

Em `docker-compose.yml`:

```yaml
mongodb:
  volumes:
    - mongo_data:/data/db
volumes:
  mongo_data:
```

- `docker compose down` mantém o volume e, portanto, o conteúdo do banco.
- `docker compose down -v` apaga o volume também — útil para "começar do zero".

## Por que NÃO mongo em memória (tmpfs)?

Foi considerado e rejeitado:

- **Não resolve o problema real**: enquanto o container do Mongo estiver de pé entre sessões, RAM ou SSD se comportam igual — o chat antigo aparece.
- **Inverte a função do banco**: o ponto de ter Mongo era ter histórico durante a sessão (jogador entra tarde e vê o que aconteceu). RAM volátil mata isso.
- **Não cobre reuso de game_id**: mesmo com Mongo em RAM, criar uma sala com mesmo ID de uma partida não terminada cleanly traria lixo.

A solução correta é **apagar por evento de jogo** — limpa o que precisa, quando precisa.

## Snapshot de estado para clientes

Quando um WebSocket abre (`StreamEvents`), o servidor envia primeiro um `initial_state` derivado de:

```python
state = game.to_dict(viewer_id=player_id)
```

[`GameState.to_dict`](../back-end/domain/models.py) é o ponto **único** que decide o que cada jogador vê:

- Para **outros** jogadores: nome do objeto vira `"???"` e emoji vira `"❓"` se ainda não foi adivinhado.
- Para **você mesmo** (`viewer_id == pid`): vê seu próprio objeto.
- **Trocas** com `status="pending"` só aparecem para `from_id` e `to_id`.
- **Trocas aceitas**: dicas só são reveladas para participantes ou para quem espionou com sucesso (`viewer_id in ex.spies_succeeded`).

Isso garante que segredo nunca trafega indevidamente — mesmo via REST refresh, o filtro é o mesmo.

## Resumo do contrato de durabilidade

| Operação | O que sobrevive a... |
|---|---|
| Restart do backend | apenas o chat (no Mongo). Jogos somem. |
| Restart do Mongo | depende do volume — `mongo_data` por padrão preserva. |
| `docker compose down` | volume é mantido (mas chat só sobrevive até o próximo `delete_chat` automático). |
| `docker compose down -v` | nada sobrevive. |
| `game_finished` | chat daquela sala é deletado. |
| Nova sala com mesmo ID | chat antigo do mesmo ID é deletado preventivamente. |
