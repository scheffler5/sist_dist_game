/**
 * app.js — Lógica completa do cliente do jogo AdivinhAí
 * Comunicação via WebSocket (eventos em tempo real) + HTTP REST (ações do jogo)
 */

// ==================== Configuração ====================
// Usa paths relativos — nginx faz proxy para o backend
const API_BASE = "";
const WS_BASE  = `ws://${location.host}`;

// ==================== Estado do Cliente ====================
let state = {
  playerId: null,
  playerName: null,
  gameId: null,
  isHost: false,
  myObjectName: null,
  myObjectEmoji: null,
  hintSentThisTurn: false,
  exchangeUsed: false,
  pendingValidations: [],   // { guess_id, guesser_name, guess }
  pendingExchangeRequests: [], // { exchange_id, from_id, from_name }
  spyTarget: null,          // { exchange_id, from_name, to_name }
  lastGameState: null,
  ws: null,
  voted: false,
};

// ==================== Navegação de Telas ====================
function showScreen(id) {
  ["login","lobby","game","voting","result"].forEach(s => {
    const el = document.getElementById(`screen-${s}`);
    if (el) {
      el.classList.add("hidden");
      el.classList.remove("flex");
    }
  });
  const target = document.getElementById(`screen-${id}`);
  if (target) {
    target.classList.remove("hidden");
    if (["login","voting","result"].includes(id)) {
      target.classList.add("flex");
    }
  }
}

// ==================== Toast Notifications ====================
function toast(message, type = "info", duration = 4000) {
  const container = document.getElementById("toasts");
  const colors = {
    info:    "bg-gray-800 border-gray-600 text-gray-200",
    success: "bg-green-900 border-green-600 text-green-100",
    error:   "bg-red-900 border-red-600 text-red-100",
    warning: "bg-amber-900 border-amber-600 text-amber-100",
    spy:     "bg-purple-900 border-purple-600 text-purple-100",
  };
  const icons = { info:"ℹ️", success:"✅", error:"❌", warning:"⚠️", spy:"🕵️" };

  const el = document.createElement("div");
  el.className = `border rounded-xl px-4 py-3 text-sm flex gap-2 items-start toast-enter shadow-xl ${colors[type] || colors.info}`;
  el.innerHTML = `<span class="flex-shrink-0 mt-0.5">${icons[type]||"ℹ️"}</span><span class="flex-1">${message}</span>`;
  container.appendChild(el);

  setTimeout(() => {
    el.classList.remove("toast-enter");
    el.classList.add("toast-exit");
    setTimeout(() => el.remove(), 300);
  }, duration);
}

// ==================== Feed de Eventos (in-game) ====================
function addEventFeed(text, color = "bg-gray-800") {
  const feed = document.getElementById("event-feed");
  if (!feed) return;
  const el = document.createElement("div");
  el.className = `${color} border border-gray-700 rounded-xl px-3 py-2 text-xs text-white shadow-lg toast-enter pointer-events-auto`;
  el.textContent = text;
  feed.appendChild(el);
  if (feed.children.length > 5) feed.removeChild(feed.firstChild);
  setTimeout(() => {
    if (el.parentNode) el.remove();
  }, 6000);
}

// ==================== API Helpers ====================
async function api(path, method = "GET", body = null) {
  const opts = {
    method,
    headers: { "Content-Type": "application/json" },
  };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(`${API_BASE}${path}`, opts);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// ==================== WebSocket ====================
function connectWS() {
  if (state.ws) state.ws.close();

  const url = `${WS_BASE}/ws/${state.gameId}/${state.playerId}`;
  state.ws = new WebSocket(url);

  state.ws.onopen = () => {
    console.log("WebSocket conectado");
  };

  state.ws.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data);
      handleEvent(msg.event_type, msg.data);
    } catch (e) {
      console.error("Erro ao parsear evento:", e);
    }
  };

  state.ws.onclose = () => {
    console.log("WebSocket fechado, reconectando em 3s...");
    setTimeout(() => {
      if (state.gameId && state.playerId) connectWS();
    }, 3000);
  };

  state.ws.onerror = (e) => console.error("WebSocket erro:", e);
}

