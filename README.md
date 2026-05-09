# AdivinhAí

Jogo multiplayer de adivinhação em tempo real. Cada jogador recebe um objeto secreto e tenta adivinhar o objeto dos outros a partir das dicas que eles publicam, das trocas privadas que negociam e da espionagem que arrisca fazer.

A aplicação foi construída como um exercício de sistemas distribuídos, integrando três protocolos de comunicação (gRPC, HTTP REST, WebSocket) e três serviços containerizados (gateway, gRPC server, MongoDB).

> Documentação técnica detalhada por etapas: [`docs/`](docs/README.md) — arquitetura, RPC, gateway, funcionamento do jogo, persistência, frontend, deploy.

---

## Visão geral

- **Tipo**: jogo de adivinhação por turnos, multiplayer (2+ jogadores), em tempo real.
- **Frontend**: HTML/CSS/JS estático servido por Nginx, sem framework (Tailwind via CDN).
- **Backend**: dois processos Python rodando no mesmo container — um servidor gRPC (lógica do jogo) e um gateway FastAPI (HTTP/WebSocket para o navegador).
- **Persistência**: MongoDB para histórico de chat. Estado do jogo vive em memória.
- **Orquestração**: Docker Compose com três serviços (`mongodb`, `backend`, `frontend`).

---

## Arquitetura

```
            ┌──────────────┐
            │   Browser    │
            └──────┬───────┘
                   │ HTTP + WebSocket
                   ▼
       ┌──────────────────────┐
       │ Nginx (frontend:80)  │  serve estáticos + proxy /api e /ws
       └──────────┬───────────┘
                  │
                  ▼
       ┌──────────────────────┐
       │ FastAPI Gateway      │  traduz HTTP/WS → gRPC
       │ (backend:8000)       │
       └──────────┬───────────┘
                  │ gRPC (unário + streaming)
                  ▼
       ┌──────────────────────┐
       │ gRPC GameServer      │  lógica + estado em memória
       │ (backend:50051)      │
       └──────────┬───────────┘
                  │ Motor (async)
                  ▼
       ┌──────────────────────┐
       │ MongoDB              │  histórico de chat
       │ (mongodb:27017)      │
       └──────────────────────┘
```

### Por que três protocolos

- **HTTP REST** entre o navegador e o gateway: simples, ideal para ações pontuais (entrar, enviar dica, votar).
- **WebSocket** entre o navegador e o gateway: canal contínuo para receber eventos do jogo (alguém entrou, alguém adivinhou, troca aceita, voto, etc.).
- **gRPC** entre o gateway e o servidor do jogo: contrato fortemente tipado por `.proto`, suporte nativo a streaming server-side, separa a lógica do jogo da camada de transporte web.

---

## Stack

| Componente | Tecnologia |
|---|---|
| Servidor de jogo | Python 3.11, `grpcio` |
| Gateway HTTP/WS | FastAPI, Uvicorn |
| Comunicação browser→backend | REST + WebSocket |
| Comunicação gateway→servidor | gRPC (unário e streaming) |
| Persistência de chat | MongoDB 7 + Motor (async) |
| Frontend | HTML, JS puro, Tailwind CDN |
| Servidor estático / proxy | Nginx |
| Orquestração | Docker Compose |

---

## Como rodar

### Pré-requisitos

- Docker
- Docker Compose v2 (já vem com Docker Desktop e versões recentes do Docker Engine)

### Subir a aplicação

```bash
docker compose up -d --build
```

Isso cria três containers:

- `guessgame-mongodb` — banco de dados.
- `guessgame-backend` — gRPC server + gateway HTTP/WS.
- `guessgame-frontend` — Nginx servindo o jogo e fazendo proxy para o backend.

### Acesso local

- **Jogo**: <http://localhost>
- **Health do gateway**: <http://localhost:8000/health>

### Comandos úteis

```bash
docker compose ps                    # ver status dos 3 containers
docker compose logs -f backend       # acompanhar logs do backend
docker compose logs -f frontend      # acompanhar logs do nginx
docker compose restart               # reiniciar sem rebuild
docker compose up -d --build         # rebuild quando mudar código
docker compose down                  # parar e remover containers (mantém o volume do mongo)
docker compose down -v               # parar e apagar inclusive o volume
```

