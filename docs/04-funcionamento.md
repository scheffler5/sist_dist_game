# 4. Funcionamento do jogo

Este documento descreve as **regras** e a **máquina de estados** que governam uma partida, junto com a tabela de pontuação detalhada.

## Modelo de dados

Definido em [`back-end/domain/models.py`](../back-end/domain/models.py):

```python
@dataclass
class Player:
    id: str
    name: str
    object_name: str = ""
    object_emoji: str = ""
    public_hints: List[str] = []
    object_guessed: bool = False
    guessed_by: List[str] = []
    private_exchange_used: bool = False
    score: int = 0
    hint_sent_this_turn: bool = False
    is_host: bool = False
    connected: bool = True

@dataclass
class GameState:
    game_id: str
    status: str = "waiting"     # waiting | playing | voting | finished
    players: Dict[str, Player]
    current_turn: int = 0
    max_turns: int = 5
    current_round: int = 1
    guess_attempts: Dict[str, GuessAttempt]
    private_exchanges: Dict[str, PrivateExchange]
    votes_continue: Set[str]
    votes_end: Set[str]
    used_objects: List[str]      # já usados nesta partida; evita repetir entre rodadas

@dataclass
class GuessAttempt:
    id: str
    guesser_id: str
    guesser_name: str
    target_player_id: str
    guess: str
    status: str = "pending"      # pending | correct | incorrect
    timestamp: float
    first_correct: bool = False

@dataclass
class PrivateExchange:
    id: str
    from_id, from_name: str
    to_id, to_name: str
    from_hint: str
    to_hint: str = ""
    status: str = "pending"       # pending | accepted | rejected
    round: int
    spies_caught: List[str]
    spies_succeeded: List[str]
```

## Máquina de estados de uma sala

```
                ┌──────────────────────────┐
                │       waiting            │
                │  (lobby, host configura) │
                └────────────┬─────────────┘
                             │ host chama StartGame
                             │ assign_objects() sorteia objetos
                             ▼
                ┌──────────────────────────┐
                │       playing            │
                │  turnos 1..max_turns     │
                │  ações habilitadas:      │
                │   - SendPublicHint       │
                │   - GuessObject          │
                │   - RequestPrivateExch.. │
                │   - SpyOnExchange        │
                │   - AdvanceTurn (host)   │
                └────────────┬─────────────┘
                             │ host chama AdvanceTurn no último turno
                             │ calculate_owner_scores() aplica pontos do dono
                             ▼
                ┌──────────────────────────┐
                │       voting             │
                │  cada player vota:       │
                │   continuar | encerrar   │
                └─────┬──────────────┬─────┘
                      │              │
        votos_cont >  │              │  votos_cont <= votos_end
        votos_end     │              │
                      ▼              ▼
              ┌───────────┐    ┌──────────────┐
              │  playing  │    │   finished   │
              │ (rodada+1 │    │ (chat apaga, │
              │  novos    │    │  ranking     │
              │  objetos) │    │  final)      │
              └───────────┘    └──────────────┘
```

Os valores de `status` correspondem a [`domain/constants.py:GameStatus`](../back-end/domain/constants.py).

## Sorteio de objetos

[`core/scoring.py:assign_objects`](../back-end/core/scoring.py):

- Há 24 objetos em [`OBJECTS`](../back-end/domain/constants.py) (bicicleta, piano, telescópio, ...).
- A cada início de partida ou rodada, escolhe `len(players)` objetos **únicos** que ainda não foram usados naquela partida (`used_objects`).
- Se acabarem objetos disponíveis (rodadas demais), o conjunto é resetado e tudo volta a ser candidato.
- Para cada jogador, atribui o objeto e **reseta** flags por rodada: `public_hints`, `object_guessed`, `guessed_by`, `private_exchange_used`, `hint_sent_this_turn`.

## Mecânica de turnos

Um turno é a unidade mínima de progresso. Em cada turno:

- Cada jogador pode enviar **uma única dica pública** (`hint_sent_this_turn`). Tentar enviar duas é rejeitado pelo `GameplayService.send_public_hint`.
- Palpites, trocas e espionagem **não são limitados pelo turno** — só pelas regras próprias (1 troca por rodada, 1 palpite por alvo, etc.).
- O **host** avança o turno chamando `AdvanceTurn`. Não há avanço automático.
- Ao avançar, todas as flags `hint_sent_this_turn` são resetadas.