// ==================== Handlers de Eventos ====================
function handleEvent(type, data) {
  // Ignora eventos privados destinados a outro jogador
  if (data && data.target_player_id && data.target_player_id !== state.playerId) return;

  switch (type) {
    case "heartbeat": break;

    case "initial_state":
      if (data.state) applyGameState(data.state);
      if (data.your_object_name) {
        state.myObjectName  = data.your_object_name;
        state.myObjectEmoji = data.your_object_emoji;
        renderMyObject();
      }
      break;

    case "player_joined":
      toast(`${data.player_name} entrou na sala!`, "info");
      refreshState();
      break;

    case "player_kicked":
      if (data.player_id === state.playerId) {
        toast("Você foi removido da sala.", "error");
        resetGame();
      } else {
        toast(`${data.player_name} foi removido.`, "warning");
        renderLobbyPlayers();
      }
      break;

    case "game_started":
      if (data.state) applyGameState(data.state);
      state.myObjectName  = data.your_object_name;
      state.myObjectEmoji = data.your_object_emoji;
      showScreen("game");
      renderMyObject();
      loadChatHistory();
      toast("🚀 Jogo iniciado! Boa sorte!", "success");
      addEventFeed(`🎮 Turno 1 iniciado!`, "bg-indigo-900");
      break;

    case "hint_sent":
      addEventFeed(`💡 ${data.player_name} enviou uma dica no turno ${data.turn}`);
      if (data.player_id === state.playerId) {
        state.hintSentThisTurn = true;
        document.getElementById("hint-status").textContent = "✓ Dica enviada neste turno";
        document.getElementById("hint-status").className = "text-xs text-green-400";
      }
      refreshState();
      break;

    case "guess_pending":
      addEventFeed(`🎯 ${data.guesser_name} tentou adivinhar o objeto de ${data.target_name}: "${data.guess}"`);
      break;

    case "validate_request":
      // Só chega para o dono do objeto
      state.pendingValidations.push({
        guess_id: data.guess_id,
        guesser_name: data.guesser_name,
        guess: data.guess,
      });
      toast(`🎯 ${data.guesser_name} adivinhou "${data.guess}" para seu objeto! Você valida?`, "warning", 10000);
      renderNotifications();
      break;

    case "guess_result":
      if (data.correct) {
        const msg = data.first_correct
          ? `✅ ${data.guesser_name} adivinhou PRIMEIRO o objeto de ${data.target_name}: "${data.object_emoji} ${data.object_name}" (+${data.points} pts)`
          : `✅ ${data.guesser_name} acertou o objeto de ${data.target_name}: "${data.object_emoji} ${data.object_name}" (+${data.points} pts)`;
        toast(msg, "success", 6000);
        addEventFeed(msg, "bg-green-900");
      } else {
        addEventFeed(`❌ ${data.guesser_name} errou o palpite "${data.guess}"`);
      }
      refreshState();
      break;

    case "all_guessed":
      toast(`😬 Todos adivinharam o objeto de ${data.target_name}! "${data.object_name}"`, "warning");
      addEventFeed(`😬 Todos descobriram o objeto de ${data.target_name}!`, "bg-amber-900");
      refreshState();
      break;

    case "exchange_request":
      // Só chega para o destinatário
      state.pendingExchangeRequests.push({
        exchange_id: data.exchange_id,
        from_id: data.from_id,
        from_name: data.from_name,
      });
      toast(`🤝 ${data.from_name} quer trocar dicas com você!`, "warning", 10000);
      renderNotifications();
      break;

    case "exchange_announced":
      addEventFeed(`🤝 ${data.from_name} solicitou troca de dica com ${data.to_name}`, "bg-purple-900");
      break;

    case "exchange_accepted":
      // Para cada participante: recebe as dicas
      toast(`✅ Troca aceita! Dica recebida: "${data.your_hint_received}"`, "success", 8000);
      addEventFeed(`✅ Troca entre ${data.from_name} e ${data.to_name} concluída`);
      refreshState();
      break;

    case "exchange_completed":
      addEventFeed(`🔐 ${data.from_name} e ${data.to_name} concluíram troca privada`, "bg-purple-900");
      refreshState();
      break;

    case "exchange_rejected":
      toast(`❌ ${data.to_name} recusou a troca de dicas.`, "warning");
      addEventFeed(`❌ ${data.to_name} recusou troca com ${data.from_name}`);
      refreshState();
      break;

    case "spy_attempt":
      if (data.discovered) {
        toast(`🚨 ${data.spy_name} foi PEGO espiando a troca de ${data.target1_name} e ${data.target2_name}!`, "warning", 6000);
        addEventFeed(`🚨 ${data.spy_name} foi pego espiando!`, "bg-red-900");
      } else {
        addEventFeed(`👀 Alguém tentou espionar...`, "bg-gray-800");
      }
      break;

    case "spy_caught":
      toast(`👀 ${data.spy_name} tentou espionar sua troca e foi descoberto!`, "warning", 6000);
      refreshState();
      break;

    case "you_were_caught_spying":
      toast(`🚨 Você foi DESCOBERTO espiando! ${data.score_delta} pontos`, "error", 8000);
      refreshState();
      break;

    case "turn_advanced":
      state.hintSentThisTurn = false;
      document.getElementById("hint-status").textContent = "";
      document.getElementById("hud-turn").textContent = `${data.current_turn}/${data.max_turns}`;
      toast(`⏭ Turno ${data.current_turn} de ${data.max_turns}`, "info");
      addEventFeed(`⏭ Turno ${data.current_turn} iniciado!`, "bg-indigo-900");
      refreshState();
      break;

    case "voting_started":
      showScreen("voting");
      renderVotingScores(data.scores);
      toast("🗳️ Limite de turnos! Vote para continuar ou encerrar.", "warning", 8000);
      break;

    case "vote_update":
      document.getElementById("vote-continue-count").textContent = data.votes_continue;
      document.getElementById("vote-end-count").textContent = data.votes_end;
      break;

    case "new_round":
      state.myObjectName  = data.your_object_name;
      state.myObjectEmoji = data.your_object_emoji;
      state.hintSentThisTurn = false;
      state.exchangeUsed = false;
      state.voted = false;
      state.pendingValidations = [];
      state.pendingExchangeRequests = [];
      if (data.state) applyGameState(data.state);
      showScreen("game");
      renderMyObject();
      toast(`🔄 Rodada ${data.round} começou! Novo objeto!`, "success", 6000);
      addEventFeed(`🔄 Rodada ${data.round} iniciada!`, "bg-indigo-900");
      break;

    case "game_finished":
      showScreen("result");
      renderFinalScores(data.final_scores);
      break;

    case "chat_message":
      appendChatMessage(data);
      break;

    default:
      console.log("Evento não tratado:", type, data);
  }
}