---

## Acesso na rede local (LAN)

Para outros dispositivos da sua rede acessarem o jogo, basta apontar para o IP da máquina que está rodando os containers, na porta `80`:

```
http://<IP-DO-HOST>
```

### WSL2 no Windows

WSL2 não expõe automaticamente portas para a LAN. Abra o **PowerShell como administrador** no Windows e configure o port forwarding (substitua `<IP-WSL>` pelo resultado de `hostname -I` dentro do WSL):

```powershell
netsh interface portproxy add v4tov4 listenport=80   listenaddress=0.0.0.0 connectport=80   connectaddress=<IP-WSL>
netsh interface portproxy add v4tov4 listenport=8000 listenaddress=0.0.0.0 connectport=8000 connectaddress=<IP-WSL>
New-NetFirewallRule -DisplayName "WSL AdivinhAi 80"   -Direction Inbound -LocalPort 80   -Protocol TCP -Action Allow
New-NetFirewallRule -DisplayName "WSL AdivinhAi 8000" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow
```

Para reverter:

```powershell
netsh interface portproxy reset
Remove-NetFirewallRule -DisplayName "WSL AdivinhAi 80"
Remove-NetFirewallRule -DisplayName "WSL AdivinhAi 8000"
```

> O IP do WSL muda a cada restart. Se precisar, descubra o novo com `hostname -I` e refaça o `portproxy`.

---

## Como jogar

### Entrar em uma sala

1. Abra o jogo no navegador.
2. Digite seu nome.
3. **Para criar uma sala nova**: deixe o campo "Código da sala" vazio e clique em *Entrar*. O sistema gera um código aleatório de 6 caracteres (ex: `ABC123`).
4. **Para entrar em uma sala existente**: digite o código que outro jogador compartilhou e clique em *Entrar*.

O primeiro jogador a entrar vira o **host** da sala.

### Iniciar o jogo

- O host configura o número de turnos por rodada (1 a 20, padrão 5) e clica em *Iniciar jogo*.
- São necessários **no mínimo 2 jogadores** para começar.
- Cada jogador recebe um **objeto secreto** (visível apenas para ele) com nome e emoji.

### Estrutura da partida

Uma rodada é dividida em **turnos**. Em cada turno cada jogador pode:

1. **Enviar 1 dica pública** sobre seu próprio objeto (uma palavra). Todos veem.
2. **Tentar adivinhar** o objeto de outro jogador. O dono do objeto valida se está correto.
3. **Solicitar uma troca privada** de dicas com outro jogador (1 vez por rodada).
4. **Espionar** uma troca privada concluída entre outros dois jogadores (com risco de ser descoberto).

O **host** avança o turno quando todos enviaram suas ações. Ao chegar no último turno da rodada, abre-se uma **votação** — todos decidem se querem continuar com uma nova rodada (com novos objetos) ou encerrar.

### Mecânicas em detalhe

#### Dica pública

- Apenas uma palavra, no máximo uma por turno.
- Aparece no card do jogador para todo mundo ver.
- Estratégia: revelar o suficiente para acumular pontos quando outros adivinharem, mas sem entregar de graça.

#### Palpite

- Você escolhe um jogador e digita o que acha que é o objeto dele.
- O dono do objeto recebe a notificação e **valida manualmente** (sim/não). Isso é proposital: às vezes o palpite é uma palavra equivalente (ex: "carro" para "automóvel") e o dono decide.
- Se acertar, ganha pontos (mais se for o **primeiro** a acertar).

#### Troca privada de dicas

- Você manda uma dica privada para outro jogador junto com o pedido.
- Se ele aceita, manda a dica dele de volta. As duas dicas são reveladas só para os dois.
- Cada jogador pode iniciar/aceitar **apenas uma troca por rodada**.
- Trocas concluídas ficam visíveis (sem o conteúdo) para todos — abrindo espaço para espionagem.

#### Espionagem

