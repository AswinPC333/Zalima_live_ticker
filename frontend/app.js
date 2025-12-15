// app.js — WebSocket client + UI logic
const WS_URL = "ws://localhost:8000/ws";

let socket;

const grid = document.getElementById("grid");
const empty = document.getElementById("empty");
const statusBadge = document.getElementById("statusBadge");
const symbolInput = document.getElementById("symbolInput");
const subBtn = document.getElementById("subBtn");
const companyList = document.getElementById("companyList");

/* ---------- TOP 10 COMPANIES ---------- */
const TOP_COMPANIES = [
  { name: "Apple Inc.", symbol: "AAPL" },
  { name: "Microsoft", symbol: "MSFT" },
  { name: "Amazon", symbol: "AMZN" },
  { name: "Alphabet", symbol: "GOOGL" },
  { name: "Meta", symbol: "META" },
  { name: "Tesla", symbol: "TSLA" },
  { name: "NVIDIA", symbol: "NVDA" },
  { name: "Netflix", symbol: "NFLX" },
  { name: "Intel", symbol: "INTC" },
  { name: "IBM", symbol: "IBM" }
];

// in-memory state
const cards = {};

/* ---------- STATUS ---------- */
function setStatus(text, ok = false) {
  statusBadge.textContent = text;
  statusBadge.style.background = ok
    ? "rgba(16,185,129,0.12)"
    : "rgba(255,255,255,0.03)";
}

/* ---------- SIDEBAR ---------- */
function renderCompanyList() {
  companyList.innerHTML = "";
  TOP_COMPANIES.forEach(c => {
    const li = document.createElement("li");
    li.className = "company-item";
    li.innerHTML = `
      <div class="company-name">${c.name}</div>
      <div class="company-symbol">${c.symbol}</div>
    `;
    li.onclick = () => subscribeSymbol(c.symbol);
    companyList.appendChild(li);
  });
}

/* ---------- SUBSCRIBE ---------- */
function subscribeSymbol(symbol) {
  symbol = symbol.toUpperCase();
  if (cards[symbol]) return;

  if (socket?.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ cmd: "subscribe", symbol }));
    cards[symbol] = { last: null, prices: [] };
    drawCard(symbol);
  }
}

/* ---------- REMOVE ---------- */
function removeSymbol(symbol) {
  document.getElementById("card-" + symbol)?.remove();
  delete cards[symbol];

  if (socket?.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ cmd: "unsubscribe", symbol }));
  }

  if (!Object.keys(cards).length) {
    empty.style.display = "block";
  }
}

/* ---------- CARDS ---------- */
function drawCard(symbol) {
  const card = document.createElement("div");
  card.className = "card";
  card.id = "card-" + symbol;

  card.innerHTML = `
    <div class="row">
      <div>
        <div class="symbol">${symbol}</div>
        <div class="muted">Live trades • real-time</div>
      </div>

      <div style="text-align:right">
        <button class="remove-btn">✕</button>
        <div class="price" id="price-${symbol}">—</div>
        <div id="change-${symbol}" class="change muted">—</div>
      </div>
    </div>
    <canvas id="spark-${symbol}" class="spark"></canvas>
  `;

  card.querySelector(".remove-btn").onclick = () => removeSymbol(symbol);
  grid.prepend(card);
  empty.style.display = "none";
}

/* ---------- UPDATE ---------- */
function updateCard(symbol, price) {
  if (!cards[symbol]) return;

  const pEl = document.getElementById(`price-${symbol}`);
  const cEl = document.getElementById(`change-${symbol}`);
  const canvas = document.getElementById(`spark-${symbol}`);
  const state = cards[symbol];

  const prev = state.last ?? price;
  state.last = price;
  state.prices.push(price);
  if (state.prices.length > 30) state.prices.shift();

  pEl.textContent = "$" + price.toFixed(2);
  const diff = price - prev;
  const pct = ((diff / prev) * 100).toFixed(2);
  cEl.textContent = `${diff >= 0 ? "+" : ""}${diff.toFixed(2)} (${pct}%)`;
  cEl.style.color = diff >= 0 ? "var(--success)" : "var(--danger)";

  drawSpark(canvas, state.prices);
}

/* ---------- SPARK ---------- */
function drawSpark(canvas, prices) {
  const ctx = canvas.getContext("2d");
  const w = canvas.width = canvas.offsetWidth;
  const h = canvas.height = canvas.offsetHeight;

  ctx.clearRect(0, 0, w, h);
  if (!prices.length) return;

  const min = Math.min(...prices);
  const max = Math.max(...prices);
  const range = max - min || 1;

  ctx.beginPath();
  prices.forEach((p, i) => {
    const x = (i / (prices.length - 1)) * w;
    const y = h - ((p - min) / range) * h;
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  });

  ctx.strokeStyle = "#06b6d4";
  ctx.lineWidth = 2;
  ctx.stroke();
}

/* ---------- SOCKET ---------- */
function connect() {
  socket = new WebSocket(WS_URL);

  socket.onopen = () => {
    setStatus("Connected", true);
    socket.send(JSON.stringify({ cmd: "ping" }));
  };

  socket.onmessage = (evt) => {
    let msg;
    try { msg = JSON.parse(evt.data); } catch { return; }

    if (msg.type === "status") {
      setStatus(
        msg.connected ? "Finnhub: Connected" : "Finnhub: Disconnected",
        msg.connected
      );
    }

    if (msg.type === "trade") {
      const s = msg.symbol;
      const p = msg.data?.p ?? msg.data?.price;
      if (p != null) updateCard(s, p);
    }
  };

  socket.onclose = () => {
    setStatus("Disconnected");
    setTimeout(connect, 2000);
  };
}

/* ---------- EVENTS ---------- */
subBtn.onclick = () => {
  const symbol = symbolInput.value.trim();
  if (symbol) subscribeSymbol(symbol);
  symbolInput.value = "";
};

/* ---------- INIT ---------- */
renderCompanyList();
connect();