// ==================== Ações do Lobby ====================
async function joinGame() {
  const name = document.getElementById("input-name").value.trim();
  const gameId = document.getElementById("input-gameid").value.trim();

  if (!name) { toast("Digite seu nome!", "error"); return; }

  try {
    const res = await api("/api/join", "POST", { player_name: name, game_id: gameId });
    if (!res.success) { toast(res.message, "error"); return; }

    state.playerId = res.player_id;
    state.playerName = name;
    state.gameId = res.game_id;

    document.getElementById("lobby-code").textContent = res.game_id;

    // Conecta WebSocket antes de ir para o lobby
    connectWS();

    // Carrega estado atual
    await refreshState();
    showScreen("lobby");
    toast(res.message, "success");
  } catch (e) {
    toast("Erro ao conectar ao servidor: " + e.message, "error");
  }
}

async function startGame() {
  const maxTurns = parseInt(document.getElementById("max-turns").value) || 5;
  try {
    const res = await api("/api/start", "POST", {
      player_id: state.playerId,
      game_id: state.gameId,
      max_turns: maxTurns,
    });
    if (!res.success) toast(res.message, "error");
  } catch (e) {
    toast("Erro: " + e.message, "error");
  }
}

// ==================== Ações do Jogo ====================
async function sendHint() {
  const hint = document.getElementById("hint-input").value.trim();
  if (!hint) { toast("Digite uma dica!", "error"); return; }
  if (hint.includes(" ")) { toast("A dica deve ser uma única palavra!", "error"); return; }

  try {
    const res = await api("/api/hint", "POST", {
      player_id: state.playerId,
      game_id: state.gameId,
      hint,
    });
    if (res.success) {
      document.getElementById("hint-input").value = "";
    } else {
      toast(res.message, "error");
    }
  } catch (e) {
    toast("Erro: " + e.message, "error");
  }
}

async function sendGuess() {
  const targetId = document.getElementById("guess-target").value;
  const guess = document.getElementById("guess-input").value.trim();

  if (!targetId) { toast("Escolha um jogador!", "error"); return; }
  if (!guess) { toast("Digite seu palpite!", "error"); return; }

  try {
    const res = await api("/api/guess", "POST", {
      guesser_id: state.playerId,
      game_id: state.gameId,
      target_player_id: targetId,
      guess,
    });
    if (res.success) {
      document.getElementById("guess-input").value = "";
      toast("Palpite enviado! Aguardando validação...", "info");
    } else {
      toast(res.message, "error");
    }
  } catch (e) {
    toast("Erro: " + e.message, "error");
  }
}