- Trocas privadas concluídas mostram um botão *Espionar* para quem **não participou**.
- Há **40% de chance** de ser pego. Se for pego, perde **5 pontos** e a tentativa é anunciada.
- Se não for pego, você vê as duas dicas trocadas — dados fortes para acertar o objeto de ambos.
- Cada jogador só pode tentar espionar cada troca **uma vez**.

#### Votação e fim do jogo

- Quando o último turno acaba, o jogo entra em modo de votação.
- Cada jogador vota *Continuar* ou *Encerrar*.
- Se houver mais votos para continuar, uma **nova rodada** começa: novos objetos, dicas e estado de troca/espionagem zerados, pontuação **acumulada**.
- Se houver mais votos para encerrar (ou empate), o jogo finaliza, mostra o ranking final e o histórico de chat daquela sala é apagado.

---

## Pontuação

| Evento | Pontos |
|---|---|
| Adivinhou primeiro o objeto de alguém | **+15** |
| Adivinhou (não foi o primeiro) | **+10** |
| Foi o **único** a adivinhar um objeto (bônus) | **+5** |
| Seu objeto foi adivinhado por **só 1 pessoa** | **+20** (para você) |
| Seu objeto foi adivinhado por **vários** (não todos) | **+10** (para você) |
| Seu objeto foi adivinhado por **todos** | **−5** (para você) |
| Foi pego espiando | **−5** |

Os pontos do dono do objeto (linhas 4–6) são apurados ao **fim de cada rodada**.

A pontuação acumula entre rodadas até o jogo encerrar.

---

## API e protocolos

### Endpoints HTTP REST (gateway)

| Método | Rota | Descrição |
|---|---|---|
| `POST` | `/api/join` | Cria/entra em uma sala |
| `POST` | `/api/start` | Host inicia o jogo |
| `GET`  | `/api/state/{game_id}/{player_id}` | Snapshot do estado |
| `POST` | `/api/hint` | Envia dica pública |
| `POST` | `/api/guess` | Tenta adivinhar |
| `POST` | `/api/validate` | Dono valida o palpite |
| `POST` | `/api/advance-turn` | Host avança turno |
| `POST` | `/api/exchange/request` | Solicita troca privada |
| `POST` | `/api/exchange/respond` | Aceita/recusa troca |
| `POST` | `/api/spy` | Espia troca alheia |
| `POST` | `/api/vote` | Vota para continuar/encerrar |
| `POST` | `/api/chat` | Envia mensagem de chat |
| `GET`  | `/api/chat/{game_id}` | Histórico do chat |
| `GET`  | `/health` | Health check |

### WebSocket

```
GET ws://<host>/ws/{game_id}/{player_id}
```

Após conectar, o cliente recebe um stream contínuo de eventos JSON do tipo:

```json
{
  "event_type": "guess_result",
  "data": { /* payload específico do evento */ },
  "timestamp": 1714679823000,
  "target_player_id": ""
}
```

Quando `target_player_id` está preenchido, o evento é privado para aquele jogador (palpites pendentes, dicas privadas recebidas, etc.).

### Eventos do servidor

| Evento | Quando ocorre |
|---|---|
| `initial_state` | Logo após conectar, com o snapshot inicial |
| `player_joined` | Alguém entrou na sala |
| `player_kicked` | Alguém foi removido |
| `game_started` | Host iniciou o jogo |
| `hint_sent` | Dica pública publicada |
| `guess_pending` | Palpite enviado (público) |
| `validate_request` | Apenas para o dono — pedido de validação |
| `guess_result` | Resultado do palpite |
| `all_guessed` | Todos os outros adivinharam um mesmo objeto |
| `exchange_request` | Pedido de troca privada (privado para o destinatário) |
| `exchange_announced` | Houve uma solicitação de troca (público) |
| `exchange_accepted` | Troca aceita — dicas reveladas para os participantes |
| `exchange_completed` | Troca encerrada (público) |
| `exchange_rejected` | Troca recusada |
| `spy_attempt` | Alguém tentou espionar |
| `spy_caught` | Alguém foi pego espiando sua troca |
| `you_were_caught_spying` | Você foi pego (privado) |
| `turn_advanced` | Turno avançou |
| `voting_started` | Final dos turnos — votação aberta |
| `vote_update` | Atualização de contagem de votos |
| `new_round` | Nova rodada iniciada |
| `game_finished` | Jogo encerrado, ranking final |
| `chat_message` | Mensagem de chat |
| `heartbeat` | Mensagem de keepalive (a cada 25s) |

