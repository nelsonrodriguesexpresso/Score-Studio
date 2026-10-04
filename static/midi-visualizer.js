/* Score Studio MIDI visualizer: piano-roll inspired by MuScriptor's graphical result view. */
(() => {
  const COLORS = ["#59e8a9", "#7ab8ff", "#ff9b73", "#d58cff", "#ffd166", "#6fe7e1", "#ff7aa2", "#b7e36a"];
  const GM_FAMILIES = ["Piano", "Percussão cromática", "Órgão", "Guitarra", "Baixo", "Cordas", "Ensemble", "Metais", "Palhetas", "Sopros", "Sintetizador", "Synth Pad", "Efeitos", "Étnico", "Percussão", "Efeitos sonoros"];
  let current = null;
  let blobUrl = null;
  let hiddenTracks = new Set();
  let pxPerSecond = 58;

  const style = document.createElement("style");
  style.textContent = `
    .midi-lab{margin-top:18px;border:1px solid rgba(255,255,255,.11);border-radius:20px;background:linear-gradient(145deg,rgba(9,22,17,.94),rgba(6,15,12,.96));overflow:hidden;box-shadow:0 18px 50px rgba(0,0,0,.18)}
    .midi-lab-head{display:flex;align-items:flex-start;justify-content:space-between;gap:18px;padding:20px 22px;border-bottom:1px solid rgba(255,255,255,.08)}
    .midi-lab-head h3{margin:3px 0 5px;font-size:20px}.midi-lab-head p{margin:0;color:#a8bbb1;max-width:720px;line-height:1.45}.midi-kicker{font-size:11px;letter-spacing:.16em;color:#59e8a9;font-weight:800}
    .midi-state{display:inline-flex;align-items:center;gap:7px;border:1px solid rgba(255,255,255,.12);border-radius:999px;padding:7px 10px;font-size:11px;font-weight:800;color:#b8c8c0;white-space:nowrap}.midi-state i{width:7px;height:7px;border-radius:50%;background:#84938c}.midi-state.ready{color:#9af6c8;border-color:rgba(89,232,169,.26);background:rgba(89,232,169,.08)}.midi-state.ready i{background:#59e8a9;box-shadow:0 0 0 4px rgba(89,232,169,.1)}
    .midi-actions{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:14px 18px;border-bottom:1px solid rgba(255,255,255,.07);flex-wrap:wrap}.midi-actions-left,.midi-actions-right{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.midi-tool{border:1px solid rgba(255,255,255,.13);background:rgba(255,255,255,.05);color:#eaf5ef;border-radius:10px;padding:8px 10px;font:inherit;font-size:12px;font-weight:750;cursor:pointer}.midi-tool:hover{background:rgba(255,255,255,.09)}.midi-tool.primary{background:#59e8a9;color:#07110d;border-color:#59e8a9}.midi-tool[disabled]{opacity:.45;cursor:default}.midi-stats{font-size:12px;color:#9fb0a8}
    .midi-legend{display:flex;gap:7px;flex-wrap:wrap;padding:12px 18px;border-bottom:1px solid rgba(255,255,255,.07)}.midi-track-chip{display:inline-flex;align-items:center;gap:7px;border:1px solid rgba(255,255,255,.12);background:rgba(255,255,255,.045);color:#dce8e2;border-radius:999px;padding:7px 10px;font:inherit;font-size:11px;font-weight:750;cursor:pointer}.midi-track-chip i{width:9px;height:9px;border-radius:3px;background:var(--track-color)}.midi-track-chip.off{opacity:.42;text-decoration:line-through}
    .midi-roll-wrap{position:relative;overflow:auto;max-height:520px;background:#07100d}.midi-roll-wrap canvas{display:block}.midi-empty{padding:38px 24px;text-align:center;color:#8fa098}.midi-empty strong{display:block;color:#dce8e2;font-size:16px;margin-bottom:6px}.midi-empty span{font-size:13px;line-height:1.5}
    .midi-hint{padding:10px 18px 14px;color:#83958c;font-size:11px;line-height:1.5}.midi-generate-slot{display:flex;align-items:center;justify-content:flex-end;gap:10px;flex-wrap:wrap}.midi-generate-slot > div{min-width:220px}
    @media(max-width:760px){.midi-lab-head{padding:16px;flex-direction:column}.midi-actions{padding:12px}.midi-legend{padding:10px 12px}.midi-roll-wrap{max-height:430px}.midi-state{align-self:flex-start}}
  `;
  document.head.appendChild(style);

  function readU32(view, offset) { return view.getUint32(offset, false); }
  function readU16(view, offset) { return view.getUint16(offset, false); }
  function readVar(bytes, state) {
    let value = 0, b, guard = 0;
    do { b = bytes[state.i++]; value = (value << 7) | (b & 0x7f); guard++; } while ((b & 0x80) && guard < 5 && state.i < bytes.length);
    return value;
  }
  function text(bytes, start, len) {
    try { return new TextDecoder("utf-8").decode(bytes.slice(start, start + len)).replace(/\0/g, "").trim(); } catch { return ""; }
  }

  function parseMidi(buffer) {
    const bytes = new Uint8Array(buffer), view = new DataView(buffer);
    if (text(bytes, 0, 4) !== "MThd") throw new Error("O ficheiro recebido não é um MIDI válido.");
    const headerLen = readU32(view, 4), format = readU16(view, 8), nTracks = readU16(view, 10), division = readU16(view, 12);
    if (division & 0x8000) throw new Error("Este MIDI usa temporização SMPTE, ainda não suportada na visualização.");
    let pos = 8 + headerLen;
    const tracks = [], tempos = [{ tick: 0, us: 500000 }];
    let maxTick = 0;

    for (let ti = 0; ti < nTracks && pos + 8 <= bytes.length; ti++) {
      if (text(bytes, pos, 4) !== "MTrk") break;
      const len = readU32(view, pos + 4), end = Math.min(bytes.length, pos + 8 + len);
      const s = { i: pos + 8 }, active = new Map(), notes = [];
      let tick = 0, running = 0, name = "", instrument = "", program = null;
      while (s.i < end) {
        tick += readVar(bytes, s); maxTick = Math.max(maxTick, tick);
        let status = bytes[s.i++];
        if (status < 0x80) { s.i--; status = running; } else if (status < 0xf0) running = status;
        if (status === 0xff) {
          const type = bytes[s.i++], l = readVar(bytes, s), start = s.i;
          if (type === 0x03) name = text(bytes, start, l) || name;
          if (type === 0x04) instrument = text(bytes, start, l) || instrument;
          if (type === 0x51 && l === 3) tempos.push({ tick, us: (bytes[start] << 16) | (bytes[start + 1] << 8) | bytes[start + 2] });
          s.i += l; continue;
        }
        if (status === 0xf0 || status === 0xf7) { const l = readVar(bytes, s); s.i += l; continue; }
        const type = status & 0xf0, ch = status & 0x0f;
        if (type === 0xc0 || type === 0xd0) {
          const a = bytes[s.i++]; if (type === 0xc0 && program === null) program = a; continue;
        }
        const a = bytes[s.i++], b = bytes[s.i++];
        if (type === 0x90 && b > 0) {
          const key = `${ch}:${a}`; const stack = active.get(key) || []; stack.push({ tick, velocity: b, channel: ch, pitch: a }); active.set(key, stack);
        } else if (type === 0x80 || (type === 0x90 && b === 0)) {
          const key = `${ch}:${a}`, stack = active.get(key); if (stack && stack.length) { const on = stack.shift(); notes.push({ ...on, endTick: Math.max(on.tick + 1, tick) }); }
        }
      }
      for (const stack of active.values()) for (const on of stack) notes.push({ ...on, endTick: Math.max(on.tick + 1, maxTick) });
      if (notes.length) tracks.push({ index: ti, name, instrument, program, notes });
      pos = end;
    }

    tempos.sort((a,b) => a.tick - b.tick);
    const dedup = [];
    for (const t of tempos) { if (dedup.length && dedup[dedup.length - 1].tick === t.tick) dedup[dedup.length - 1] = t; else dedup.push(t); }
    let sec = 0, lastTick = 0, us = 500000;
    for (const t of dedup) { sec += ((t.tick - lastTick) * us) / division / 1e6; t.sec = sec; lastTick = t.tick; us = t.us; }
    function tickToSec(tick) {
      let lo = 0, hi = dedup.length - 1, idx = 0;
      while (lo <= hi) { const mid = (lo + hi) >> 1; if (dedup[mid].tick <= tick) { idx = mid; lo = mid + 1; } else hi = mid - 1; }
      const t = dedup[idx]; return t.sec + ((tick - t.tick) * t.us) / division / 1e6;
    }
    let count = 0, minPitch = 127, maxPitch = 0, duration = 0;
    tracks.forEach((track, idx) => {
      track.color = COLORS[idx % COLORS.length];
      track.label = track.name || track.instrument || (track.notes.some(n => n.channel === 9) ? "Bateria / Percussão" : track.program !== null ? `${GM_FAMILIES[Math.floor(track.program / 8)] || "Instrumento"} · Pista ${idx + 1}` : `Pista ${idx + 1}`);
      track.notes = track.notes.map(n => {
        const start = tickToSec(n.tick), end = tickToSec(n.endTick); count++; minPitch = Math.min(minPitch, n.pitch); maxPitch = Math.max(maxPitch, n.pitch); duration = Math.max(duration, end); return { ...n, start, end };
      });
    });
    return { format, division, tracks, count, minPitch: count ? minPitch : 48, maxPitch: count ? maxPitch : 72, duration };
  }

  function noteName(pitch) { const names = ["C","C#","D","D#","E","F","F#","G","G#","A","A#","B"]; return `${names[pitch % 12]}${Math.floor(pitch / 12) - 1}`; }
  function black(pitch) { return [1,3,6,8,10].includes(((pitch % 12) + 12) % 12); }

  function ensurePanel() {
    if (document.getElementById("midiLab")) return document.getElementById("midiLab");
    const analysisCard = document.getElementById("analysisCard"); if (!analysisCard) return null;
    const panel = document.createElement("section"); panel.id = "midiLab"; panel.className = "midi-lab";
    panel.innerHTML = `
      <div class="midi-lab-head">
        <div><span class="midi-kicker">MUSCRIPTOR · MIDI</span><h3>Visualização gráfica da transcrição</h3><p>Depois de gerar o MIDI, as notas aparecem aqui em formato piano roll, separadas por pista/instrumento.</p></div>
        <span id="midiVisualState" class="midi-state"><i></i><span>À espera de MIDI</span></span>
      </div>
      <div class="midi-actions">
        <div class="midi-actions-left"><span id="midiStats" class="midi-stats">Gera um MIDI para abrir a visualização.</span></div>
        <div class="midi-actions-right"><button id="midiZoomOut" class="midi-tool" disabled>− Zoom</button><button id="midiZoomIn" class="midi-tool" disabled>+ Zoom</button><button id="midiDownloadAgain" class="midi-tool primary" disabled>Descarregar MIDI</button></div>
      </div>
      <div id="midiLegend" class="midi-legend" hidden></div>
      <div id="midiRollWrap" class="midi-roll-wrap"><div class="midi-empty"><strong>A visualização MIDI aparecerá aqui</strong><span>Escolhe a música e usa “Gerar MIDI com IA”.</span></div></div>
      <div class="midi-hint">Cada cor representa uma pista. Clica no nome de uma pista para a ocultar/mostrar. Usa o zoom para ampliar a linha temporal.</div>`;
    const action = analysisCard.querySelector(".analysis-action");
    action?.insertAdjacentElement("afterend", panel);

    // Move the existing MuScriptor action into the graphical MIDI card.
    setTimeout(() => {
      const button = document.getElementById("muscriptorMidi");
      if (button && !panel.contains(button)) {
        const slot = document.createElement("div"); slot.className = "midi-generate-slot";
        const parent = button.parentElement; if (parent) slot.appendChild(parent);
        panel.querySelector(".midi-actions-left")?.appendChild(slot);
      }
    }, 0);

    document.getElementById("midiZoomOut").onclick = () => { pxPerSecond = Math.max(16, pxPerSecond / 1.35); draw(); };
    document.getElementById("midiZoomIn").onclick = () => { pxPerSecond = Math.min(220, pxPerSecond * 1.35); draw(); };
    document.getElementById("midiDownloadAgain").onclick = () => { if (!blobUrl) return; const a = document.createElement("a"); a.href = blobUrl; a.download = current?.filename || "MuScriptor_transcricao.mid"; document.body.appendChild(a); a.click(); a.remove(); };
    return panel;
  }

  function renderLegend() {
    const legend = document.getElementById("midiLegend"); if (!legend || !current) return;
    legend.hidden = false; legend.innerHTML = "";
    current.tracks.forEach((track, idx) => {
      const b = document.createElement("button"); b.type = "button"; b.className = "midi-track-chip" + (hiddenTracks.has(idx) ? " off" : ""); b.style.setProperty("--track-color", track.color);
      b.innerHTML = `<i></i><span>${track.label.replace(/[<&]/g, m => m === "<" ? "&lt;" : "&amp;")}</span><b>${track.notes.length}</b>`;
      b.onclick = () => { hiddenTracks.has(idx) ? hiddenTracks.delete(idx) : hiddenTracks.add(idx); renderLegend(); draw(); };
      legend.appendChild(b);
    });
  }

  function draw() {
    const wrap = document.getElementById("midiRollWrap"); if (!wrap || !current) return;
    const minPitch = Math.max(21, Math.min(current.minPitch - 2, current.maxPitch - 23));
    const maxPitch = Math.min(108, Math.max(current.maxPitch + 2, minPitch + 23));
    const pitchCount = maxPitch - minPitch + 1;
    const rowH = 12, keyW = 64, topH = 28;
    const width = Math.max(920, Math.min(26000, keyW + current.duration * pxPerSecond + 50));
    const height = topH + pitchCount * rowH;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const canvas = document.createElement("canvas"); canvas.width = Math.round(width * dpr); canvas.height = Math.round(height * dpr); canvas.style.width = `${width}px`; canvas.style.height = `${height}px`;
    const ctx = canvas.getContext("2d"); ctx.scale(dpr, dpr); ctx.font = "10px system-ui, sans-serif";

    ctx.fillStyle = "#07100d"; ctx.fillRect(0,0,width,height);
    for (let p = minPitch; p <= maxPitch; p++) {
      const y = topH + (maxPitch - p) * rowH;
      ctx.fillStyle = black(p) ? "rgba(0,0,0,.20)" : (p % 12 === 0 ? "rgba(255,255,255,.035)" : "rgba(255,255,255,.014)"); ctx.fillRect(keyW,y,width-keyW,rowH);
      ctx.strokeStyle = "rgba(255,255,255,.035)"; ctx.beginPath(); ctx.moveTo(keyW,y+.5); ctx.lineTo(width,y+.5); ctx.stroke();
    }
    const secStep = pxPerSecond >= 90 ? 1 : pxPerSecond >= 38 ? 2 : pxPerSecond >= 22 ? 5 : 10;
    for (let s = 0; s <= current.duration + secStep; s += secStep) {
      const x = keyW + s * pxPerSecond; ctx.strokeStyle = s % (secStep * 5) === 0 ? "rgba(255,255,255,.12)" : "rgba(255,255,255,.055)"; ctx.beginPath(); ctx.moveTo(x,topH); ctx.lineTo(x,height); ctx.stroke(); ctx.fillStyle = "#80938a"; ctx.fillText(`${Math.floor(s/60)}:${String(Math.round(s%60)).padStart(2,"0")}`, x+4, 18);
    }
    current.tracks.forEach((track, idx) => { if (hiddenTracks.has(idx)) return; ctx.fillStyle = track.color; for (const n of track.notes) { if (n.pitch < minPitch || n.pitch > maxPitch) continue; const x = keyW + n.start * pxPerSecond, y = topH + (maxPitch - n.pitch) * rowH + 1.5, w = Math.max(2.5,(n.end-n.start)*pxPerSecond-1), h = rowH-3; ctx.globalAlpha = .38 + .62*(n.velocity/127); ctx.fillRect(x,y,w,h); } ctx.globalAlpha = 1; });

    ctx.fillStyle = "#0a1511"; ctx.fillRect(0,topH,keyW,height-topH); ctx.strokeStyle = "rgba(255,255,255,.13)"; ctx.beginPath(); ctx.moveTo(keyW-.5,topH); ctx.lineTo(keyW-.5,height); ctx.stroke();
    for (let p = minPitch; p <= maxPitch; p++) { const y = topH + (maxPitch - p) * rowH; ctx.fillStyle = black(p) ? "#17201c" : "#dfe8e3"; const kw = black(p) ? keyW*.68 : keyW; ctx.fillRect(0,y,kw,rowH-1); if (p % 12 === 0 || pitchCount <= 32) { ctx.fillStyle = black(p) ? "#dfe8e3" : "#18201d"; ctx.fillText(noteName(p), 5, y+9); } }
    wrap.replaceChildren(canvas);
  }

  async function showMidi(blob, filename) {
    ensurePanel();
    try {
      const parsed = parseMidi(await blob.arrayBuffer()); parsed.filename = filename; current = parsed; hiddenTracks = new Set();
      if (blobUrl) URL.revokeObjectURL(blobUrl); blobUrl = URL.createObjectURL(blob);
      const state = document.getElementById("midiVisualState"); state.className = "midi-state ready"; state.querySelector("span").textContent = "MIDI pronto";
      document.getElementById("midiStats").textContent = `${parsed.count} notas · ${parsed.tracks.length} pista${parsed.tracks.length === 1 ? "" : "s"} · ${Math.floor(parsed.duration/60)}:${String(Math.round(parsed.duration%60)).padStart(2,"0")}`;
      ["midiZoomOut","midiZoomIn","midiDownloadAgain"].forEach(id => document.getElementById(id).disabled = false);
      renderLegend(); draw();
      document.getElementById("midiLab")?.scrollIntoView({behavior:"smooth",block:"start"});
    } catch (error) {
      const state = document.getElementById("midiVisualState"); state.querySelector("span").textContent = "MIDI criado · visualização indisponível";
      const wrap = document.getElementById("midiRollWrap"); wrap.innerHTML = `<div class="midi-empty"><strong>O MIDI foi criado normalmente</strong><span>${String(error.message || error)}</span></div>`;
    }
  }

  ensurePanel();

  // Observe successful Score Studio -> MuScriptor MIDI requests without changing the existing workflow.
  const nativeFetch = window.fetch.bind(window);
  window.fetch = async function(input, init) {
    const response = await nativeFetch(input, init);
    try {
      const url = typeof input === "string" ? input : input?.url || "";
      if (url.includes("/api/muscriptor/midi") && response.ok) {
        const clone = response.clone();
        const disposition = clone.headers.get("content-disposition") || "";
        const match = disposition.match(/filename="?([^";]+)"?/i);
        const filename = match?.[1] || "MuScriptor_transcricao.mid";
        clone.blob().then(blob => showMidi(blob, filename)).catch(() => undefined);
      }
    } catch {}
    return response;
  };
})();
