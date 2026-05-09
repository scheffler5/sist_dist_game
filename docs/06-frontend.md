# 6. Frontend

O frontend é deliberadamente **minimalista**: HTML estático, JavaScript puro, Tailwind via CDN. Sem framework, sem build step, sem bundler. Tudo cabe em dois arquivos: [`index.html`](../front-end/static/index.html) e [`js/app.js`](../front-end/static/js/app.js).

## Stack

| Item | Tecnologia |
|---|---|
| Markup | HTML5 estático |
| Estilo | Tailwind CSS via CDN (`cdn.tailwindcss.com`) compilado no carregamento da página |
| Lógica | JavaScript puro (ES2020+), sem bibliotecas |
| Comunicação | `fetch()` (REST) e `WebSocket` nativo |
| Servidor | Nginx |

## Telas

São **5 telas** num único `index.html`. A função `showScreen(id)` em `app.js` esconde todas e mostra apenas a alvo.

| ID | Tela | Mostrada quando |
|---|---|---|
| `screen-login` | Entrada (nome + código) | Estado inicial |
| `screen-lobby` | Sala de espera | Após `joinGame()` bem-sucedido |
| `screen-game` | Tabuleiro principal | Após `game_started` |
| `screen-voting` | Votação (continuar/encerrar) | Após `voting_started` |
| `screen-result` | Ranking final | Após `game_finished` |

Há também um **modal** sobreposto:

- `modal-spy` — confirmação de espionagem (mostra a chance de ser pego).

## Estado do cliente

Tudo num único objeto global:

```js
let state = {
  playerId: null,
  playerName: null,
  gameId: null,
  isHost: false,
  myObjectName: null,
  myObjectEmoji: null,
  hintSentThisTurn: false,
  exchangeUsed: false,
  pendingValidations: [],       // {guess_id, guesser_name, guess}
  pendingExchangeRequests: [],  // {exchange_id, from_id, from_name}
  spyTarget: null,              // dados temporários do modal
  lastGameState: null,          // último snapshot recebido
  ws: null,                     // WebSocket atual
  voted: false,
};
```

A função `resetGame()` reinicializa esse objeto e fecha o WebSocket.

## Comunicação com o backend

### Helper REST

```js
async function api(path, method = "GET", body = null) {
  const opts = { method, headers: {"Content-Type": "application/json"} };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(`${API_BASE}${path}`, opts);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}
```

`API_BASE = ""` — todas as chamadas são relativas. O nginx faz o proxy de `/api/*` para o backend.

### WebSocket

```js
function connectWS() {
  if (state.ws) state.ws.close();
  const url = `${WS_BASE}/ws/${state.gameId}/${state.playerId}`;
  state.ws = new WebSocket(url);

  state.ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    handleEvent(msg.event_type, msg.data);
  };

  state.ws.onclose = () => {
    setTimeout(() => {
      if (state.gameId && state.playerId) connectWS();
    }, 3000);
  };
}
```

- **Auto-reconect**: 3s após qualquer fechamento.
- O envio é **unilateral**: o cliente só recebe pelo WebSocket. Toda ação que muda estado vai pelo REST.

## Despacho de eventos — `handleEvent`

```
WebSocket.onmessage
       │
       ▼
JSON.parse → {event_type, data, timestamp, target_player_id}
       │
       ├─ filtra eventos com target_player_id != state.playerId  (defensivo)
       ▼
switch (event_type) {
   "initial_state":      ← snapshot completo + objeto secreto
   "player_joined":      → toast + refreshState
   "player_kicked":      → resetGame se for você, senão toast
   "game_started":       → mostra screen-game, carrega chat history
   "hint_sent":          → addEventFeed
   "guess_pending":      → addEventFeed (público)
   "validate_request":   → push em pendingValidations + toast (privado)
   "guess_result":       → toast + addEventFeed
   "all_guessed":        → toast
   "exchange_request":   → push em pendingExchangeRequests (privado)
   "exchange_announced": → addEventFeed (público)
   "exchange_accepted":  → toast com a dica recebida (privado)
   "exchange_completed": → addEventFeed
   "exchange_rejected":  → toast
   "spy_attempt":        → addEventFeed; se discovered, toast
   "spy_caught":         → toast (privado para participantes da troca)
   "you_were_caught_spying": → toast (privado para o espião)
   "turn_advanced":      → reseta hint_sent_this_turn local + toast
   "voting_started":     → showScreen("voting") + render dos placares
   "vote_update":        → atualiza contadores
   "new_round":          → showScreen("game") + novo objeto
   "game_finished":      → showScreen("result") + render final
   "chat_message":       → appendChatMessage
   "heartbeat":          → ignora
}
```