Quando `current_turn >= max_turns` e o host chama `AdvanceTurn`, em vez de incrementar o turno, o sistema:

1. Roda `calculate_owner_scores(game)` — atribui pontos retroativos aos donos dos objetos.
2. Muda status para `voting`.
3. Emite `voting_started` com o placar atual.

## Mecânica de palpite (`GuessObject`)

```
Alice tenta adivinhar o objeto de Bob = "piano"
  │
  ▼
1. GameplayService.guess_object valida:
     - jogador, alvo, não é si mesmo
     - alvo ainda não foi adivinhado
     - Alice ainda não tentou esse alvo (1 tentativa por par)
  │
  ▼
2. cria GuessAttempt(status="pending")
  │
  ▼
3. broadcast "guess_pending"  → todos veem "Alice tentou..."
   broadcast "validate_request" → APENAS Bob: "Alice diz 'piano'. Aceita?"
  │
  ▼
4. Bob (dono) escolhe Sim ou Não em ValidateGuess
  │
  ▼
5. Se Sim:
     - first_correct = !target.object_guessed
     - alvo.guessed_by.append(Alice.id)
     - Alice.score += 15 (first) ou +10 (subsequente)
     - se first_correct: target.object_guessed = True
     - broadcast "guess_result" {correct:true, ...}
     - se todos os outros adivinharam → broadcast "all_guessed"
   Se Não:
     - status = incorrect
     - broadcast "guess_result" {correct:false}
```

A **validação manual** é proposital: o sistema não tenta normalizar palavras, então sinônimos ou plurais (`carro` vs `automóvel`, `piano` vs `pianos`) ficam à decisão do dono.

Restrições:
- Não pode adivinhar o próprio objeto.
- Não pode adivinhar um objeto já adivinhado (`object_guessed=True`).
- Cada par (guesser, target) só faz **uma tentativa** durante toda a rodada — bloqueio em `GameplayService.guess_object`.

## Mecânica de troca privada

```
1. Alice envia ExchangeRequest(to=Bob, hint="redondo")
   ├─ valida: Alice ainda não usou troca, não há pendente Alice↔Bob
   ├─ cria PrivateExchange(status="pending")
   ├─ broadcast "exchange_request" → APENAS Bob (com nome de Alice)
   └─ broadcast "exchange_announced" → todos (sem conteúdo)
        │
        ▼
2. Bob responde com RespondToExchange:
   - accept=False:
       status="rejected"
       broadcast "exchange_rejected" → todos
   - accept=True (com hint="grande"):
       status="accepted"
       to_hint = "grande"
       Alice.private_exchange_used = True
       Bob.private_exchange_used = True
       broadcast "exchange_accepted" privado para Alice (recebe "grande")
       broadcast "exchange_accepted" privado para Bob (recebe "redondo")
       broadcast "exchange_completed" → todos (sem conteúdo)
```

Restrições:
- Cada jogador só faz/aceita **uma troca por rodada** (`private_exchange_used`).
- Não pode haver duas trocas pendentes entre o mesmo par.
- Não pode trocar consigo mesmo.
- Dicas trocadas só são reveladas para os participantes (filtro em `GameState.to_dict`) — mas trocas concluídas **são visíveis** para todos como entradas com status, abrindo espaço para espionagem.

## Mecânica de espionagem

Implementada em [`services/spy.py`](../back-end/services/spy.py). Aplicável apenas a trocas com `status="accepted"`.

```
Carol clica em "Espionar" na troca Alice↔Bob (status accepted)
  │
  ▼
SpyOnExchange:
  ├─ valida: Carol não é Alice nem Bob
  ├─ valida: Carol não tentou espionar essa troca antes
  ├─ random.random() < 0.4 ?
  │    SIM (pego):
  │      exchange.spies_caught.append(Carol)
  │      Carol.score += -5
  │      broadcast "spy_caught" privado para Alice e Bob (cada)
  │      broadcast "you_were_caught_spying" privado para Carol
  │      broadcast "spy_attempt" público {discovered: true, spy_name: "Carol", target1, target2}
  │      retorna {discovered: true}
  │    NÃO (sucesso):
  │      exchange.spies_succeeded.append(Carol)
  │      broadcast "spy_attempt" público {discovered: false}  (anônimo!)
  │      retorna {discovered: false, hint1: "redondo", hint2: "grande"}
```