async function validateGuess(guessId, isCorrect) {
  try {
    const res = await api("/api/validate", "POST", {
      validator_id: state.playerId,
      game_id: state.gameId,
      guess_id: guessId,
      is_correct: isCorrect,
    });
    if (res.success) {
      state.pendingValidations = state.pendingValidations.filter(v => v.guess_id !== guessId);
      renderNotifications();
    } else {
      toast(res.message, "error");
    }
  } catch (e) {
    toast("Erro: " + e.message, "error");
  }
}

async function advanceTurn() {
  try {
    const res = await api("/api/advance-turn", "POST", {
      player_id: state.playerId,
      game_id: state.gameId,
    });
    if (!res.success) toast(res.message, "error");
  } catch (e) {
    toast("Erro: " + e.message, "error");
  }
}

// ==================== Trocas Privadas ====================
async function requestExchange() {
  const toId = document.getElementById("exchange-target").value;
  const hint = document.getElementById("exchange-hint").value.trim();

  if (!toId) { toast("Escolha o jogador para troca!", "error"); return; }
  if (!hint || hint.includes(" ")) { toast("A dica deve ser uma única palavra!", "error"); return; }

  try {
    const res = await api("/api/exchange/request", "POST", {
      from_id: state.playerId,
      to_id: toId,
      game_id: state.gameId,
      hint,
    });
    if (res.success) {
      document.getElementById("exchange-hint").value = "";
      toast("Solicitação de troca enviada!", "success");
    } else {
      toast(res.message, "error");
    }
  } catch (e) {
    toast("Erro: " + e.message, "error");
  }
}

async function respondToExchange(exchangeId, accept) {
  let hint = "";
  if (accept) {
    hint = prompt("Qual dica você quer enviar em troca? (uma palavra)") || "";
    hint = hint.trim().toLowerCase();
    if (!hint || hint.includes(" ")) {
      toast("A dica deve ser uma única palavra!", "error");
      return;
    }
  }

  try {
    const res = await api("/api/exchange/respond", "POST", {
      responder_id: state.playerId,
      game_id: state.gameId,
      exchange_id: exchangeId,
      accept,
      hint,
    });
    if (res.success) {
      state.pendingExchangeRequests = state.pendingExchangeRequests.filter(
        r => r.exchange_id !== exchangeId
      );
      renderNotifications();
    } else {
      toast(res.message, "error");
    }
  } catch (e) {
    toast("Erro: " + e.message, "error");
  }
}

// ==================== Espionagem ====================
function openSpy(exchangeId, fromName, toName) {
  state.spyTarget = { exchange_id: exchangeId, from_name: fromName, to_name: toName };
  document.getElementById("spy-target-names").textContent = `${fromName} e ${toName}`;
  document.getElementById("modal-spy").classList.remove("hidden");
}

function closeSpy() {
  state.spyTarget = null;
  document.getElementById("modal-spy").classList.add("hidden");
}

async function confirmSpy() {
  if (!state.spyTarget) return;
  const target = state.spyTarget;
  closeSpy();

  try {
    const res = await api("/api/spy", "POST", {
      spy_id: state.playerId,
      game_id: state.gameId,
      exchange_id: target.exchange_id,
    });

    if (res.success) {
      if (res.discovered) {
        toast(`🚨 Você foi PEGO espiando! Perdeu ${Math.abs(res.score_delta || 5)} pontos.`, "error", 8000);
      } else {
        toast(
          `🕵️ Espionagem bem-sucedida!\n${target.from_name}: "${res.hint1}"\n${target.to_name}: "${res.hint2}"`,
          "spy", 10000
        );
        // Mostra as dicas em um popup visual
        showSpyResult(res.hint1, res.hint2, target.from_name, target.to_name);
      }
    } else {
      toast(res.message, "error");
    }
  } catch (e) {
    toast("Erro: " + e.message, "error");
  }
}

function showSpyResult(hint1, hint2, name1, name2) {
  const container = document.getElementById("event-feed");
  const el = document.createElement("div");
  el.className = "bg-purple-900 border border-purple-600 rounded-xl px-4 py-3 text-sm text-white shadow-xl toast-enter pointer-events-auto";
  el.innerHTML = `
    <div class="font-bold mb-1">🕵️ Dicas espionadas:</div>
    <div>${name1}: <span class="text-purple-300 font-mono">${hint1}</span></div>
    <div>${name2}: <span class="text-purple-300 font-mono">${hint2}</span></div>
  `;
  container.appendChild(el);
  setTimeout(() => el.remove(), 12000);
}