## Render

Funções de render leem `state.lastGameState` e re-pintam DOM. Não há reconciliação tipo virtual DOM — `innerHTML` é reescrito a cada update.

| Função | Atualiza |
|---|---|
| `applyGameState(gs)` | HUD, status, dicas, controles do host, dispara renders abaixo |
| `updatePlayerSelects` | `<select>` de palpite e troca |
| `renderPlayers` | cards dos outros jogadores |
| `renderScoreboard` | placar lateral |
| `renderExchanges` | trocas privadas (com botão de espionagem condicional) |
| `renderNotifications` | painel "aguardando sua ação" (validações + pedidos de troca) |
| `renderLobbyPlayersFromState` | lista no lobby |
| `renderMyObject` | seu objeto secreto (emoji + nome) |
| `renderVotingScores` | placar na tela de votação |
| `renderFinalScores` | ranking na tela final |

`refreshState()` faz `GET /api/state/{gid}/{pid}` e despacha para `applyGameState`. Chamado depois de cada evento que possa ter mudado dados (turno avançou, palpite resolvido, etc.).

## Seleção de cor (toasts)

O sistema de toast tem 5 tipos com bordas distintas:

```js
const styles = {
  info:    "bg-zinc-900 border-zinc-700 text-zinc-100",
  success: "bg-zinc-900 border-emerald-800 text-zinc-100",
  error:   "bg-zinc-900 border-red-800 text-zinc-100",
  warning: "bg-zinc-900 border-amber-800 text-zinc-100",
  spy:     "bg-zinc-900 border-blue-800 text-zinc-100",
};
```

Mesma base zinc para tudo, com a borda variando para sinalizar o tom. Sem ícones e sem fundos saturados — escolha estilística do redesign.

## Chat

- Mensagens são enviadas via `POST /api/chat`.
- O histórico inicial é carregado via `GET /api/chat/{game_id}` em `loadChatHistory()`, chamado em `game_started`.
- Mensagens novas chegam pelo evento `chat_message` no WebSocket e são empilhadas em `#chat-messages`.
- Não há indicador "digitando", não há edição/exclusão.

## Feed de eventos lateral

`#event-feed` no canto inferior esquerdo mostra os 5 eventos mais recentes do jogo (palpites errados, dicas enviadas, trocas concluídas...). Cada item dura 6s e é removido automaticamente.

```js
function addEventFeed(text) {
  const feed = document.getElementById("event-feed");
  const el = document.createElement("div");
  el.className = "bg-zinc-900 border border-zinc-800 rounded-md ... text-zinc-300";
  el.textContent = text;
  feed.appendChild(el);
  if (feed.children.length > 5) feed.removeChild(feed.firstChild);
  setTimeout(() => el.parentNode && el.remove(), 6000);
}
```

## Acessibilidade e segurança

- `escapeHtml(str)` é aplicado em qualquer texto vindo de outro jogador antes de ir para `innerHTML`. Cobre `&`, `<`, `>`, `"`. Aspas simples não são escapadas — atributos com strings vindas de jogador (ex: `onclick="openSpy('${name}')"`) podem quebrar com nomes contendo `'`.
- Não há autenticação no front — `state.playerId` é o único token. Se vazar, qualquer um pode agir como o jogador.

## Por que sem framework

- Pega leve. Carga mínima.
- Mostra de forma direta o uso dos protocolos (fetch + WebSocket), que é o foco do exercício.
- Tailwind CDN cobre a estilização sem dependências de build.

O lado negativo é o re-render por `innerHTML`, que perde o foco de inputs e cresce em complexidade quando o estado interativo aumenta. Para o tamanho atual, é aceitável.

## Servir o frontend

[`front-end/Dockerfile`](../front-end/Dockerfile):

```dockerfile
FROM nginx:1.27-alpine
RUN rm /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/app.conf
COPY static/ /usr/share/nginx/html/
EXPOSE 80
```

Imagem leve, configuração customizada do nginx, arquivos estáticos copiados. Alterações no front exigem `docker compose up -d --build frontend`.