### Contrato gRPC

Definido em [`back-end/protos/game.proto`](back-end/protos/game.proto). O serviço `GameService` expõe RPCs unários para todas as ações e um RPC server-streaming `StreamEvents` que alimenta o WebSocket.

---

## Persistência

- O **estado do jogo** (jogadores, objetos, turnos, dicas, trocas, votos) vive **em memória** dentro do processo do gRPC server. Não sobrevive a restarts do backend.
- Apenas o **histórico de chat** é persistido no MongoDB.
- O chat é **apagado automaticamente** em dois momentos:
  - Quando o jogo termina (votação resolveu para encerrar).
  - Quando uma sala nova é criada com um `game_id` cujo chat antigo ficou no banco (limpeza defensiva, p.ex. após restart do backend).

---

## Estrutura do projeto

```
sis_dist/
├── docker-compose.yml          # orquestra mongodb + backend + frontend
├── back-end/
│   ├── Dockerfile
│   ├── entrypoint.sh           # gera proto, sobe gRPC server e gateway
│   ├── requirements.txt
│   ├── protos/
│   │   └── game.proto          # contrato gRPC
│   ├── game_server.py          # servidor gRPC (implementa GameService)
│   ├── gateway.py              # FastAPI: HTTP REST + WebSocket → gRPC
│   ├── game_manager.py         # singleton que agrega todos os services
│   ├── database.py             # camada Mongo (chat)
│   ├── core/
│   │   ├── event_bus.py        # pub/sub em memória por game_id
│   │   └── scoring.py          # sorteio de objetos e cálculo de pontos
│   ├── domain/
│   │   ├── constants.py        # objetos, pontos, status
│   │   └── models.py           # GameState, Player, GuessAttempt, PrivateExchange
│   └── services/
│       ├── base.py             # dependências compartilhadas
│       ├── lobby.py            # join/start/kick
│       ├── gameplay.py         # dicas, palpites, validação, turnos
│       ├── exchange.py         # trocas privadas
│       ├── spy.py              # espionagem
│       └── voting.py           # votação e fim de jogo
└── front-end/
    ├── Dockerfile
    ├── nginx.conf              # proxy /api e /ws → backend:8000
    └── static/
        ├── index.html          # 5 telas: login, lobby, game, voting, result
        └── js/
            └── app.js          # estado, WebSocket, render, ações
```

---

## Variáveis de ambiente

Configuradas em `docker-compose.yml`. Padrões:

| Variável | Padrão | Descrição |
|---|---|---|
| `GRPC_HOST` | `localhost` | Host do gRPC server (consumido pelo gateway no mesmo container) |
| `GRPC_PORT` | `50051` | Porta do gRPC server |
| `HTTP_PORT` | `8000` | Porta do gateway HTTP/WS |
| `MONGO_URI` | `mongodb://mongodb:27017` | URI do Mongo |
| `MONGO_DB` | `guessgame` | Nome do banco |

---

## Notas operacionais

- O Tailwind CDN compila os estilos no carregamento. Após mudanças no front, force um refresh do navegador (`Ctrl+Shift+R`) para invalidar cache.
- O proto é compilado dentro do container no boot, em `entrypoint.sh`. Se mudar `game.proto`, basta reconstruir o backend (`docker compose up -d --build backend`).
- Estado em memória significa que, em produção, escalar horizontalmente o backend exigiria um broker externo (Redis/NATS) para o `event_bus` e um store compartilhado para `GameState`. Para o escopo de jogo local em LAN, uma instância única é suficiente.
- O WebSocket envia um `heartbeat` a cada 25s para manter a conexão viva atrás de proxies.