// ==================== Votação ====================
async function vote(continueGame) {
  if (state.voted) { toast("Você já votou!", "warning"); return; }
  state.voted = true;

  try {
    const res = await api("/api/vote", "POST", {
      player_id: state.playerId,
      game_id: state.gameId,
      continue_game: continueGame,
    });
    if (res.success) {
      document.getElementById("vote-buttons").classList.add("hidden");
      document.getElementById("vote-status").classList.remove("hidden");
      toast(continueGame ? "✅ Você votou para continuar!" : "🏁 Você votou para encerrar!", "success");
    } else {
      state.voted = false;
      toast(res.message, "error");
    }
  } catch (e) {
    state.voted = false;
    toast("Erro: " + e.message, "error");
  }
}

// ==================== Chat ====================
async function sendChat() {
  const input = document.getElementById("chat-input");
  const msg = input.value.trim();
  if (!msg) return;
  input.value = "";

  try {
    await api("/api/chat", "POST", {
      player_id: state.playerId,
      player_name: state.playerName,
      game_id: state.gameId,
      message: msg,
    });
  } catch (e) {
    toast("Erro no chat: " + e.message, "error");
  }
}

function appendChatMessage(data) {
  const container = document.getElementById("chat-messages");
  if (!container) return;

  const isMe = data.player_id === state.playerId;
  const time = new Date(data.timestamp).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });

  const el = document.createElement("div");
  el.className = isMe ? "text-right" : "text-left";
  el.innerHTML = `
    <div class="inline-block max-w-[85%] ${isMe ? "bg-indigo-900 text-indigo-100" : "bg-gray-800 text-gray-200"} rounded-xl px-3 py-2 text-sm">
      ${!isMe ? `<div class="text-xs text-gray-400 mb-0.5 font-medium">${escapeHtml(data.player_name)}</div>` : ""}
      <div>${escapeHtml(data.message)}</div>
      <div class="text-xs opacity-50 mt-0.5">${time}</div>
    </div>
  `;
  container.appendChild(el);
  container.scrollTop = container.scrollHeight;
}

async function loadChatHistory() {
  try {
    const messages = await api(`/api/chat/${state.gameId}?limit=50`);
    const container = document.getElementById("chat-messages");
    if (container) container.innerHTML = "";
    messages.forEach(appendChatMessage);
  } catch (e) {
    console.error("Erro ao carregar chat:", e);
  }
}

// ==================== Render State ====================
async function refreshState() {
  if (!state.gameId || !state.playerId) return;
  try {
    const gameState = await api(`/api/state/${state.gameId}/${state.playerId}`);
    applyGameState(gameState);
  } catch (e) {
    console.error("Erro ao atualizar estado:", e);
  }
}

function applyGameState(gameState) {
  state.lastGameState = gameState;

  // Atualiza HUD
  if (document.getElementById("hud-gameid"))
    document.getElementById("hud-gameid").textContent = gameState.game_id;
  if (document.getElementById("hud-turn"))
    document.getElementById("hud-turn").textContent = `${gameState.current_turn}/${gameState.max_turns}`;
  if (document.getElementById("hud-round"))
    document.getElementById("hud-round").textContent = gameState.current_round;

  const me = gameState.players[state.playerId];
  if (me) {
    if (document.getElementById("hud-score"))
      document.getElementById("hud-score").textContent = me.score;
    state.isHost = me.is_host;
    state.hintSentThisTurn = me.hint_sent_this_turn;
    state.exchangeUsed = me.private_exchange_used;

    // Status da dica
    const hintStatus = document.getElementById("hint-status");
    if (hintStatus) {
      if (me.hint_sent_this_turn) {
        hintStatus.textContent = "✓ Dica enviada neste turno";
        hintStatus.className = "text-xs text-green-400";
      } else {
        hintStatus.textContent = "";
      }
    }

    // Status da troca
    const exchangeMsg = document.getElementById("exchange-used-msg");
    if (exchangeMsg) {
      if (me.private_exchange_used) {
        exchangeMsg.classList.remove("hidden");
      } else {
        exchangeMsg.classList.add("hidden");
      }
    }
  }

  // Atualiza minhas dicas
  if (me) {
    const myHintsList = document.getElementById("my-hints-list");
    if (myHintsList) {
      const hints = me.public_hints || [];
      myHintsList.innerHTML = hints.length
        ? hints.map(h => `<span class="bg-indigo-900/70 text-indigo-200 px-2 py-0.5 rounded-full text-xs font-mono">${escapeHtml(h)}</span>`).join("")
        : '<span class="text-xs text-gray-500 italic">Nenhuma ainda</span>';
    }
  }

  // Controles do host
  const hostCtrl = document.getElementById("host-turn-controls");
  if (hostCtrl) {
    if (state.isHost && gameState.status === "playing") {
      hostCtrl.classList.remove("hidden");
    } else {
      hostCtrl.classList.add("hidden");
    }
  }

  // Atualiza selects de alvo
  updatePlayerSelects(gameState);

  // Renderiza jogadores
  renderPlayers(gameState);
  renderScoreboard(gameState);
  renderExchanges(gameState);
  renderLobbyPlayersFromState(gameState);
}

