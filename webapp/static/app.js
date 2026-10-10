"use strict";
(function () {
  var START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";
  var GLYPH = { k: "♚", q: "♛", r: "♜", b: "♝", n: "♞", p: "♟" };
  var QVAR = {
    best: "--best", good: "--good", excellent: "--excellent", inaccuracy: "--inaccuracy",
    mistake: "--mistake", blunder: "--blunder", brilliant: "--brilliant"
  };

  // ---- state ----
  var S = {
    fen: START,
    orient: "white",      // which color sits at the bottom
    human: "white",
    level: 3,
    useLlm: true,
    moves: [],            // {fen, san, side, coaching?}
    legal: [],            // array of legal uci strings for current side
    sel: null,            // selected source square
    last: null,           // {from,to} of last move
    coaching: null,       // current coaching payload to display
    showRef: false,
    busy: false
  };

  // ---- dom ----
  var board = document.getElementById("board");
  var arrows = document.getElementById("arrows");
  var panel = document.getElementById("panel");
  var statusline = document.getElementById("statusline");
  var movegrid = document.getElementById("movegrid");
  var promo = document.getElementById("promo");
  var refBtn = document.getElementById("refBtn");

  function cvar(n) { return getComputedStyle(document.documentElement).getPropertyValue(n).trim(); }
  function turnOf(fen) { return fen.split(" ")[1] === "w" ? "white" : "black"; }

  async function api(path, body) {
    var res = await fetch(path, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {})
    });
    var data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || ("HTTP " + res.status));
    return data;
  }

  // ---- board geometry ----
  function parseFEN(fen) {
    var rows = fen.split(" ")[0].split("/"), grid = [];
    for (var r = 0; r < 8; r++) {
      var row = [], ch = rows[r];
      for (var c = 0; c < ch.length; c++) {
        var x = ch[c];
        if (/\d/.test(x)) { var n = +x; while (n--) row.push(null); }
        else row.push(x);
      }
      grid.push(row);
    }
    return grid; // grid[0]=rank8
  }
  function sqName(boardRow, boardCol) {
    return String.fromCharCode(97 + boardCol) + (8 - boardRow);
  }
  function sqToXY(sq) {
    var fi = sq.charCodeAt(0) - 97, rk = +sq[1];
    if (S.orient === "white") return { x: fi * 10 + 5, y: (8 - rk) * 10 + 5 };
    return { x: (7 - fi) * 10 + 5, y: (rk - 1) * 10 + 5 };
  }

  function renderBoard() {
    var grid = parseFEN(S.fen);
    board.innerHTML = "";
    for (var dr = 0; dr < 8; dr++) {
      for (var dc = 0; dc < 8; dc++) {
        var br = S.orient === "white" ? dr : 7 - dr;
        var bc = S.orient === "white" ? dc : 7 - dc;
        var name = sqName(br, bc);
        var cell = document.createElement("div");
        var light = (br + bc) % 2 === 0;
        cell.className = "sq";
        cell.dataset.sq = name;
        cell.style.background = light ? cvar("--sq-light") : cvar("--sq-dark");
        if (S.last && (S.last.from === name || S.last.to === name)) cell.classList.add("lastmove");
        if (S.sel === name) cell.classList.add("sel");
        var p = grid[br][bc];
        if (p) {
          var span = document.createElement("span");
          span.className = "pc " + (p === p.toUpperCase() ? "w" : "b");
          span.textContent = GLYPH[p.toLowerCase()];
          cell.appendChild(span);
        }
        // legal-move markers for the selected piece
        if (S.sel && targetsFrom(S.sel).indexOf(name) >= 0) {
          if (p) cell.classList.add("capture");
          var m = document.createElement("span"); m.className = "dotmark"; cell.appendChild(m);
        }
        if (dc === 0) { var rr = coord("rank", 8 - br, light); cell.appendChild(rr); }
        if (dr === 7) { var ff = coord("file", String.fromCharCode(97 + bc), light); cell.appendChild(ff); }
        cell.addEventListener("click", onSquareClick);
        board.appendChild(cell);
      }
    }
  }
  function coord(kind, text, light) {
    var e = document.createElement("span");
    e.className = "coord " + kind;
    e.style.color = light ? cvar("--sq-dark") : cvar("--sq-light");
    e.textContent = text;
    return e;
  }

  function targetsFrom(from) {
    var out = [];
    S.legal.forEach(function (u) { if (u.slice(0, 2) === from) out.push(u.slice(2, 4)); });
    return out;
  }

  // ---- arrows ----
  function clearArrows() { arrows.querySelectorAll("line,circle").forEach(function (n) { n.remove(); }); }
  function drawArrow(from, to, color, dashed) {
    var a = sqToXY(from), b = sqToXY(to);
    var dx = b.x - a.x, dy = b.y - a.y, len = Math.hypot(dx, dy) || 1;
    var ln = document.createElementNS("http://www.w3.org/2000/svg", "line");
    ln.setAttribute("x1", a.x + dx / len * 1.5); ln.setAttribute("y1", a.y + dy / len * 1.5);
    ln.setAttribute("x2", b.x - dx / len * 3.2); ln.setAttribute("y2", b.y - dy / len * 3.2);
    ln.setAttribute("stroke", color); ln.setAttribute("stroke-width", "1.7");
    ln.setAttribute("stroke-linecap", "round"); ln.setAttribute("opacity", "0.9");
    ln.setAttribute("marker-end", "url(#ah)");
    if (dashed) ln.setAttribute("stroke-dasharray", "3 2");
    arrows.appendChild(ln);
    var dot = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    dot.setAttribute("cx", a.x); dot.setAttribute("cy", a.y); dot.setAttribute("r", "1.5");
    dot.setAttribute("fill", color); dot.setAttribute("opacity", "0.9");
    arrows.appendChild(dot);
  }
  function renderArrows() {
    clearArrows();
    var c = S.coaching;
    if (!c) return;
    if (S.showRef && c.refuteFrom) { drawArrow(c.refuteFrom, c.refuteTo, cvar("--blunder"), false); return; }
    if (!c.isBest) drawArrow(c.bestFrom, c.bestTo, cvar("--accent"), true);
    if (c.playedFrom) drawArrow(c.playedFrom, c.playedTo, cvar(QVAR[c.quality] || "--good"), false);
  }

  // ---- panel ----
  function renderPanel() {
    var c = S.coaching;
    if (!c) { panel.innerHTML = '<p class="empty">Make a move and your coaching appears here.</p>'; return; }
    var qc = cvar(QVAR[c.quality] || "--good");
    var label = c.quality.toUpperCase() + (c.glyph ? " " + c.glyph : "");
    var ev = (c.evalAfter > 0 ? "+" : "") + c.evalAfter.toFixed(1);
    var src = c.explanationSource === "ollama" ? "LLM" : "template";
    var h = '<div class="verdict">' +
      '<span class="badge" style="background:' + qc + '">' + label + '</span>' +
      '<span class="mv">' + esc(c.label || c.san) + '</span>' +
      '<span class="evalpill">eval ' + ev + '</span></div>' +
      '<p class="why">' + esc(c.explanation) + '</p><div class="lines">';
    h += row(c.isBest ? "Line" : "Best", c.isBest ? c.bestLine.join(" ") : (c.bestSan + "  —  " + c.bestLine.join(" ")));
    if (c.refuteFrom && !c.isBest) h += row("If played", c.refuteLine.join(" "));
    h += '</div><div class="panelnote"><span class="srcpill">' + src + '</span>';
    if (S.showRef) h += " · showing the position after " + esc(c.san) + " with the reply in red";
    h += "</div>";
    panel.innerHTML = h;
    refBtn.disabled = !(c.refuteFrom && !c.isBest);
    refBtn.setAttribute("aria-pressed", S.showRef ? "true" : "false");
  }
  function row(k, v) { return '<div class="row"><span class="k">' + k + '</span><span class="v">' + esc(v) + '</span></div>'; }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }

  function renderMoves() {
    movegrid.innerHTML = "";
    S.moves.forEach(function (m) {
      var chip = document.createElement("span");
      chip.className = "mchip";
      var color = m.coaching ? cvar(QVAR[m.coaching.quality] || "--good") : cvar("--muted");
      var num = m.side === "white" ? '<span class="num">' + m.num + '.</span> ' : "";
      chip.innerHTML = '<span class="dot" style="background:' + color + '"></span>' + num + esc(m.san) + (m.coaching ? (m.coaching.glyph || "") : "");
      movegrid.appendChild(chip);
    });
  }

  function setStatus(text, alert, spin) {
    statusline.className = "statusline" + (alert ? " alert" : "");
    statusline.innerHTML = (spin ? '<span class="spin"></span> ' : "") + esc(text);
  }

  function renderAll() { renderBoard(); renderArrows(); renderPanel(); renderMoves(); }

  // ---- flow ----
  async function refreshLegal() {
    var st = await api("/api/legal", { fen: S.fen });
    S.legal = st.ucis || [];
    return st;
  }

  function pushMove(side, san, fen, num, coaching) {
    S.moves.push({ side: side, san: san, fen: fen, num: num, coaching: coaching });
  }

  async function humanMove(uci) {
    if (S.busy) return;
    S.busy = true; S.sel = null; S.showRef = false;
    setStatus("Coach is thinking…", false, true);
    try {
      var num = fullmove(S.fen);
      var side = turnOf(S.fen);
      var c = await api("/api/move", { fen: S.fen, uci: uci, useLlm: S.useLlm });
      S.fen = c.fen; S.coaching = c; S.last = { from: c.playedFrom, to: c.playedTo };
      pushMove(side, c.san, c.fen, num, c);
      renderAll();
      if (c.gameOver) { endGame(c); S.busy = false; return; }
      await engineMove();
    } catch (e) { setStatus("Error: " + e.message, true); }
    S.busy = false;
  }

  async function engineMove() {
    setStatus(S.human === "white" ? "Black is thinking…" : "White is thinking…", false, true);
    var num = fullmove(S.fen);
    var side = turnOf(S.fen);
    var r = await api("/api/engine", { fen: S.fen, level: S.level });
    S.fen = r.fen; S.last = { from: r.from, to: r.to };
    pushMove(side, r.san, r.fen, num, null);
    S.coaching = null;           // engine move is not coached
    renderArrows(); renderBoard(); renderMoves();
    // keep the human's last coaching in the panel for reference
    if (lastHumanCoaching()) { S.coaching = lastHumanCoaching(); renderPanel(); renderArrows(); }
    if (r.gameOver) { endGame(r); return; }
    await refreshLegal();
    setStatus("Your move.");
  }

  function lastHumanCoaching() {
    for (var i = S.moves.length - 1; i >= 0; i--) if (S.moves[i].coaching) return S.moves[i].coaching;
    return null;
  }

  function endGame(st) { setStatus(st.status || "Game over.", true); S.legal = []; }

  function fullmove(fen) { return parseInt(fen.split(" ")[5], 10) || 1; }

  // ---- interaction ----
  function onSquareClick(e) {
    if (S.busy) return;
    var sq = e.currentTarget.dataset.sq;
    if (S.sel) {
      if (sq === S.sel) { S.sel = null; renderBoard(); return; }
      if (targetsFrom(S.sel).indexOf(sq) >= 0) { attemptMove(S.sel, sq); return; }
    }
    // select if it's a legal source for the side to move
    if (targetsFrom(sq).length) { S.sel = sq; renderBoard(); }
    else { S.sel = null; renderBoard(); }
  }

  function attemptMove(from, to) {
    var cands = S.legal.filter(function (u) { return u.slice(0, 4) === from + to; });
    if (cands.length > 1) { showPromo(from, to, cands); return; }
    if (cands.length === 1) humanMove(cands[0]);
  }

  function showPromo(from, to, cands) {
    promo.hidden = false; promo.innerHTML = "";
    var order = ["q", "r", "b", "n"];
    order.forEach(function (pc) {
      var u = from + to + pc;
      if (cands.indexOf(u) < 0) return;
      var b = document.createElement("button");
      b.textContent = GLYPH[pc];
      b.addEventListener("click", function () { promo.hidden = true; humanMove(u); });
      promo.appendChild(b);
    });
  }

  // ---- controls ----
  async function newGame() {
    if (S.busy) return;
    S.busy = true;
    S.fen = START; S.moves = []; S.sel = null; S.last = null; S.coaching = null; S.showRef = false;
    S.human = document.getElementById("colorSel").value;
    S.level = parseInt(document.getElementById("levelSel").value, 10);
    S.orient = S.human;
    renderAll();
    setStatus("New game. " + (S.human === "white" ? "Your move." : "Engine to move…"), false, S.human === "black");
    try {
      if (S.human === "black") { await engineMove(); }
      else { await refreshLegal(); }
    } catch (e) { setStatus("Error: " + e.message, true); }
    S.busy = false;
  }

  async function undo() {
    if (S.busy || S.moves.length === 0) return;
    S.busy = true; S.showRef = false; S.sel = null;
    S.moves.pop();                                   // undo last ply
    if (S.moves.length && turnAfter() !== S.human) S.moves.pop(); // and the matching one
    S.fen = S.moves.length ? S.moves[S.moves.length - 1].fen : START;
    S.last = null;
    S.coaching = lastHumanCoaching();
    try { await refreshLegal(); } catch (e) { }
    renderAll(); setStatus("Your move.");
    S.busy = false;
  }
  function turnAfter() { return turnOf(S.fen && S.moves.length ? S.moves[S.moves.length - 1].fen : START); }

  async function hint() {
    if (S.busy) return;
    S.busy = true; S.showRef = false;
    setStatus("Finding the best move…", false, true);
    try {
      var c = await api("/api/hint", { fen: S.fen, useLlm: S.useLlm });
      c.label = "Best: " + c.bestSan;
      c.isBest = true; c.playedFrom = c.bestFrom; c.playedTo = c.bestTo; c.quality = "best";
      S.coaching = c; renderArrows(); renderPanel();
      setStatus("Hint shown — the green arrow is the engine's choice.");
    } catch (e) { setStatus("Error: " + e.message, true); }
    S.busy = false;
  }

  function flip() { S.orient = S.orient === "white" ? "black" : "white"; renderAll(); }
  function toggleRef() { if (refBtn.disabled) return; S.showRef = !S.showRef; renderArrows(); renderPanel(); }

  async function loadHealth() {
    try {
      var h = await api("/api/health", {});
      var el = document.getElementById("health");
      el.textContent = "engine " + (h.engine ? "✓" : "✗") +
        "  ·  LLM " + (h.ollama ? h.model : "off");
      if (!h.ollama) {
        var chk = document.getElementById("llmChk");
        chk.checked = false; chk.disabled = true; S.useLlm = false;
        document.getElementById("llmLabel").textContent = "Local LLM not running — using template explainer";
      }
    } catch (e) { }
  }

  // ---- wire up ----
  document.getElementById("newBtn").onclick = newGame;
  document.getElementById("undoBtn").onclick = undo;
  document.getElementById("hintBtn").onclick = hint;
  document.getElementById("flipBtn").onclick = flip;
  refBtn.onclick = toggleRef;
  document.getElementById("llmChk").onchange = function (e) { S.useLlm = e.target.checked; };
  document.getElementById("colorSel").onchange = newGame;
  document.getElementById("levelSel").onchange = function (e) { S.level = parseInt(e.target.value, 10); };

  loadHealth();
  renderAll();
  refreshLegal().then(function () { setStatus("Your move."); }).catch(function (e) { setStatus("Error: " + e.message, true); });
})();
