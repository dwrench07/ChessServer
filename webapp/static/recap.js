/* chesscoach — Match Recap
 *
 * A cinematic, shareable recap of a finished game, rendered entirely on a
 * <canvas> and (optionally) recorded to a downloadable video with the browser's
 * native MediaRecorder — no server, no ffmpeg, no libraries.
 *
 * Output format: MP4 (H.264) where the browser supports it (Chrome 130+,
 * Safari), which is what LinkedIn wants; otherwise WebM, which the UI labels so
 * the user can convert it (`ffmpeg -i recap.webm recap.mp4`).
 *
 * Exposes window.ChessRecap = { open(match), supported() }.
 *   match = {
 *     youName, oppName, oppIcon, youColor, result, resultText, won, drew,
 *     accuracy, grade, xp, level, startFen,
 *     moves: [{san, fen, from, to, side}],   // fen is AFTER the move
 *     plot: <find_plot result>               // {hasPlot, seed, strike, ...}
 *   }
 */
(function () {
  "use strict";

  var SIZE = 1080;                       // square, feed-friendly
  var FPS = 30;
  var GLYPH = { k: "♚", q: "♛", r: "♜", b: "♝", n: "♞", p: "♟" };

  // --- palette (self-contained so the recap looks identical in any theme) ----
  var C = {
    bg0: "#0f1420", bg1: "#1b2233", ink: "#eef1f6", sub: "#9aa6b8",
    sqLight: "#e9e6d6", sqDark: "#6f8f69",
    accent: "#5bb98c", good: "#4bbe7a", bad: "#e0564f", gold: "#e8b84b",
    plot: "#17a2b8",
  };

  // ---------------------------------------------------------------- utilities
  function clamp(v, a, b) { return v < a ? a : v > b ? b : v; }
  function ease(t) { return t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2; }
  function lerp(a, b, t) { return a + (b - a) * t; }

  function parseFEN(fen) {
    var rows = (fen || "").split(" ")[0].split("/");
    var grid = [];
    for (var r = 0; r < 8; r++) {
      var out = [], row = rows[r] || "8";
      for (var i = 0; i < row.length; i++) {
        var ch = row[i];
        if (/\d/.test(ch)) { for (var k = 0; k < +ch; k++) out.push(""); }
        else out.push(ch);
      }
      while (out.length < 8) out.push("");
      grid.push(out);
    }
    return grid;
  }

  // Board FEN *before* ply p (1-indexed), from the move list.
  function fenBeforePly(match, ply) {
    if (ply <= 1) return match.startFen;
    var m = match.moves[ply - 2];
    return (m && m.fen) ? m.fen : match.startFen;
  }

  function sqXY(sq, x0, y0, cell, orient) {
    var fi = sq.charCodeAt(0) - 97, rk = +sq[1];
    var col = orient === "white" ? fi : 7 - fi;
    var row = orient === "white" ? 8 - rk : rk - 1;
    return { x: x0 + col * cell + cell / 2, y: y0 + row * cell + cell / 2 };
  }

  // ------------------------------------------------------------- drawing bits
  function bg(ctx, t) {
    var g = ctx.createLinearGradient(0, 0, SIZE, SIZE);
    g.addColorStop(0, C.bg0); g.addColorStop(1, C.bg1);
    ctx.fillStyle = g; ctx.fillRect(0, 0, SIZE, SIZE);
    // subtle drifting vignette for a little life
    var cx = SIZE / 2 + Math.sin(t * 0.6) * 40, cy = SIZE * 0.42 + Math.cos(t * 0.5) * 30;
    var rg = ctx.createRadialGradient(cx, cy, 80, cx, cy, SIZE * 0.8);
    rg.addColorStop(0, "rgba(91,185,140,0.10)"); rg.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = rg; ctx.fillRect(0, 0, SIZE, SIZE);
  }

  function text(ctx, s, x, y, opts) {
    opts = opts || {};
    ctx.save();
    ctx.globalAlpha = opts.alpha == null ? 1 : opts.alpha;
    ctx.fillStyle = opts.color || C.ink;
    ctx.textAlign = opts.align || "center";
    ctx.textBaseline = opts.baseline || "middle";
    var weight = opts.weight || 600;
    var family = opts.mono ? "'JetBrains Mono',ui-monospace,monospace"
      : opts.display ? "'Fraunces',Georgia,serif"
      : "system-ui,-apple-system,'Segoe UI',Roboto,sans-serif";
    ctx.font = weight + " " + (opts.size || 40) + "px " + family;
    if (opts.spacing) {
      var cx = x, total = 0, i;
      for (i = 0; i < s.length; i++) total += ctx.measureText(s[i]).width + opts.spacing;
      cx = x - (opts.align === "center" ? total / 2 : 0);
      ctx.textAlign = "left";
      for (i = 0; i < s.length; i++) {
        ctx.fillText(s[i], cx, y);
        cx += ctx.measureText(s[i]).width + opts.spacing;
      }
    } else {
      ctx.fillText(s, x, y);
    }
    ctx.restore();
  }

  function roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  function board(ctx, fen, x0, y0, boardSize, orient, opts) {
    opts = opts || {};
    var cell = boardSize / 8, grid = parseFEN(fen);
    ctx.save();
    // frame
    ctx.shadowColor = "rgba(0,0,0,0.45)"; ctx.shadowBlur = 40; ctx.shadowOffsetY = 18;
    roundRect(ctx, x0, y0, boardSize, boardSize, 14);
    ctx.fillStyle = C.sqDark; ctx.fill();
    ctx.shadowColor = "transparent"; ctx.shadowBlur = 0; ctx.shadowOffsetY = 0;
    roundRect(ctx, x0, y0, boardSize, boardSize, 14); ctx.clip();  // keep corners rounded

    for (var dr = 0; dr < 8; dr++) for (var dc = 0; dc < 8; dc++) {
      var br = orient === "white" ? dr : 7 - dr;
      var bc = orient === "white" ? dc : 7 - dc;
      var px = x0 + dc * cell, py = y0 + dr * cell;
      ctx.fillStyle = (br + bc) % 2 === 0 ? C.sqLight : C.sqDark;
      ctx.fillRect(px, py, cell, cell);
      var sqname = String.fromCharCode(97 + bc) + (8 - br);
      if (opts.highlight && opts.highlight.indexOf(sqname) >= 0) {
        ctx.fillStyle = "rgba(232,184,75,0.45)";
        ctx.fillRect(px, py, cell, cell);
      }
      var p = grid[br][bc];
      if (p) {
        var white = p === p.toUpperCase();
        ctx.font = "400 " + (cell * 0.82) + "px 'JetBrains Mono',serif";
        ctx.textAlign = "center"; ctx.textBaseline = "middle";
        var cx = px + cell / 2, cy = py + cell / 2 + cell * 0.03;
        ctx.lineWidth = Math.max(2, cell * 0.04);
        ctx.strokeStyle = white ? "rgba(20,20,20,0.9)" : "rgba(10,10,10,0.9)";
        ctx.fillStyle = white ? "#fbfbf7" : "#2a2a2a";
        var gl = GLYPH[p.toLowerCase()];
        ctx.strokeText(gl, cx, cy); ctx.fillText(gl, cx, cy);
      }
    }
    // clip rounded corners back over the square overspill
    ctx.restore();

    // optional arrow overlay
    if (opts.arrows) {
      opts.arrows.forEach(function (a) {
        drawArrow(ctx, sqXY(a.from, x0, y0, cell, orient), sqXY(a.to, x0, y0, cell, orient),
          a.color, a.width || cell * 0.16, a.alpha == null ? 1 : a.alpha, a.dashed);
      });
    }
    if (opts.dots) {
      opts.dots.forEach(function (d) {
        var p = sqXY(d.sq, x0, y0, cell, orient);
        ctx.save(); ctx.globalAlpha = d.alpha == null ? 1 : d.alpha;
        ctx.fillStyle = d.color; ctx.beginPath();
        ctx.arc(p.x, p.y, cell * (d.r || 0.22), 0, Math.PI * 2); ctx.fill();
        ctx.restore();
      });
    }
  }

  function drawArrow(ctx, p, q, color, width, alpha, dashed) {
    var dx = q.x - p.x, dy = q.y - p.y, len = Math.hypot(dx, dy) || 1;
    var ux = dx / len, uy = dy / len;
    var head = width * 2.2;
    var ex = q.x - ux * head, ey = q.y - uy * head;
    ctx.save();
    ctx.globalAlpha = alpha; ctx.strokeStyle = color; ctx.fillStyle = color;
    ctx.lineWidth = width; ctx.lineCap = "round";
    if (dashed) ctx.setLineDash([width * 1.4, width * 1.1]);
    ctx.beginPath(); ctx.moveTo(p.x + ux * width, p.y + uy * width); ctx.lineTo(ex, ey); ctx.stroke();
    ctx.setLineDash([]);
    var px = -uy, py = ux;
    ctx.beginPath();
    ctx.moveTo(q.x, q.y);
    ctx.lineTo(ex + px * head * 0.6, ey + py * head * 0.6);
    ctx.lineTo(ex - px * head * 0.6, ey - py * head * 0.6);
    ctx.closePath(); ctx.fill();
    ctx.restore();
  }

  // ------------------------------------------------------------- confetti
  function makeConfetti(n) {
    var parts = [];
    var cols = [C.accent, C.gold, C.good, C.plot, "#e07b2e"];
    for (var i = 0; i < n; i++) {
      parts.push({
        x: Math.random() * SIZE, y: -Math.random() * SIZE * 0.4,
        vx: (Math.random() - 0.5) * 140, vy: 140 + Math.random() * 220,
        s: 10 + Math.random() * 16, rot: Math.random() * 6.28,
        vr: (Math.random() - 0.5) * 8, col: cols[i % cols.length],
      });
    }
    return parts;
  }
  function drawConfetti(ctx, parts, t) {
    parts.forEach(function (p) {
      var y = p.y + p.vy * t, x = p.x + p.vx * t, rot = p.rot + p.vr * t;
      ctx.save(); ctx.translate(x, y); ctx.rotate(rot);
      ctx.fillStyle = p.col; ctx.fillRect(-p.s / 2, -p.s / 2, p.s, p.s * 0.6);
      ctx.restore();
    });
  }

  // ------------------------------------------------------------- scene build
  function buildScenes(match) {
    var scenes = [];
    var orient = match.youColor || "white";

    // The replay uses the last few plies so the clip stays punchy.
    var all = match.moves || [];
    var replayCount = Math.min(all.length, 12);
    var replayStart = all.length - replayCount; // index into all
    var perMove = 0.42;

    // --- 1. INTRO ---------------------------------------------------------
    scenes.push({
      dur: 2.6,
      draw: function (ctx, t) {
        bg(ctx, t);
        var a1 = clamp(t / 0.5, 0, 1);
        text(ctx, "chesscoach", SIZE / 2, SIZE * 0.30, { size: 46, color: C.accent, display: true, alpha: a1 });
        var a2 = clamp((t - 0.4) / 0.5, 0, 1);
        text(ctx, "MATCH RECAP", SIZE / 2, SIZE * 0.42, { size: 86, display: true, alpha: a2, spacing: 6 });
        var a3 = clamp((t - 1.0) / 0.6, 0, 1);
        var vs = match.youName + "  vs  " + (match.oppIcon ? match.oppIcon + " " : "") + match.oppName;
        text(ctx, vs, SIZE / 2, SIZE * 0.56, { size: 40, color: C.sub, alpha: a3 });
        // result badge slides up
        var a4 = clamp((t - 1.5) / 0.6, 0, 1);
        var by = lerp(SIZE * 0.78, SIZE * 0.70, ease(a4));
        var col = match.won ? C.good : (match.drew ? C.gold : C.bad);
        ctx.save(); ctx.globalAlpha = a4;
        var w = 420, h = 110, x = SIZE / 2 - w / 2;
        roundRect(ctx, x, by, w, h, 18); ctx.fillStyle = "rgba(255,255,255,0.04)"; ctx.fill();
        ctx.lineWidth = 3; ctx.strokeStyle = col; ctx.stroke(); ctx.restore();
        text(ctx, match.resultText, SIZE / 2, by + h / 2, { size: 52, display: true, color: col, alpha: a4 });
      },
    });

    // --- 2. REPLAY --------------------------------------------------------
    scenes.push({
      dur: Math.max(3.2, replayCount * perMove + 0.8),
      draw: function (ctx, t) {
        bg(ctx, t);
        var bs = SIZE * 0.70, x0 = (SIZE - bs) / 2, y0 = SIZE * 0.12;
        // which ply are we showing
        var idx = clamp(Math.floor(t / perMove), 0, replayCount - 1);
        var gi = replayStart + idx;
        var mv = all[gi];
        var fen = mv ? mv.fen : (all.length ? all[all.length - 1].fen : match.startFen);
        var hl = mv && mv.from ? [mv.from, mv.to] : [];
        board(ctx, fen, x0, y0, bs, orient, { highlight: hl });
        text(ctx, "THE GAME", SIZE / 2, y0 - SIZE * 0.045, { size: 30, color: C.sub, spacing: 4 });
        // move caption
        if (mv) {
          var num = mv.num || Math.floor(gi / 2) + 1;
          var label = num + (mv.side === "white" ? ". " : "... ") + mv.san;
          text(ctx, label, SIZE / 2, y0 + bs + SIZE * 0.06, { size: 44, mono: true, weight: 700 });
        }
        // progress ticks
        var ty = y0 + bs + SIZE * 0.11, tw = bs, tx = x0;
        for (var i = 0; i < replayCount; i++) {
          ctx.fillStyle = i <= idx ? C.accent : "rgba(255,255,255,0.14)";
          var seg = tw / replayCount;
          ctx.fillRect(tx + i * seg + 2, ty, seg - 4, 6);
        }
      },
    });

    // --- 3. THE PLOT (only when there is one) -----------------------------
    if (match.plot && match.plot.hasPlot) {
      var pl = match.plot;
      var strikeFen = fenBeforePly(match, pl.strike.ply);
      scenes.push({
        dur: 4.0,
        draw: function (ctx, t) {
          bg(ctx, t);
          var bs = SIZE * 0.60, x0 = (SIZE - bs) / 2, y0 = SIZE * 0.14;
          var seedA = clamp((t - 0.5) / 0.8, 0, 1);
          var strikeA = clamp((t - 1.8) / 0.7, 0, 1);
          var dots = [], arrows = [];
          if (pl.seed) dots.push({ sq: pl.seed.to, color: C.plot, alpha: seedA * (0.6 + 0.4 * Math.sin(t * 6)), r: 0.26 });
          if (strikeA > 0 && pl.strike) arrows.push({ from: pl.strike.from, to: pl.strike.to, color: match.won ? C.good : C.bad, alpha: strikeA });
          board(ctx, strikeFen, x0, y0, bs, orient, { dots: dots, arrows: arrows });
          text(ctx, "💭  THE PLOT", SIZE / 2, y0 - SIZE * 0.05, { size: 40, display: true, color: C.plot });
          // three-act caption
          if (pl.seed) text(ctx, "Act 1 — the seed: move " + pl.seed.moveNumber + ", " + pl.seed.san,
            SIZE / 2, y0 + bs + SIZE * 0.055, { size: 32, color: C.sub, alpha: seedA });
          text(ctx, "Act 3 — the strike: move " + pl.strike.moveNumber + ", " + pl.strike.san,
            SIZE / 2, y0 + bs + SIZE * 0.10, { size: 34, color: match.won ? C.good : C.bad, alpha: strikeA, weight: 700 });
        },
      });
    }

    // --- 4. STATS ---------------------------------------------------------
    var confetti = match.won ? makeConfetti(140) : null;
    scenes.push({
      dur: 3.2,
      draw: function (ctx, t) {
        bg(ctx, t);
        text(ctx, "THE VERDICT", SIZE / 2, SIZE * 0.14, { size: 32, color: C.sub, spacing: 4 });
        // grade stamp (scales in)
        var gA = clamp(t / 0.5, 0, 1);
        var scale = lerp(1.6, 1, ease(gA));
        var gcol = ({ A: C.good, B: C.accent, C: C.gold, D: "#e07b2e", E: C.bad })[(match.grade || "E")[0]] || C.bad;
        ctx.save(); ctx.globalAlpha = gA;
        ctx.translate(SIZE / 2, SIZE * 0.34); ctx.scale(scale, scale);
        ctx.lineWidth = 7; ctx.strokeStyle = gcol;
        ctx.beginPath(); ctx.arc(0, 0, 130, 0, Math.PI * 2); ctx.stroke();
        text(ctx, match.grade || "—", 0, 6, { size: 150, display: true, color: gcol });
        ctx.restore();
        text(ctx, "GRADE", SIZE / 2, SIZE * 0.50, { size: 28, color: C.sub, spacing: 4, alpha: gA });

        // count-up accuracy + XP row
        var rowA = clamp((t - 0.6) / 0.6, 0, 1);
        var accVal = match.accuracy == null ? null : Math.round(match.accuracy * clamp((t - 0.6) / 1.2, 0, 1));
        var cells = [
          { b: accVal == null ? "—" : accVal + "%", s: "accuracy" },
          { b: "+" + (match.xp || 0), s: "XP earned" },
          { b: "Lvl " + (match.level || 1), s: "level" },
        ];
        var cw = 300, gap = 24, total = cells.length * cw + (cells.length - 1) * gap;
        var sx = SIZE / 2 - total / 2, sy = SIZE * 0.60;
        cells.forEach(function (c, i) {
          var x = sx + i * (cw + gap);
          ctx.save(); ctx.globalAlpha = rowA;
          roundRect(ctx, x, sy, cw, 150, 16); ctx.fillStyle = "rgba(255,255,255,0.05)"; ctx.fill();
          ctx.restore();
          text(ctx, c.b, x + cw / 2, sy + 62, { size: 60, mono: true, weight: 700, alpha: rowA });
          text(ctx, c.s, x + cw / 2, sy + 118, { size: 28, color: C.sub, alpha: rowA });
        });

        if (confetti) drawConfetti(ctx, confetti, t);
      },
    });

    // --- 5. OUTRO ---------------------------------------------------------
    scenes.push({
      dur: 2.0,
      draw: function (ctx, t) {
        bg(ctx, t);
        var a = clamp(t / 0.6, 0, 1);
        text(ctx, "chesscoach", SIZE / 2, SIZE * 0.44, { size: 72, color: C.accent, display: true, alpha: a });
        text(ctx, "the engine thinks — the coach talks", SIZE / 2, SIZE * 0.54,
          { size: 34, color: C.sub, alpha: clamp((t - 0.4) / 0.6, 0, 1) });
      },
    });

    return scenes;
  }

  // ------------------------------------------------------------- player
  function totalDur(scenes) { return scenes.reduce(function (s, sc) { return s + sc.dur; }, 0); }

  function drawAt(ctx, scenes, time) {
    var acc = 0;
    for (var i = 0; i < scenes.length; i++) {
      if (time < acc + scenes[i].dur || i === scenes.length - 1) {
        scenes[i].draw(ctx, time - acc);
        return;
      }
      acc += scenes[i].dur;
    }
  }

  function animate(ctx, scenes, onDone, onProgress) {
    var total = totalDur(scenes), start = null, raf;
    function frame(ts) {
      if (start == null) start = ts;
      var t = (ts - start) / 1000;
      drawAt(ctx, scenes, Math.min(t, total - 0.001));
      if (onProgress) onProgress(clamp(t / total, 0, 1));
      if (t < total) { raf = requestAnimationFrame(frame); }
      else if (onDone) onDone();
    }
    raf = requestAnimationFrame(frame);
    return function cancel() { cancelAnimationFrame(raf); };
  }

  // ------------------------------------------------------------- recording
  function pickMime() {
    if (typeof MediaRecorder === "undefined" || !MediaRecorder.isTypeSupported) return "";
    var cands = ["video/mp4;codecs=avc1.640028", "video/mp4",
      "video/webm;codecs=vp9", "video/webm;codecs=vp8", "video/webm"];
    for (var i = 0; i < cands.length; i++) if (MediaRecorder.isTypeSupported(cands[i])) return cands[i];
    return "";
  }

  function supported() {
    return typeof MediaRecorder !== "undefined" &&
      !!HTMLCanvasElement.prototype.captureStream && !!pickMime();
  }

  // ------------------------------------------------------------- overlay UI
  function open(match) {
    var scenes = buildScenes(match);

    var ov = document.createElement("div");
    ov.className = "recap-ov";
    ov.innerHTML =
      '<div class="recap-box">' +
      '  <canvas class="recap-canvas" width="' + SIZE + '" height="' + SIZE + '"></canvas>' +
      '  <div class="recap-bar"><div class="recap-fill"></div></div>' +
      '  <div class="recap-ctrls">' +
      '    <button class="ctl" data-act="replay">▶ Replay</button>' +
      '    <button class="ctl primary" data-act="download">⬇ Download video</button>' +
      '    <button class="ctl" data-act="close">Close</button>' +
      '  </div>' +
      '  <div class="recap-note"></div>' +
      '</div>';
    document.body.appendChild(ov);

    var canvas = ov.querySelector(".recap-canvas");
    var ctx = canvas.getContext("2d");
    var fill = ov.querySelector(".recap-fill");
    var note = ov.querySelector(".recap-note");
    var dlBtn = ov.querySelector('[data-act="download"]');
    var cancelAnim = null, recording = false;

    function setProgress(p) { fill.style.width = (p * 100).toFixed(1) + "%"; }

    function play(onDone) {
      if (cancelAnim) cancelAnim();
      cancelAnim = animate(ctx, scenes, function () { if (onDone) onDone(); }, setProgress);
    }

    function download() {
      if (recording) return;
      var mime = pickMime();
      if (!mime) { note.textContent = "This browser can't record video. Try Chrome or Edge."; return; }
      var isMp4 = mime.indexOf("mp4") >= 0;
      var stream, rec;
      try {
        stream = canvas.captureStream(FPS);
        rec = new MediaRecorder(stream, { mimeType: mime, videoBitsPerSecond: 8000000 });
      } catch (e) { note.textContent = "Recording failed to start: " + e.message; return; }

      var chunks = [];
      rec.ondataavailable = function (e) { if (e.data && e.data.size) chunks.push(e.data); };
      rec.onstop = function () {
        var blob = new Blob(chunks, { type: mime.split(";")[0] });
        var ext = isMp4 ? "mp4" : "webm";
        var a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = "chesscoach-recap." + ext;
        document.body.appendChild(a); a.click(); a.remove();
        setTimeout(function () { URL.revokeObjectURL(a.href); }, 4000);
        recording = false; dlBtn.disabled = false; dlBtn.textContent = "⬇ Download video";
        note.innerHTML = isMp4
          ? "Saved <b>chesscoach-recap.mp4</b> — ready to upload to LinkedIn."
          : "Saved <b>chesscoach-recap.webm</b>. LinkedIn prefers MP4 — convert with " +
            "<code>ffmpeg -i chesscoach-recap.webm chesscoach-recap.mp4</code>.";
      };

      recording = true; dlBtn.disabled = true; dlBtn.textContent = "● Recording…";
      note.textContent = "Recording the recap in real time… keep this tab in front.";
      rec.start();
      play(function () { setTimeout(function () { if (rec.state !== "inactive") rec.stop(); }, 120); });
    }

    ov.addEventListener("click", function (e) {
      var act = e.target && e.target.getAttribute && e.target.getAttribute("data-act");
      if (act === "close" || e.target === ov) { if (cancelAnim) cancelAnim(); ov.remove(); }
      else if (act === "replay") { note.textContent = ""; play(); }
      else if (act === "download") { download(); }
    });

    if (!supported()) {
      dlBtn.disabled = true;
      note.innerHTML = "Your browser can't record video here — you can still <b>Replay</b> the recap. " +
        "For a downloadable MP4, open chesscoach in Chrome or Edge.";
    }

    play();  // auto-play once on open
  }

  window.ChessRecap = { open: open, supported: supported };
})();