function updatePlayerSelects(gameState) {
  const selects = ["guess-target", "exchange-target"];
  selects.forEach(id => {
    const sel = document.getElementById(id);
    if (!sel) return;
    const curr = sel.value;
    sel.innerHTML = '<option value="">Escolha o jogador...</option>';
    Object.values(gameState.players).forEach(p => {
      if (p.id === state.playerId) return;
      if (id === "guess-target" && p.object_guessed) return;
      const opt = document.createElement("option");
      opt.value = p.id;
      opt.textContent = p.name + (p.object_guessed ? " ✓" : "");
      if (p.id === curr) opt.selected = true;
      sel.appendChild(opt);
    });
  });
}

function renderPlayers(gameState) {
  const grid = document.getElementById("players-grid");
  if (!grid) return;
  grid.innerHTML = "";

  Object.values(gameState.players).forEach(p => {
    if (p.id === state.playerId) return;

    const hintBadges = p.public_hints.map(h =>
      `<span class="bg-gray-700 text-gray-200 px-2 py-0.5 rounded-full text-xs font-mono">${escapeHtml(h)}</span>`
    ).join("") || '<span class="text-gray-500 text-xs italic">Sem dicas ainda</span>';

    const guessedBadge = p.object_guessed
      ? `<span class="bg-green-900 text-green-300 px-2 py-0.5 rounded-full text-xs">✅ Adivinhado: ${p.object_emoji} ${p.object_name}</span>`
      : "";

    const card = document.createElement("div");
    card.className = "bg-gray-800 rounded-xl p-3 border border-gray-700 hover:border-gray-600 transition";
    card.innerHTML = `
      <div class="flex items-center justify-between mb-2">
        <div class="flex items-center gap-2">
          <span class="text-lg">${p.is_host ? "👑" : "🎭"}</span>
          <span class="font-semibold text-white text-sm">${escapeHtml(p.name)}</span>
          ${p.hint_sent_this_turn ? '<span class="text-xs bg-indigo-900 text-indigo-300 px-1.5 py-0.5 rounded">dica ✓</span>' : ''}
        </div>
        <span class="text-green-400 font-bold text-sm">${p.score} pts</span>
      </div>
      <div class="flex flex-wrap gap-1 mb-2">${hintBadges}</div>
      ${guessedBadge ? `<div class="mt-1">${guessedBadge}</div>` : ""}
    `;
    grid.appendChild(card);
  });

  if (!grid.children.length) {
    grid.innerHTML = '<p class="text-gray-500 text-sm italic">Aguardando outros jogadores...</p>';
  }
}

function renderMyObject() {
  const emojiEl = document.getElementById("my-emoji");
  const nameEl  = document.getElementById("my-object-name");
  if (emojiEl) emojiEl.textContent = state.myObjectEmoji || "❓";
  if (nameEl)  nameEl.textContent  = state.myObjectName  || "";
}

function renderScoreboard(gameState) {
  const board = document.getElementById("scoreboard");
  if (!board) return;

  const sorted = Object.values(gameState.players).sort((a, b) => b.score - a.score);
  board.innerHTML = sorted.map((p, i) => {
    const medal = i === 0 ? "🥇" : i === 1 ? "🥈" : i === 2 ? "🥉" : `${i+1}.`;
    const isMe = p.id === state.playerId;
    return `
      <div class="flex items-center justify-between ${isMe ? "bg-indigo-950/60 border border-indigo-800/50" : "bg-gray-800"} rounded-lg px-3 py-2">
        <div class="flex items-center gap-2">
          <span>${medal}</span>
          <span class="text-sm ${isMe ? "text-indigo-200 font-bold" : "text-gray-200"}">${escapeHtml(p.name)}</span>
          ${isMe ? '<span class="text-xs text-indigo-400">(você)</span>' : ""}
        </div>
        <span class="font-bold text-green-400">${p.score}</span>
      </div>
    `;
  }).join("");
}