Detalhes importantes:
- A constante de chance vive em [`SPY_CATCH_CHANCE = 0.4`](../back-end/domain/constants.py).
- Quando o espião **passa**, o evento público é **anônimo** (`"Alguém tentou espionar"`) — a identidade só é revelada se for pego.
- As dicas voltam **apenas como resposta REST direta**, não como evento broadcast — só o espião as vê.
- O `GameState.to_dict` faz o `viewer_id in spies_succeeded` para também revelar dicas em refreshes futuros, marcando o exchange com `spied: true`.

## Votação e fim de rodada

Implementada em [`services/voting.py`](../back-end/services/voting.py).

```
voting_started → cada jogador chama VoteContinue(continue_game=true|false)
  │
  ├─ atualiza votes_continue / votes_end (Sets)
  ├─ broadcast "vote_update" {votes_continue, votes_end, total_players}
  │
  └─ se todos votaram (votes_in == n_players) → _resolve_vote
       │
       ├─ continuar > encerrar:
       │     current_round += 1
       │     current_turn = 1
       │     status = playing
       │     limpa: votes, guess_attempts, private_exchanges
       │     assign_objects (novos objetos, mesma partida)
       │     broadcast "new_round" privado para cada player (com seu objeto)
       │
       └─ caso contrário (encerrar venceu ou empate):
             status = finished
             scores ordenados em ranking
             broadcast "game_finished" {final_scores}
             db.delete_chat(game_id)
```

Empate vai para "encerrar" — comportamento implícito do `>` em `len(votes_continue) > len(votes_end)`.

## Pontuação completa

Tudo em [`domain/constants.py`](../back-end/domain/constants.py). Aplicado em duas frentes:

### Pontos do adivinhador (aplicados imediatamente)

| Constante | Valor | Quando |
|---|---|---|
| `FIRST_GUESS_POINTS` | `+15` | Primeiro a acertar o objeto de alguém |
| `OTHER_GUESS_POINTS` | `+10` | Acertou (não foi o primeiro) |
| `SOLO_BONUS_POINTS` | `+5` | Foi o **único** a adivinhar um determinado objeto (apurado no fim da rodada) |

### Pontos do dono do objeto (aplicados ao fim da rodada, em `calculate_owner_scores`)

| Cenário | Constante | Valor |
|---|---|---|
| Ninguém adivinhou | — | `0` (status quo) |
| **Só 1** adivinhou | `OWNER_SOLO_POINTS` | `+20` |
| **Vários** adivinharam (não todos) | `OWNER_MULTI_POINTS` | `+10` |
| **Todos** os outros adivinharam | `OWNER_ALL_PENALTY` | `−5` |

### Penalidade da espionagem

| Constante | Valor | Quando |
|---|---|---|
| `SPY_CAUGHT_PENALTY` | `−5` | Espião foi pego |

A pontuação **acumula entre rodadas** até o jogo encerrar. O ranking final é o vetor de `score` ordenado decrescente.

### Lógica do bônus solo

Em `calculate_owner_scores` (após aplicar pontos do dono):

```python
for guesser:
    for target:
        if target.id != guesser.id and len(target.guessed_by) == 1 and target.guessed_by[0] == guesser.id:
            guesser.score += SOLO_BONUS_POINTS
```

Em palavras: se você foi o **único** a adivinhar o objeto de alguém, ganha +5 extras.

## Lifecycle resumido em uma linha

```
join → start → (turnos: hint, guess, exchange, spy) ×N → advance final →
       voting → resolve → [new_round | finished]
```

A cada `start` e `new_round`, [`assign_objects`](../back-end/core/scoring.py) sorteia objetos novos.
A cada `finished`, o chat é apagado (ver [05-persistencia.md](05-persistencia.md)).
