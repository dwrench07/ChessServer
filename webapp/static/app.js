"use strict";
(function () {
  var START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";
  var GLYPH = { k: "♚", q: "♛", r: "♜", b: "♝", n: "♞", p: "♟" };
  var QVAR = { best: "--best", good: "--good", excellent: "--excellent", inaccuracy: "--inaccuracy",
    mistake: "--mistake", blunder: "--blunder", brilliant: "--brilliant" };
  var TAGLABEL = { hangs_piece: "Hanging pieces", allows_mate: "Allowed mate", refuted: "Lost material",
    fork: "Walked into forks", gives_check: "Checks", captures: "Captures" };

  function cvar(n){ return getComputedStyle(document.documentElement).getPropertyValue(n).trim(); }
  function turnOf(fen){ return fen.split(" ")[1] === "w" ? "white" : "black"; }
  function esc(s){ return String(s).replace(/[&<>"]/g, function(c){ return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]; }); }
  function winPercent(cp){ cp = Math.max(-2000, Math.min(2000, cp)); return 50 + 50 * (2/(1+Math.exp(-0.00368208*cp)) - 1); }
  function moveAcc(cpLoss, evalCp){ var wb=winPercent(evalCp+cpLoss), wa=winPercent(evalCp);
    return Math.max(0, Math.min(100, 103.1668*Math.exp(-0.04354*Math.max(0,wb-wa))-3.1669)); }

  async function api(path, body){
    var res = await fetch(path, { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(body||{}) });
    var data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || ("HTTP "+res.status));
    return data;
  }

  // ---------- shared board rendering ----------
  function parseFEN(fen){
    var rows = fen.split(" ")[0].split("/"), grid=[];
    for (var r=0;r<8;r++){ var row=[],ch=rows[r];
      for (var c=0;c<ch.length;c++){ var x=ch[c]; if(/\d/.test(x)){var n=+x;while(n--)row.push(null);} else row.push(x);} grid.push(row);}
    return grid;
  }
  function sqName(br,bc){ return String.fromCharCode(97+bc)+(8-br); }
  function sqToXY(sq, orient){
    var fi=sq.charCodeAt(0)-97, rk=+sq[1];
    if (orient==="white") return { x:fi*10+5, y:(8-rk)*10+5 };
    return { x:(7-fi)*10+5, y:(rk-1)*10+5 };
  }
  function drawBoard(boardEl, fen, orient, opts){
    opts = opts || {};
    var grid = parseFEN(fen);
    boardEl.innerHTML = "";
    for (var dr=0;dr<8;dr++) for (var dc=0;dc<8;dc++){
      var br = orient==="white"?dr:7-dr, bc = orient==="white"?dc:7-dc;
      var name = sqName(br,bc);
      var cell = document.createElement("div");
      var light = (br+bc)%2===0;
      cell.className = "sq"; cell.dataset.sq = name;
      cell.style.background = light ? cvar("--sq-light") : cvar("--sq-dark");
      if (opts.last && (opts.last.from===name || opts.last.to===name)) cell.classList.add("lastmove");
      if (opts.sel === name) cell.classList.add("sel");
      if (opts.warnGlow && opts.warnGlow.indexOf(name)>=0) cell.classList.add("glow-warn");
      if (opts.goodGlow && opts.goodGlow.indexOf(name)>=0) cell.classList.add("glow-good");
      var p = grid[br][bc];
      if (p){ var span=document.createElement("span"); span.className="pc "+(p===p.toUpperCase()?"w":"b");
        span.textContent=GLYPH[p.toLowerCase()]; cell.appendChild(span); }
      if (opts.targets && opts.targets.indexOf(name)>=0){ if(p) cell.classList.add("capture");
        var m=document.createElement("span"); m.className="dotmark"; cell.appendChild(m); }
      if (dc===0){ var rr=mkcoord("rank",8-br,light); cell.appendChild(rr); }
      if (dr===7){ var ff=mkcoord("file",String.fromCharCode(97+bc),light); cell.appendChild(ff); }
      if (opts.onClick) cell.addEventListener("click", opts.onClick);
      boardEl.appendChild(cell);
    }
  }
  function mkcoord(kind,text,light){ var e=document.createElement("span"); e.className="coord "+kind;
    e.style.color = light?cvar("--sq-dark"):cvar("--sq-light"); e.textContent=text; return e; }
  function drawArrows(svgEl, orient, list){
    svgEl.querySelectorAll("line,circle").forEach(function(n){n.remove();});
    var mk = svgEl.querySelector("marker").id;
    list.forEach(function(a){
      var p=sqToXY(a.from,orient), q=sqToXY(a.to,orient);
      var dx=q.x-p.x, dy=q.y-p.y, len=Math.hypot(dx,dy)||1;
      var ln=document.createElementNS("http://www.w3.org/2000/svg","line");
      ln.setAttribute("x1",p.x+dx/len*1.5); ln.setAttribute("y1",p.y+dy/len*1.5);
      ln.setAttribute("x2",q.x-dx/len*3.2); ln.setAttribute("y2",q.y-dy/len*3.2);
      ln.setAttribute("stroke",a.color); ln.setAttribute("stroke-width","1.7");
      ln.setAttribute("stroke-linecap","round"); ln.setAttribute("opacity","0.9");
      ln.setAttribute("marker-end","url(#"+mk+")");
      if (a.dashed) ln.setAttribute("stroke-dasharray","3 2");
      svgEl.appendChild(ln);
      var dot=document.createElementNS("http://www.w3.org/2000/svg","circle");
      dot.setAttribute("cx",p.x); dot.setAttribute("cy",p.y); dot.setAttribute("r","1.5");
      dot.setAttribute("fill",a.color); dot.setAttribute("opacity","0.9"); svgEl.appendChild(dot);
    });
  }
  function coachArrows(c, showRef){
    var out=[];
    if (showRef && c.refuteFrom){ out.push({from:c.refuteFrom,to:c.refuteTo,color:cvar("--blunder")}); return out; }
    if (!c.isBest && c.bestFrom) out.push({from:c.bestFrom,to:c.bestTo,color:cvar("--accent"),dashed:true});
    if (c.playedFrom) out.push({from:c.playedFrom,to:c.playedTo,color:cvar(QVAR[c.quality]||"--good")});
    return out;
  }
  function panelHTML(c, showRef){
    var qc=cvar(QVAR[c.quality]||"--good");
    var label=c.quality.toUpperCase()+(c.glyph?" "+c.glyph:"");
    var ev=(c.evalAfter>0?"+":"")+Number(c.evalAfter).toFixed(1);
    var src=c.explanationSource==="ollama"?"LLM":"template";
    var h='<div class="verdict"><span class="badge" style="background:'+qc+'">'+label+'</span>'+
      '<span class="mv">'+esc(c.label||c.san)+'</span><span class="evalpill">eval '+ev+'</span></div>'+
      '<p class="why">'+esc(c.explanation)+'</p><div class="lines">';
    h+=lineRow(c.isBest?"Line":"Best", c.isBest?c.bestLine.join(" "):(c.bestSan+"  —  "+c.bestLine.join(" ")));
    if (c.refuteFrom && !c.isBest) h+=lineRow("If played", c.refuteLine.join(" "));
    h+='</div>';
    if (c.recurring) h+='<div class="recurring">↻ '+esc(c.recurring.text)+'</div>';
    h+='<div class="panelnote"><span class="srcpill">'+src+'</span>';
    if (showRef) h+=" · showing the reply to "+esc(c.san)+" in red";
    h+="</div>";
    return h;
  }
  function lineRow(k,v){ return '<div class="row"><span class="k">'+k+'</span><span class="v">'+esc(v)+'</span></div>'; }

  // ================= PLAY =================
  var P = { fen:START, orient:"white", human:"white", level:3, useLlm:true,
    moves:[], legal:[], sel:null, last:null, coaching:null, showRef:false, busy:false,
    humanAccs:[], evalWhiteCp:0, saved:false, plan:null, arrows:[], analogy:false,
    showGlow:true, hanging:[], targets:[], streak:0, prevYourWin:50 };
  var el = function(id){ return document.getElementById(id); };
  var pboard=el("board"), parrows=el("arrows"), ppanel=el("panel"),
      pstatus=el("statusline"), pmoves=el("movegrid"), promo=el("promo"), refBtn=el("refBtn");

  function pTargets(from){ var o=[]; P.legal.forEach(function(u){ if(u.slice(0,2)===from)o.push(u.slice(2,4)); }); return o; }
  function renderPlay(){
    drawBoard(pboard, P.fen, P.orient, { sel:P.sel, last:P.last,
      targets: P.sel?pTargets(P.sel):null, onClick:onSquareClick,
      warnGlow: P.showGlow?P.hanging:[], goodGlow: P.showGlow?P.targets:[] });
    drawArrows(parrows, P.orient, P.arrows || []);
    renderPanel(); renderMoves(); renderEval(); renderAcc(); renderWin();
  }

  // ---- real-time juice ----
  function reduceMotion(){ try{ return matchMedia("(prefers-reduced-motion:reduce)").matches; }catch(e){ return false; } }
  var fx=el("fx"), fxCtx=null, parts=[], rafId=null;
  function fxResize(){ var w=el("boardWrap").clientWidth||440; if(fx.width!==w){ fx.width=w; fx.height=w; } }
  function burst(cx,cy,colors,n){
    if (reduceMotion()) return; fxResize();
    for(var i=0;i<n;i++){ var a=Math.random()*6.283, sp=1+Math.random()*3.2;
      parts.push({x:cx,y:cy,vx:Math.cos(a)*sp,vy:Math.sin(a)*sp-1.4,life:1,
        color:colors[i%colors.length],r:2+Math.random()*2.5}); }
    if(!rafId) rafId=requestAnimationFrame(fxTick);
  }
  function fxTick(){
    fxCtx=fxCtx||fx.getContext("2d"); fxCtx.clearRect(0,0,fx.width,fx.height);
    parts=parts.filter(function(p){ return p.life>0; });
    parts.forEach(function(p){ p.x+=p.vx; p.y+=p.vy; p.vy+=0.14; p.life-=0.024;
      fxCtx.globalAlpha=Math.max(0,p.life); fxCtx.fillStyle=p.color;
      fxCtx.beginPath(); fxCtx.arc(p.x,p.y,p.r,0,6.283); fxCtx.fill(); });
    fxCtx.globalAlpha=1;
    if(parts.length) rafId=requestAnimationFrame(fxTick);
    else { rafId=null; fxCtx.clearRect(0,0,fx.width,fx.height); }
  }
  function sqPixel(sq){ var pt=sqToXY(sq,P.orient); var w=fx.width||440; return {x:pt.x/80*w,y:pt.y/80*w}; }
  function captureFx(toSq){
    var cell=pboard.querySelector('[data-sq="'+toSq+'"]');
    if(cell && !reduceMotion()){ cell.classList.add("capflash"); setTimeout(function(){ cell.classList.remove("capflash"); },460); }
    fxResize(); var px=sqPixel(toSq); burst(px.x,px.y,[cvar("--brilliant"),cvar("--mistake"),cvar("--best")],14);
  }
  function confetti(){ fxResize(); burst(fx.width/2, fx.height*0.3,
    [cvar("--brilliant"),cvar("--best"),cvar("--good"),cvar("--inaccuracy")], 42); }
  function momentum(delta){
    if(reduceMotion() || Math.abs(delta)<2) return;
    var m=el("momentum"); m.hidden=false; m.className="momentum "+(delta>0?"up":"down");
    m.textContent=(delta>0?"+":"")+Math.round(delta)+"%";
    m.style.animation="none"; void m.offsetWidth; m.style.animation="";
    clearTimeout(m._t); m._t=setTimeout(function(){ m.hidden=true; },1300);
  }
  function renderWin(){
    var w=el("winpct");
    if(!P.moves.length && !P.coaching){ w.hidden=true; return; }
    var yc = P.human==="white" ? P.evalWhiteCp : -P.evalWhiteCp;
    var you = Math.max(1, Math.min(99, winPercent(yc)));
    w.hidden=false;
    w.innerHTML='<span class="wyou">You '+you.toFixed(0)+'%</span>'+
      '<span class="wbar"><span class="wfill" style="width:'+you.toFixed(0)+'%"></span></span>'+
      '<span>Engine '+(100-you).toFixed(0)+'%</span>'+
      (P.streak>=3?' <span class="streak">🔥 '+P.streak+' in a row</span>':'');
  }
  function renderPanel(){
    if (P.plan){ ppanel.innerHTML = planHTML(P.plan) + analogyHTML(P.plan.conceptKey); refBtn.disabled=true; return; }
    if (!P.coaching){ ppanel.innerHTML='<p class="empty">Make a move and your coaching appears here.</p>';
      refBtn.disabled=true; return; }
    ppanel.innerHTML = panelHTML(P.coaching, P.showRef) + analogyHTML(P.coaching.conceptKey);
    refBtn.disabled = !(P.coaching.refuteFrom && !P.coaching.isBest);
    refBtn.setAttribute("aria-pressed", P.showRef?"true":"false");
  }
  var CONCEPTS = {};
  function analogyHTML(key){
    if (!P.analogy || !key || !CONCEPTS[key]) return "";
    return '<div class="analogy">⚔ '+esc(CONCEPTS[key].analogy)+'</div>';
  }
  async function loadConcepts(){
    try{ var d=await api("/api/concepts",{});
      (d.concepts||[]).forEach(function(c){ CONCEPTS[c.key]=c; });
      var grid=el("conceptGrid"); if(!grid) return; grid.innerHTML="";
      (d.concepts||[]).forEach(function(c){
        var card=document.createElement("div"); card.className="ccard";
        card.innerHTML='<h3>'+esc(c.title)+'</h3><p class="def">'+esc(c.definition)+'</p>'+
          '<p class="ana">⚔ '+esc(c.analogy)+'</p>';
        grid.appendChild(card);
      });
    }catch(e){}
  }
  function planHTML(d){
    var h='<div class="verdict"><span class="badge" style="background:var(--accent)">PLAN · '+esc(d.phase)+'</span>'+
      '<span class="mv">think ahead</span></div>'+
      '<p class="why">'+esc(d.text)+'</p><div class="planlist">';
    if (d.yourPlan && d.yourPlan.length) h+=planRow("Your plan", d.yourPlan.join("; "));
    if (d.pawnBreaks && d.pawnBreaks.length) h+=planRow("Breaks", d.pawnBreaks.join(", "));
    if (d.opponentPlan && d.opponentPlan.length) h+=planRow("Watch for", d.opponentPlan.join("; "));
    h+='</div><div class="panelnote"><span class="srcpill">'+(d.source==="ollama"?"LLM":"template")+
      '</span> · the dashed arrow is the engine\'s move toward this plan</div>';
    return h;
  }
  function planRow(k,v){ return '<div class="pl"><b>'+k+'</b><span>'+esc(v)+'</span></div>'; }
  function renderMoves(){
    pmoves.innerHTML="";
    P.moves.forEach(function(m){
      var chip=document.createElement("span"); chip.className="mchip";
      var color=m.coaching?cvar(QVAR[m.coaching.quality]||"--good"):cvar("--muted");
      var num=m.side==="white"?'<span class="num">'+m.num+'.</span> ':"";
      chip.innerHTML='<span class="dot" style="background:'+color+'"></span>'+num+esc(m.san)+(m.coaching?(m.coaching.glyph||""):"");
      pmoves.appendChild(chip);
    });
  }
  function renderEval(){
    var pct=Math.max(2, Math.min(98, winPercent(P.evalWhiteCp)));
    el("evalfill").style.height=pct+"%";
  }
  function renderAcc(){
    if (!P.humanAccs.length){ el("accNow").textContent=""; return; }
    var avg=P.humanAccs.reduce(function(a,b){return a+b;},0)/P.humanAccs.length;
    el("accNow").innerHTML='<i style="border-color:var(--muted)"></i>your accuracy '+avg.toFixed(0)+"%";
  }
  function setStatus(t,alert,spin){ pstatus.className="statusline"+(alert?" alert":"");
    pstatus.innerHTML=(spin?'<span class="spin"></span> ':"")+esc(t); }
  function renderPulse(pulse){
    var b=el("pulseBar");
    if(!pulse){ b.hidden=true; return; }
    b.hidden=false; b.className="pulsebar sharp-"+pulse.sharpness;
    var label = pulse.sharpness==="sharp"?"⚡ Sharp position"
              : pulse.sharpness==="tense"?"Tense position":"Quiet — play on principle";
    var extra = pulse.critical?(" · "+pulse.criticalText):"";
    b.textContent=label+extra;
  }

  async function refreshLegal(){ var st=await api("/api/legal",{fen:P.fen});
    P.legal=st.ucis||[]; P.hanging=st.hanging||[]; P.targets=st.targets||[]; return st; }
  function pushMove(side,san,uci,fen,num,coaching){ P.moves.push({side:side,san:san,uci:uci,fen:fen,num:num,coaching:coaching}); }
  function fullmove(fen){ return parseInt(fen.split(" ")[5],10)||1; }

  async function humanMove(uci){
    if (P.busy) return; P.busy=true; P.sel=null; P.showRef=false; P.plan=null;
    el("pulseBar").hidden=true;
    setStatus("Coach is thinking…",false,true);
    try{
      var num=fullmove(P.fen), side=turnOf(P.fen);
      var c=await api("/api/move",{fen:P.fen,uci:uci,useLlm:P.useLlm});
      P.fen=c.fen; P.coaching=c; P.last={from:c.playedFrom,to:c.playedTo};
      P.arrows=coachArrows(c,false);
      P.evalWhiteCp = side==="white"? c.evalCp : -c.evalCp;
      if (c.cpLoss!=null && c.evalCp!=null) P.humanAccs.push(moveAcc(c.cpLoss,c.evalCp));
      // juice: momentum swing, streak, confetti, capture burst
      var yourWin = winPercent(c.evalCp);          // c.evalCp is from your POV
      momentum(yourWin - P.prevYourWin); P.prevYourWin = yourWin;
      P.streak = (["best","excellent","good","brilliant"].indexOf(c.quality)>=0) ? P.streak+1 : 0;
      if (c.quality==="brilliant") confetti();
      if (c.san.indexOf("x")>=0) captureFx(c.playedTo);
      pushMove(side,c.san,uci,c.fen,num,c);
      renderPlay();
      if (c.gameOver){ await endGame(c); P.busy=false; return; }
      await engineMove();
    }catch(e){ setStatus("Error: "+e.message,true); }
    P.busy=false;
  }
  async function engineMove(){
    setStatus((P.human==="white"?"Black":"White")+" is thinking…",false,true);
    var num=fullmove(P.fen), side=turnOf(P.fen);
    var r=await api("/api/engine",{fen:P.fen,level:P.level});
    P.fen=r.fen; P.last={from:r.from,to:r.to}; P.arrows=[];
    pushMove(side,r.san,r.from+r.to,r.fen,num,null);
    renderPlay();
    if (r.san.indexOf("x")>=0) captureFx(r.to);
    if (r.gameOver){ await endGame(r); return; }
    await refreshLegal();
    // Threat radar + pulse: warn about the opponent's threat and read the
    // position's sharpness / whether you have a tactic.
    try{
      var t=await api("/api/threat",{fen:P.fen});
      renderPulse(t.pulse);
      if (t.threat){ P.arrows=[{from:t.threat.from,to:t.threat.to,color:cvar("--blunder")}];
        drawArrows(parrows,P.orient,P.arrows); setStatus("⚠ "+t.threat.text+" Your move."); return; }
      if (t.pulse && t.pulse.tactic){ setStatus(t.pulse.tacticText+" Your move."); return; }
    }catch(e){}
    setStatus("Your move.");
  }
  async function endGame(st){
    setStatus(st.status||"Game over.",true); P.legal=[];
    if (!P.saved){ P.saved=true; await saveGame(st.status); }
  }
  function resultFrom(status){
    if (!status) return "*";
    if (/white wins/i.test(status)) return "1-0";
    if (/black wins/i.test(status)) return "0-1";
    if (/draw/i.test(status)) return "1/2-1/2";
    return "*";
  }
  function buildPgn(){
    var out="", n=1;
    for (var i=0;i<P.moves.length;i++){ var m=P.moves[i];
      if (m.side==="white"){ out+=n+". "+m.san+" "; n++; } else out+=m.san+" "; }
    return out.trim();
  }
  async function saveGame(status){
    try{
      var payload={ humanColor:P.human, level:P.level, result:resultFrom(status), pgn:buildPgn(),
        streak:P.streak||0,
        moves:P.moves.map(function(m,i){ return { ply:i+1, side:m.side, san:m.san, uci:m.uci,
          quality:m.coaching?m.coaching.quality:null, cpLoss:m.coaching?m.coaching.cpLoss:null,
          evalCp:m.coaching?m.coaching.evalCp:null, tag:m.coaching?m.coaching.tag:null }; }) };
      var r=await api("/api/save",payload);
      var acc = P.human==="white"? r.whiteAcc : r.blackAcc;
      var pr = r.progress;
      var msg = (status||"Game over.")+"  — saved to Dashboard"+(acc!=null?" ("+acc+"% accuracy)":"")+".";
      if (pr){ msg += "  Grade "+pr.grade+", +"+pr.earned+" XP (level "+pr.level+")."; }
      setStatus(msg, true);
      if (pr){ showGrade(pr); }
    }catch(e){ /* saving is best-effort */ }
  }

  function onSquareClick(e){
    if (P.busy || !P.legal.length) return;
    var sq=e.currentTarget.dataset.sq;
    if (P.sel){ if (sq===P.sel){ P.sel=null; renderPlay(); return; }
      if (pTargets(P.sel).indexOf(sq)>=0){ attemptMove(P.sel,sq); return; } }
    if (pTargets(sq).length){ P.sel=sq; renderPlay(); } else { P.sel=null; renderPlay(); }
  }
  function attemptMove(from,to){
    var cands=P.legal.filter(function(u){ return u.slice(0,4)===from+to; });
    if (cands.length>1){ showPromo(from,to,cands); return; }
    if (cands.length===1) humanMove(cands[0]);
  }
  function showPromo(from,to,cands){
    promo.hidden=false; promo.innerHTML="";
    ["q","r","b","n"].forEach(function(pc){ var u=from+to+pc; if(cands.indexOf(u)<0)return;
      var b=document.createElement("button"); b.textContent=GLYPH[pc];
      b.addEventListener("click",function(){ promo.hidden=true; humanMove(u); }); promo.appendChild(b); });
  }

  async function newGame(){
    if (P.busy) return; P.busy=true;
    P.fen=START; P.moves=[]; P.sel=null; P.last=null; P.coaching=null; P.showRef=false;
    P.humanAccs=[]; P.evalWhiteCp=0; P.saved=false; P.plan=null; P.arrows=[];
    P.streak=0; P.prevYourWin=50; P.hanging=[]; P.targets=[]; renderPulse(null);
    P.human=el("colorSel").value; P.level=parseInt(el("levelSel").value,10); P.orient=P.human;
    renderPlay();
    setStatus("New game. "+(P.human==="white"?"Your move.":"Engine to move…"),false,P.human==="black");
    try{ if (P.human==="black"){ await engineMove(); } else { await refreshLegal(); } }
    catch(e){ setStatus("Error: "+e.message,true); }
    P.busy=false;
  }
  async function undo(){
    if (P.busy || !P.moves.length) return; P.busy=true; P.showRef=false; P.sel=null; P.plan=null; P.arrows=[];
    P.moves.pop(); if (P.moves.length && turnOf(P.moves[P.moves.length-1].fen)!==P.human) P.moves.pop();
    P.fen = P.moves.length? P.moves[P.moves.length-1].fen : START;
    P.last=null; P.coaching=lastHumanCoaching(); P.saved=false;
    P.humanAccs=P.moves.filter(function(m){return m.coaching && m.coaching.cpLoss!=null;})
      .map(function(m){return moveAcc(m.coaching.cpLoss,m.coaching.evalCp);});
    try{ await refreshLegal(); }catch(e){}
    renderPlay(); setStatus("Your move."); P.busy=false;
  }
  function lastHumanCoaching(){ for(var i=P.moves.length-1;i>=0;i--) if(P.moves[i].coaching) return P.moves[i].coaching; return null; }
  async function hint(){
    if (P.busy) return; P.busy=true; P.showRef=false; P.plan=null;
    setStatus("Finding the best move…",false,true);
    try{ var c=await api("/api/hint",{fen:P.fen,useLlm:P.useLlm});
      c.label="Best: "+c.bestSan; c.isBest=true; c.playedFrom=c.bestFrom; c.playedTo=c.bestTo; c.quality="best";
      P.coaching=c; P.arrows=coachArrows(c,false); renderPlay();
      setStatus("Hint shown — the green arrow is the engine's choice.");
    }catch(e){ setStatus("Error: "+e.message,true); } P.busy=false;
  }
  async function plan(){
    if (P.busy) return; P.busy=true; P.showRef=false; P.coaching=null;
    setStatus("Thinking about the plan…",false,true);
    try{ var d=await api("/api/plan",{fen:P.fen,useLlm:P.useLlm});
      P.plan=d; P.arrows = d.bestFrom?[{from:d.bestFrom,to:d.bestTo,color:cvar("--accent"),dashed:true}]:[];
      renderPlay(); setStatus("Here's the long-term plan for this position.");
    }catch(e){ setStatus("Error: "+e.message,true); } P.busy=false;
  }
  function flip(){ P.orient=P.orient==="white"?"black":"white"; renderPlay(); }
  function toggleRef(){ if(refBtn.disabled)return; P.showRef=!P.showRef;
    P.arrows=coachArrows(P.coaching,P.showRef); renderPlay(); }

  // ================= DASHBOARD =================
  var D = { review:null, idx:0 };
  function openReview(data){
    D.review=data.review; D.idx=0;
    el("reviewCard").hidden=false;
    var head=el("reviewHead");
    head.innerHTML='<strong>'+esc(data.white)+'</strong> vs <strong>'+esc(data.black)+'</strong> '+esc(data.result)+
      '<span class="acc">W '+(data.whiteAcc!=null?data.whiteAcc+"%":"–")+' · B '+(data.blackAcc!=null?data.blackAcc+"%":"–")+'</span>';
    var ss=el("stratSummary");
    if (data.strategicSummary && data.strategicSummary.text){ ss.hidden=false; ss.textContent=data.strategicSummary.text; }
    else ss.hidden=true;
    renderPlot(data.plot);
    renderReview();
    el("reviewCard").scrollIntoView({behavior:"smooth",block:"nearest"});
  }
  function jumpToPly(ply){
    if (!D.review) return;
    for (var i=0;i<D.review.length;i++){ if (D.review[i].ply===ply){ D.idx=i; renderReview(); return; } }
  }
  function renderPlot(plot){
    var card=el("plotCard");
    if (!plot || !plot.hasPlot){
      if (plot && plot.reason){ card.hidden=false;
        card.innerHTML='<h3>🎭 The Plot</h3><p class="plotnone">No slow-burning plot here — '+esc(plot.reason)+'</p>'; }
      else card.hidden=true;
      return;
    }
    card.hidden=false;
    var acts='<div class="plotacts">'+
      plotAct("Act 1 · Seed", plot.seed)+
      (plot.buildup&&plot.buildup.length?plotAct("Act 2 · Build", plot.buildup[0], plot.buildup.length>1?('+'+(plot.buildup.length-1)+' more'):""):"")+
      plotAct("Act 3 · Strike", plot.strike)+'</div>';
    card.innerHTML='<h3>🎭 The Plot</h3><p class="ptext">'+esc(plot.text)+'</p>'+acts;
    [].forEach.call(card.querySelectorAll('.pact'),function(b){ b.addEventListener('click',function(){ jumpToPly(+b.dataset.ply); }); });
  }
  function plotAct(label,node,extra){
    return '<button class="pact" data-ply="'+node.ply+'"><span class="k">'+label+'</span>'+
      '<span class="m">'+node.moveNumber+'. '+esc(node.san)+'</span>'+(extra?' <span class="k">'+esc(extra)+'</span>':'')+'</button>';
  }
  function renderReview(){
    if (!D.review || !D.review.length) return;
    var c=D.review[D.idx];
    drawBoard(el("dboard"), c.fenBefore, "white", { last:{from:c.playedFrom,to:c.playedTo} });
    drawArrows(el("darrows"), "white", coachArrows(c,false));
    el("dpanel").innerHTML = panelHTML(c,false);
    var mg=el("dmovegrid"); mg.innerHTML="";
    D.review.forEach(function(m,i){
      var chip=document.createElement("button"); chip.className="mchip"; chip.setAttribute("aria-current", i===D.idx?"true":"false");
      var num=m.side==="white"?'<span class="num">'+m.moveNumber+'.</span> ':"";
      chip.innerHTML='<span class="dot" style="background:'+cvar(QVAR[m.quality]||"--good")+'"></span>'+num+esc(m.san)+(m.glyph||"");
      chip.addEventListener("click",function(){ D.idx=i; renderReview(); }); mg.appendChild(chip);
    });
  }
  function reviewStep(delta,abs){ if(!D.review)return; D.idx = abs!=null?abs:Math.max(0,Math.min(D.review.length-1,D.idx+delta)); renderReview(); }

  async function loadDash(){
    try{
      var d=await api("/api/dashboard",{});
      renderStats(d);
      var g=await api("/api/games",{limit:50});
      renderGames(g.games);
    }catch(e){ el("statsPanel").innerHTML='<p class="empty">Could not load stats: '+esc(e.message)+'</p>'; }
  }
  function renderStats(d){
    var rec=d.record, trend=d.accuracyTrend||[];
    var avg = trend.length? (trend.reduce(function(a,b){return a+b.acc;},0)/trend.length).toFixed(0)+"%" : "–";
    var h='<h2>Your patterns</h2><div class="statrow">'+
      tile(d.gameCount,"games")+tile(rec.wins+"-"+rec.draws+"-"+rec.losses,"W-D-L")+tile(avg,"avg accuracy")+'</div>';
    // accuracy trend sparkline
    if (trend.length>=2) h+='<div class="charttitle">Accuracy over time</div>'+sparkline(trend);
    // mistake-type bars
    var tags=d.mistakeTags||{}, keys=Object.keys(tags).sort(function(a,b){return tags[b]-tags[a];});
    if (keys.length){ var max=Math.max.apply(null,keys.map(function(k){return tags[k];}));
      h+='<div class="charttitle">Where you go wrong</div>';
      keys.forEach(function(k){ h+=bar(TAGLABEL[k]||k, tags[k], max, cvar("--mistake")); }); }
    // quality distribution
    var q=d.qualityCounts||{}, order=["brilliant","best","excellent","good","inaccuracy","mistake","blunder"];
    var qk=order.filter(function(k){return q[k];});
    if (qk.length){ var qmax=Math.max.apply(null,qk.map(function(k){return q[k];}));
      h+='<div class="charttitle">Your move quality</div>';
      qk.forEach(function(k){ h+=bar(k, q[k], qmax, cvar(QVAR[k])); }); }
    // accuracy by phase
    var ph=d.accuracyByPhase||{}, phk=["opening","middlegame","endgame"].filter(function(k){return ph[k]!=null;});
    if (phk.length){ h+='<div class="charttitle">Accuracy by phase</div>';
      phk.forEach(function(k){ h+=bar(k, ph[k], 100, cvar("--accent"), "%"); }); }
    // performance by opening
    if (d.byOpening && d.byOpening.length){
      h+='<div class="charttitle">By opening</div><div class="oplist">';
      d.byOpening.forEach(function(o){
        h+='<div class="oprow"><span class="opn">'+esc(o.opening)+'</span>'+
           '<span class="opm">'+o.games+'g'+(o.accuracy!=null?' · '+o.accuracy+'%':'')+
           (o.score!=null?' · '+o.score+'% score':'')+'</span></div>'; });
      h+='</div>';
    }
    // weakness trend (older -> recent)
    if (d.weaknessTrend && d.weaknessTrend.length){
      h+='<div class="charttitle">Weakness trend (older → recent)</div>';
      d.weaknessTrend.forEach(function(t){
        var arrow = t.recent>t.older?'<span style="color:var(--blunder)">↑</span>'
                  : t.recent<t.older?'<span style="color:var(--best)">↓</span>':'→';
        h+='<div class="barrow"><span class="lbl">'+esc(TAGLABEL[t.tag]||t.tag)+'</span>'+
           '<span class="val" style="width:auto;flex:1">'+t.older+' → '+t.recent+' '+arrow+'</span></div>'; });
    }
    if (!d.gameCount) h='<h2>Your patterns</h2><p class="empty">No games yet. Play a game or import one — your patterns show up here.</p>';
    el("statsPanel").innerHTML=h;
  }
  function tile(n,l){ return '<div class="stattile"><div class="n">'+esc(String(n))+'</div><div class="l">'+esc(l)+'</div></div>'; }
  function bar(label,val,max,color,suffix){
    var pct=Math.round(val/max*100);
    return '<div class="barrow"><span class="lbl">'+esc(label)+'</span><span class="track">'+
      '<span class="fill" style="width:'+pct+'%;background:'+color+'"></span></span><span class="val">'+val+(suffix||"")+'</span></div>';
  }
  function sparkline(trend){
    var w=300,h=70,pad=6, n=trend.length;
    var xs=function(i){ return pad+i*(w-2*pad)/(n-1); };
    var ys=function(a){ return h-pad-(a/100)*(h-2*pad); };
    var d="";
    trend.forEach(function(p,i){ d+=(i?"L":"M")+xs(i).toFixed(1)+","+ys(p.acc).toFixed(1)+" "; });
    var dots="";
    trend.forEach(function(p,i){ var col=p.result==="1-0"||p.result==="0-1"?cvar("--good"):cvar("--muted");
      dots+='<circle cx="'+xs(i).toFixed(1)+'" cy="'+ys(p.acc).toFixed(1)+'" r="2.5" fill="'+cvar("--accent")+'"/>'; });
    return '<svg class="trend" viewBox="0 0 '+w+' '+h+'" preserveAspectRatio="none">'+
      '<line x1="'+pad+'" y1="'+ys(50)+'" x2="'+(w-pad)+'" y2="'+ys(50)+'" stroke="'+cvar("--line")+'" stroke-dasharray="3 3"/>'+
      '<path d="'+d+'" fill="none" stroke="'+cvar("--accent")+'" stroke-width="2"/>'+dots+'</svg>';
  }
  function renderGames(games){
    var gl=el("gameList");
    if (!games.length){ gl.innerHTML='<p class="empty">No games stored yet.</p>'; return; }
    gl.innerHTML="";
    games.forEach(function(g){
      var acc = g.human_color==="white"?g.white_acc : g.human_color==="black"?g.black_acc : null;
      var date=new Date(g.created_at*1000).toLocaleDateString();
      var row=document.createElement("div"); row.className="grow";
      row.innerHTML='<div class="meta"><div class="players">'+esc(g.white||"?")+' vs '+esc(g.black||"?")+'</div>'+
        '<div class="sub">'+esc(g.source)+' · '+esc(g.result||"*")+' · '+date+'</div></div>'+
        '<div class="accbadge">'+(acc!=null?acc+"%":g.ply_count+" ply")+'</div>';
      row.addEventListener("click",function(){ openStored(g.id); });
      gl.appendChild(row);
    });
  }
  async function openStored(id){
    setImport("Re-analysing game "+id+"…",false,true);
    try{ var data=await api("/api/review",{id:id}); clearImport(); openReview(data); }
    catch(e){ setImport("Error: "+e.message,true); }
  }

  function setImport(t,err,spin){ var e=el("importStatus"); e.className="importstatus"+(err?" err":"");
    e.innerHTML=(spin?'<span class="spin"></span> ':"")+esc(t); }
  function clearImport(){ el("importStatus").textContent=""; }
  async function importLichess(){
    var u=el("lichessUser").value.trim(); if(!u){ setImport("Enter a Lichess username.",true); return; }
    setImport("Fetching & analysing "+u+"'s latest game (this takes a few seconds)…",false,true);
    try{ var data=await api("/api/import/lichess",{username:u}); clearImport(); openReview(data); loadDash(); }
    catch(e){ setImport("Error: "+e.message,true); }
  }
  async function importPgn(){
    var p=el("pgnText").value.trim(); if(!p){ setImport("Paste a PGN first.",true); return; }
    setImport("Analysing game (a few seconds)…",false,true);
    try{ var data=await api("/api/import/pgn",{pgn:p}); clearImport(); openReview(data); loadDash(); }
    catch(e){ setImport("Error: "+e.message,true); }
  }

  // ================= nav + health =================
  var dashLoaded=false;
  function showView(v){
    document.querySelectorAll(".navbtn").forEach(function(b){ b.setAttribute("aria-current", b.dataset.view===v?"true":"false"); });
    document.querySelectorAll("section[data-view]").forEach(function(s){ s.hidden = s.dataset.view!==v; });
    if (v==="dash"){ loadDash(); }
    if (v==="progress"){ loadProgress(); }
    if (v==="train"){ loadTrain(); }
  }

  // ================= progression =================
  function kingdomCards(kingdom){
    return (kingdom||[]).map(function(k){
      return '<div class="kcard'+(k.unlocked?" on":"")+'">'+
        '<span class="kicon">'+k.icon+'</span>'+
        '<span class="kname">'+esc(k.name)+'</span>'+
        (k.unlocked?'':'<span class="klock">locked</span>')+'</div>';
    }).join("");
  }
  function renderProgress(p){
    var bar = p.nextAt==null
      ? '<div class="xpnext">Max level reached — '+p.xp+' XP</div>'
      : '<div class="xpbar"><div class="xpfill" style="width:'+p.pct+'%"></div></div>'+
        '<div class="xpnext">'+p.xp+' / '+p.nextAt+' XP to level '+(p.level+1)+'</div>';
    el("levelCard").innerHTML =
      '<div class="levelhead"><span class="levelno">Level '+p.level+'</span>'+
      '<span class="leveltot">'+p.xp+' XP total</span></div>'+ bar +
      '<div class="lifestats">'+
        '<div><b>'+p.stats.games+'</b><span>games</span></div>'+
        '<div><b>'+p.stats.wins+'</b><span>wins</span></div>'+
        '<div><b>'+(p.stats.bestAcc||0)+'%</b><span>best accuracy</span></div>'+
        '<div><b>'+p.stats.bestStreak+'</b><span>best streak</span></div>'+
      '</div>';
    el("kingdomGrid").innerHTML = kingdomCards(p.kingdom);
  }
  async function loadProgress(){
    try{ var p=await api("/api/profile",{}); renderProgress(p); }
    catch(e){ el("levelCard").innerHTML='<p class="empty">Could not load progress.</p>'; }
  }
  function showGrade(pr){
    var g=document.createElement("div"); g.className="gradepop grade-"+(pr.grade[0]||"E").toLowerCase();
    g.innerHTML='<div class="gradebig">'+pr.grade+'</div>'+
      '<div class="gradesub">+'+pr.earned+' XP · level '+pr.level+'</div>';
    document.body.appendChild(g);
    requestAnimationFrame(function(){ g.classList.add("show"); });
    setTimeout(function(){ g.classList.remove("show");
      setTimeout(function(){ g.remove(); },400); }, 2600);
  }
  // ================= Puzzle Rush (Train) =================
  var PZ = { puzzles:[], idx:0, fen:null, orient:"white", legal:[], sel:null,
    cur:null, solved:0, streak:0, best:0, active:false, busy:false, over:false };
  var pzBoard=el("pzBoard"), pzArrows=el("pzArrows"), pzPromo=el("pzPromo"),
      pzPanel=el("pzPanel"), pzStatus=el("pzStatus"), pzScore=el("pzScore");

  function pzSetStatus(t){ pzStatus.textContent=t; }
  function pzRenderScore(){
    if (!PZ.active && !PZ.over){ pzScore.hidden=true; return; }
    pzScore.hidden=false;
    pzScore.innerHTML='<div class="pzmetric"><b>'+PZ.solved+'</b><span>solved</span></div>'+
      '<div class="pzmetric"><b>'+PZ.streak+'</b><span>streak</span></div>'+
      '<div class="pzmetric"><b>'+PZ.best+'</b><span>best</span></div>';
  }
  function pzDraw(opts){
    opts=opts||{};
    drawBoard(pzBoard, PZ.fen, PZ.orient, {
      sel:PZ.sel, last:opts.last,
      targets: PZ.sel?pzTargets(PZ.sel):[],
      onClick: pzClick,
    });
    pzArrows.querySelectorAll("line,circle").forEach(function(n){n.remove();});
    if (opts.arrow) drawArrows(pzArrows, PZ.orient, [opts.arrow]);
  }
  function pzTargets(from){ var o=[]; PZ.legal.forEach(function(u){ if(u.slice(0,2)===from)o.push(u.slice(2,4)); }); return o; }

  async function loadTrain(){
    if (PZ.active) return;  // keep a rush in progress when returning to the tab
    try{
      var r=await api("/api/puzzles",{order:el("pzOrder").value,limit:40});
      PZ.puzzles=r.puzzles||[];
      if (!PZ.puzzles.length){
        pzPanel.innerHTML='<p class="empty">No puzzles yet. Puzzle Rush is built from your own '+
          'mistakes — play and finish a few games (they save automatically), then come back '+
          'to redeem the moves you missed.</p>';
        el("pzStartBtn").disabled=true;
        pzSetStatus("Nothing to train yet — go play a game.");
      } else {
        pzPanel.innerHTML='<p class="empty">Ready: <b>'+PZ.puzzles.length+'</b> position'+
          (PZ.puzzles.length===1?"":"s")+' drawn from your own games are waiting. '+
          'Hit <b>Start rush</b> and find the move you missed.</p>';
        el("pzStartBtn").disabled=false;
        pzSetStatus("Ready. "+PZ.puzzles.length+" of your own mistakes to redeem.");
      }
    }catch(e){ pzPanel.innerHTML='<p class="empty">Could not load puzzles.</p>'; }
  }

  async function pzStart(){
    await loadTrain();
    if (!PZ.puzzles.length) return;
    PZ.active=true; PZ.over=false; PZ.idx=0; PZ.solved=0; PZ.streak=0; PZ.best=0;
    el("pzSkipBtn").disabled=false; el("pzSolveBtn").disabled=false; el("pzStartBtn").textContent="Restart";
    pzRenderScore();
    await pzLoad(0);
  }

  async function pzLoad(i){
    PZ.busy=true; PZ.sel=null; pzPromo.hidden=true;
    if (i>=PZ.puzzles.length){ pzFinish(true); return; }
    PZ.idx=i; var p=PZ.puzzles[i]; PZ.cur=p;
    PZ.fen=p.fen; PZ.orient=p.sideToMove;
    try{ var lg=await api("/api/legal",{fen:p.fen}); PZ.legal=lg.ucis||[]; }
    catch(e){ PZ.legal=[]; }
    var side=p.sideToMove==="white"?"White":"Black";
    pzPanel.innerHTML='<div class="pztheme">'+esc(p.theme)+'</div>'+
      '<p class="why">You played <b>'+esc(p.playedSan||"?")+'</b> here — a '+esc(p.quality)+
      '. <b>'+side+'</b> to move: find the move you missed.</p>'+
      '<div class="panelnote">Puzzle '+(i+1)+' of '+PZ.puzzles.length+
      ' · from game #'+esc(String(p.gameId))+'</div>';
    pzSetStatus(side+" to move — your turn to get it right.");
    pzDraw();
    PZ.busy=false;
  }

  function pzClick(e){
    if (PZ.busy || !PZ.active || PZ.over) return;
    var sq=e.currentTarget.dataset.sq;
    if (PZ.sel){
      if (sq===PZ.sel){ PZ.sel=null; pzDraw(); return; }
      if (pzTargets(PZ.sel).indexOf(sq)>=0){ pzAttempt(PZ.sel,sq); return; }
    }
    if (pzTargets(sq).length){ PZ.sel=sq; pzDraw(); } else { PZ.sel=null; pzDraw(); }
  }
  function pzAttempt(from,to){
    var cands=PZ.legal.filter(function(u){ return u.slice(0,4)===from+to; });
    if (cands.length>1){ pzShowPromo(from,to,cands); return; }
    if (cands.length===1) pzCheck(cands[0]);
  }
  function pzShowPromo(from,to,cands){
    pzPromo.hidden=false; pzPromo.innerHTML="";
    ["q","r","b","n"].forEach(function(pc){ var u=from+to+pc; if(cands.indexOf(u)<0)return;
      var b=document.createElement("button"); b.textContent=GLYPH[pc];
      b.addEventListener("click",function(){ pzPromo.hidden=true; pzCheck(u); }); pzPromo.appendChild(b); });
  }

  async function pzCheck(uci){
    if (PZ.busy) return; PZ.busy=true; PZ.sel=null;
    pzSetStatus("Checking…");
    try{
      var r=await api("/api/puzzle/check",{fen:PZ.fen,uci:uci});
      var from=uci.slice(0,2), to=uci.slice(2,4);
      if (r.solved){
        PZ.solved++; PZ.streak++; PZ.best=Math.max(PZ.best,PZ.streak); pzRenderScore();
        pzPanel.innerHTML='<div class="pzverdict good">✓ Solved</div><p class="why">'+esc(r.message)+'</p>';
        pzDraw({arrow:{from:from,to:to,color:cvar("--good")}, last:{from:from,to:to}});
        pzSetStatus("Correct — next position…");
        setTimeout(function(){ pzLoad(PZ.idx+1); }, 1100);
      } else {
        pzPanel.innerHTML='<div class="pzverdict bad">✕ '+esc(r.message)+'</div>';
        pzDraw({arrow:{from:r.bestFrom,to:r.bestTo,color:cvar("--accent")}, last:{from:from,to:to}});
        PZ.streak=0; pzRenderScore();
        pzFinish(false);
      }
    }catch(e){ pzSetStatus("Error checking move: "+e.message); PZ.busy=false; }
  }

  async function pzSolve(){
    if (!PZ.active || PZ.over || PZ.busy || !PZ.cur) return;
    PZ.busy=true;
    try{
      // Ask the engine for the move by checking the played blunder; the response
      // always carries the best move regardless of the candidate.
      var r=await api("/api/puzzle/check",{fen:PZ.fen,uci:PZ.cur.playedUci});
      pzPanel.innerHTML='<div class="pzverdict bad">Shown</div><p class="why">The move was <b>'+
        esc(r.bestSan)+'</b>. '+esc(r.bestLine.join(" "))+'</p>';
      pzDraw({arrow:{from:r.bestFrom,to:r.bestTo,color:cvar("--accent")}});
      PZ.streak=0; pzRenderScore();
    }catch(e){ pzSetStatus("Error: "+e.message); }
    PZ.busy=false;
    setTimeout(function(){ if(PZ.active && !PZ.over) pzLoad(PZ.idx+1); }, 1400);
  }

  function pzSkip(){ if(PZ.active && !PZ.over && !PZ.busy){ PZ.streak=0; pzRenderScore(); pzLoad(PZ.idx+1); } }

  function pzFinish(cleared){
    PZ.over=true; PZ.active=false; PZ.busy=false;
    el("pzSkipBtn").disabled=true; el("pzSolveBtn").disabled=true; el("pzStartBtn").textContent="Start rush";
    pzRenderScore();
    var head=cleared? "Cleared every puzzle!" : "Rush over.";
    pzSetStatus(head+"  Solved "+PZ.solved+", best streak "+PZ.best+".");
  }

  async function loadHealth(){
    try{ var h=await api("/api/health",{});
      el("health").textContent="engine "+(h.engine?"✓":"✗")+"  ·  LLM "+(h.ollama?h.model:"off");
      if (!h.ollama){ var chk=el("llmChk"); chk.checked=false; chk.disabled=true; P.useLlm=false;
        el("llmLabel").textContent="Local LLM not running — using template explainer"; }
    }catch(e){}
  }

  // wire up play
  el("newBtn").onclick=newGame; el("undoBtn").onclick=undo; el("hintBtn").onclick=hint;
  el("flipBtn").onclick=flip; refBtn.onclick=toggleRef; el("planBtn").onclick=plan;
  el("llmChk").onchange=function(e){ P.useLlm=e.target.checked; };
  el("analogyChk").onchange=function(e){ P.analogy=e.target.checked; renderPanel(); };
  el("glowChk").onchange=function(e){ P.showGlow=e.target.checked; renderPlay(); };
  el("colorSel").onchange=newGame; el("levelSel").onchange=function(e){ P.level=parseInt(e.target.value,10); };
  document.addEventListener("keydown",function(e){
    if (!document.querySelector('section[data-view="play"]').hidden){
      if(e.key==="ArrowLeft"){ undo(); } return; }
    if (!document.querySelector('section[data-view="dash"]').hidden && D.review){
      if(e.key==="ArrowLeft"){ reviewStep(-1); e.preventDefault(); }
      else if(e.key==="ArrowRight"){ reviewStep(1); e.preventDefault(); }
    }
  });
  // wire up dashboard
  document.querySelectorAll(".navbtn").forEach(function(b){ b.onclick=function(){ showView(b.dataset.view); }; });
  el("lichessBtn").onclick=importLichess; el("pgnBtn").onclick=importPgn;
  // wire up train / puzzle rush
  el("pzStartBtn").onclick=pzStart; el("pzSkipBtn").onclick=pzSkip; el("pzSolveBtn").onclick=pzSolve;
  el("pzOrder").onchange=function(){ if(!PZ.active){ loadTrain(); } };
  el("dfirst").onclick=function(){reviewStep(null,0);}; el("dprev").onclick=function(){reviewStep(-1);};
  el("dnext").onclick=function(){reviewStep(1);}; el("dlast").onclick=function(){reviewStep(null,D.review?D.review.length-1:0);};

  loadHealth(); loadConcepts(); renderPlay();
  refreshLegal().then(function(){ setStatus("Your move."); }).catch(function(e){ setStatus("Error: "+e.message,true); });
})();