function renderExchanges(gameState) {
  const list = document.getElementById("exchanges-list");
  if (!list) return;

  const exchanges = gameState.private_exchanges || [];
  if (!exchanges.length) {
    list.innerHTML = '<p class="text-xs text-gray-500 italic">Nenhuma troca ainda</p>';
    return;
  }

  list.innerHTML = exchanges.map(ex => {
    const statusColor = {
      pending:  "text-amber-400",
      accepted: "text-green-400",
      rejected: "text-red-400",
    }[ex.status] || "text-gray-400";

    const statusLabel = { pending: "⏳ Pendente", accepted: "✅ Aceita", rejected: "❌ Recusada" }[ex.status];

    const isParticipant = ex.from_id === state.playerId || ex.to_id === state.playerId;
    const hintsHtml = (isParticipant || ex.spied) && ex.status === "accepted"
      ? `<div class="mt-1.5 text-xs space-y-0.5">
          <div class="text-gray-300">${escapeHtml(ex.from_name)}: <span class="font-mono text-purple-300">${escapeHtml(ex.from_hint)}</span></div>
          <div class="text-gray-300">${escapeHtml(ex.to_name)}: <span class="font-mono text-purple-300">${escapeHtml(ex.to_hint)}</span></div>
        </div>`
      : "";

    const spyBtn = (!isParticipant && ex.status === "accepted")
      ? `<button onclick="openSpy('${ex.id}','${escapeHtml(ex.from_name)}','${escapeHtml(ex.to_name)}')"
          class="text-xs bg-amber-900/50 hover:bg-amber-900 text-amber-300 px-2 py-0.5 rounded transition mt-1.5">
          🕵️ Espionar
        </button>`
      : "";

    return `
      <div class="bg-gray-800 rounded-xl p-3 border border-gray-700">
        <div class="flex items-center justify-between">
          <span class="text-xs text-gray-300 font-medium">${escapeHtml(ex.from_name)} ↔ ${escapeHtml(ex.to_name)}</span>
          <span class="text-xs ${statusColor}">${statusLabel}</span>
        </div>
        ${hintsHtml}
        ${spyBtn}
      </div>
    `;
  }).join("");
}

function renderNotifications() {
  const panel = document.getElementById("notifications-panel");
  const list  = document.getElementById("notifications-list");
  if (!panel || !list) return;

  const items = [];

  // Validações pendentes
  state.pendingValidations.forEach(v => {
    items.push(`
      <div class="bg-amber-900/30 border border-amber-700/40 rounded-xl p-3">
        <p class="text-sm text-amber-200 mb-2">
          <strong>${escapeHtml(v.guesser_name)}</strong> disse que seu objeto é
          <strong class="text-white">"${escapeHtml(v.guess)}"</strong>. Está correto?
        </p>
        <div class="flex gap-2">
          <button onclick="validateGuess('${v.guess_id}', true)"
            class="flex-1 bg-green-700 hover:bg-green-600 text-white text-sm font-bold py-1.5 rounded-lg transition">
            ✅ Sim
          </button>
          <button onclick="validateGuess('${v.guess_id}', false)"
            class="flex-1 bg-red-700 hover:bg-red-600 text-white text-sm font-bold py-1.5 rounded-lg transition">
            ❌ Não
          </button>
        </div>
      </div>
    `);
  });

  // Pedidos de troca pendentes
  state.pendingExchangeRequests.forEach(r => {
    items.push(`
      <div class="bg-purple-900/30 border border-purple-700/40 rounded-xl p-3">
        <p class="text-sm text-purple-200 mb-2">
          <strong>${escapeHtml(r.from_name)}</strong> quer trocar dicas com você!
        </p>
        <div class="flex gap-2">
          <button onclick="respondToExchange('${r.exchange_id}', true)"
            class="flex-1 bg-purple-700 hover:bg-purple-600 text-white text-sm font-bold py-1.5 rounded-lg transition">
            ✅ Aceitar
          </button>
          <button onclick="respondToExchange('${r.exchange_id}', false)"
            class="flex-1 bg-gray-700 hover:bg-gray-600 text-white text-sm font-bold py-1.5 rounded-lg transition">
            ❌ Recusar
          </button>
        </div>
      </div>
    `);
  });

  if (items.length) {
    panel.classList.remove("hidden");
    list.innerHTML = items.join("");
  } else {
    panel.classList.add("hidden");
    list.innerHTML = "";
  }
}

function renderLobbyPlayers() {
  if (!state.lastGameState) return;
  renderLobbyPlayersFromState(state.lastGameState);
}

function renderLobbyPlayersFromState(gameState) {
  const container = document.getElementById("lobby-players");
  if (!container) return;

  const players = Object.values(gameState.players || {});
  container.innerHTML = players.map(p => `
    <div class="flex items-center justify-between bg-gray-800 rounded-xl px-4 py-3">
      <div class="flex items-center gap-3">
        <span class="text-xl">${p.is_host ? "👑" : "🎭"}</span>
        <span class="font-medium text-white">${escapeHtml(p.name)}</span>
        ${p.id === state.playerId ? '<span class="text-xs text-indigo-400">(você)</span>' : ""}
      </div>
      ${p.is_host ? '<span class="text-xs text-amber-400 bg-amber-900/30 px-2 py-0.5 rounded-full">Host</span>' : ""}
    </div>
  `).join("") || '<p class="text-gray-500 text-sm italic">Nenhum jogador ainda...</p>';

  // Controles do host
  const hostCtrl = document.getElementById("host-controls");
  if (hostCtrl) {
    if (state.isHost) hostCtrl.classList.remove("hidden");
    else hostCtrl.classList.add("hidden");
  }
}

function renderVotingScores(scores) {
  const container = document.getElementById("voting-scores");
  if (!container) return;

  if (!scores) {
    container.innerHTML = "<p class='text-sm text-gray-400'>Carregando...</p>";
    return;
  }

  const sorted = Object.entries(scores).sort((a, b) => b[1] - a[1]);
  const names = state.lastGameState?.players || {};

  container.innerHTML = `
    <div class="text-xs text-gray-400 font-semibold uppercase tracking-wider mb-2">Pontuação atual</div>
    ${sorted.map(([pid, pts], i) => {
      const medal = i === 0 ? "🥇" : i === 1 ? "🥈" : i === 2 ? "🥉" : `${i+1}.`;
      const pname = names[pid]?.name || pid;
      const isMe = pid === state.playerId;
      return `
        <div class="flex justify-between items-center ${isMe ? "text-indigo-300" : "text-white"}">
          <span class="text-sm">${medal} ${escapeHtml(pname)} ${isMe ? "(você)" : ""}</span>
          <span class="font-bold text-green-400">${pts} pts</span>
        </div>
      `;
    }).join("")}
  `;

  // Reset voto
  state.voted = false;
  document.getElementById("vote-buttons").classList.remove("hidden");
  document.getElementById("vote-status").classList.add("hidden");
  document.getElementById("vote-continue-count").textContent = "0";
  document.getElementById("vote-end-count").textContent = "0";
}

function renderFinalScores(scores) {
  const container = document.getElementById("final-scores");
  if (!container || !scores) return;

  container.innerHTML = scores.map((p, i) => {
    const medal = i === 0 ? "🥇" : i === 1 ? "🥈" : i === 2 ? "🥉" : `${i+1}.`;
    const isMe = p.id === state.playerId;
    return `
      <div class="flex items-center justify-between ${isMe ? "bg-indigo-950 border border-indigo-700" : "bg-gray-800"} rounded-xl px-5 py-4">
        <div class="flex items-center gap-3">
          <span class="text-2xl">${medal}</span>
          <div>
            <div class="font-bold text-white">${escapeHtml(p.name)}</div>
            ${isMe ? '<div class="text-xs text-indigo-400">você</div>' : ""}
          </div>
        </div>
        <span class="text-3xl font-black text-green-400">${p.score}</span>
      </div>
    `;
  }).join("");
}

// ==================== Utilidades ====================
function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function resetGame() {
  if (state.ws) { state.ws.close(); state.ws = null; }
  state = {
    playerId: null, playerName: null, gameId: null, isHost: false,
    myObjectName: null, myObjectEmoji: null, hintSentThisTurn: false,
    exchangeUsed: false, pendingValidations: [], pendingExchangeRequests: [],
    spyTarget: null, lastGameState: null, ws: null, voted: false,
  };
  document.getElementById("input-name").value = "";
  document.getElementById("input-gameid").value = "";
  showScreen("login");
}

// ==================== Inicialização ====================
document.addEventListener("DOMContentLoaded", () => {
  showScreen("login");

  // Enter no login
  document.getElementById("input-name").addEventListener("keydown", e => {
    if (e.key === "Enter") joinGame();
  });
  document.getElementById("input-gameid").addEventListener("keydown", e => {
    if (e.key === "Enter") joinGame();
  });
});
