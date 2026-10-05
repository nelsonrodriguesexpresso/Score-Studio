(() => {
  if (window.__muscriptorProgressLoaded) return;
  window.__muscriptorProgressLoaded = true;

  const style = document.createElement("style");
  style.textContent = `
    .ai-progress{margin-top:12px;border:1px solid rgba(89,232,169,.18);border-radius:14px;background:rgba(89,232,169,.045);padding:12px 13px;display:none}
    .ai-progress.show{display:block}.ai-progress-top{display:flex;justify-content:space-between;gap:12px;align-items:center;margin-bottom:8px}.ai-progress-title{font-size:12px;font-weight:800;color:#dff6e9}.ai-progress-pct{font-size:13px;font-weight:900;color:#59e8a9;min-width:46px;text-align:right}
    .ai-progress-track{height:8px;background:rgba(255,255,255,.09);border-radius:999px;overflow:hidden}.ai-progress-bar{height:100%;width:0;background:linear-gradient(90deg,#2ccf87,#59e8a9);border-radius:inherit;transition:width .35s ease}
    .ai-progress-bottom{display:flex;justify-content:space-between;gap:12px;margin-top:8px;font-size:10.5px;color:#8fa399}.ai-progress-stage{color:#b7c9bf}.ai-progress-exact{color:#7f9188}.ai-progress.done .ai-progress-bar{background:#59e8a9}.ai-progress.error{border-color:rgba(255,122,162,.28);background:rgba(255,122,162,.06)}.ai-progress.error .ai-progress-pct{color:#ff91b1}
  `;
  document.head.appendChild(style);

  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const makeId = () => (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`);

  function ensureUi(button){
    let box = document.getElementById("muscriptorAiProgress");
    if (box) return box;
    box = document.createElement("div");
    box.id = "muscriptorAiProgress";
    box.className = "ai-progress";
    box.innerHTML = `
      <div class="ai-progress-top"><span id="aiProgressTitle" class="ai-progress-title">A preparar a transcrição…</span><strong id="aiProgressPct" class="ai-progress-pct">0%</strong></div>
      <div class="ai-progress-track"><div id="aiProgressBar" class="ai-progress-bar"></div></div>
      <div class="ai-progress-bottom"><span id="aiProgressStage" class="ai-progress-stage">A enviar áudio</span><span id="aiProgressExact" class="ai-progress-exact">Progresso real da IA</span></div>`;
    const holder = button.parentElement || button;
    holder.appendChild(box);
    return box;
  }

  function paint(data){
    const box = document.getElementById("muscriptorAiProgress");
    if (!box) return;
    box.classList.add("show");
    box.classList.toggle("done", data.stage === "done");
    box.classList.toggle("error", data.stage === "error");
    const overall = Math.max(0, Math.min(100, Number(data.percent ?? 0)));
    document.getElementById("aiProgressBar").style.width = `${overall}%`;
    document.getElementById("aiProgressPct").textContent = `${overall}%`;
    document.getElementById("aiProgressTitle").textContent = data.message || "A transcrever com IA…";
    document.getElementById("aiProgressStage").textContent = data.stage_label || data.stage || "Transcrição";
    const ai = data.ai_percent;
    document.getElementById("aiProgressExact").textContent = Number.isFinite(Number(ai)) ? `Leitura IA: ${Number(ai)}%` : "A aguardar dados da IA";
  }

  async function poll(jobId, stopRef){
    while (!stopRef.stop){
      try{
        const r = await fetch(`/api/muscriptor/progress/${encodeURIComponent(jobId)}?t=${Date.now()}`, {cache:"no-store"});
        if (r.ok){
          const data = await r.json();
          paint(data);
          if (data.stage === "done" || data.stage === "error") return;
        }
      }catch{}
      await sleep(700);
    }
  }

  function init(){
    const button = document.getElementById("muscriptorMidi");
    const input = document.getElementById("audio");
    const status = document.getElementById("muscriptorWorkerStatus");
    if (!button || !input) return false;
    if (button.dataset.progressBound === "1") return true;
    button.dataset.progressBound = "1";
    ensureUi(button);

    button.onclick = async () => {
      const file = input.files?.[0];
      if (!file){
        if (typeof window.setStatus === "function") window.setStatus("Escolhe primeiro uma música para o MuScriptor.", "error");
        else alert("Escolhe primeiro uma música para o MuScriptor.");
        return;
      }

      const jobId = makeId();
      const stopRef = {stop:false};
      const oldText = button.querySelector("span")?.textContent || "Gerar MIDI com IA";
      button.disabled = true;
      if (button.querySelector("span")) button.querySelector("span").textContent = "A transcrever…";
      if (status){ status.textContent = "MuScriptor está a transcrever. A percentagem abaixo acompanha os blocos processados pela IA."; status.style.color = ""; }
      paint({percent:1, ai_percent:0, stage:"uploading", stage_label:"A preparar", message:"A enviar o áudio para o MuScriptor…"});

      const fd = new FormData();
      fd.append("file", file);
      fd.append("job_id", jobId);
      const poller = poll(jobId, stopRef);

      try{
        const response = await fetch(`/api/muscriptor/midi?job_id=${encodeURIComponent(jobId)}`, {method:"POST", body:fd});
        if (!response.ok){
          const raw = await response.text();
          let msg = raw;
          try { const data = JSON.parse(raw); msg = data.error || data.detail || raw; } catch {}
          throw new Error(msg || `HTTP ${response.status}`);
        }
        const blob = await response.blob();
        paint({percent:100, ai_percent:100, stage:"done", stage_label:"Concluído", message:"Transcrição concluída · MIDI pronto"});
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        const base = (file.name || "transcricao").replace(/\.[^.]+$/, "");
        a.href = url; a.download = `MuScriptor_${base}.mid`; document.body.appendChild(a); a.click(); a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 4000);
        if (status){ status.textContent = "Transcrição concluída · MIDI descarregado"; status.style.color = "#6ee7a8"; }
        if (typeof window.setStatus === "function") window.setStatus("MuScriptor concluiu a transcrição MIDI.", "success");
        if (typeof window.toast === "function") window.toast("MIDI MuScriptor pronto");
      }catch(error){
        paint({percent:0, stage:"error", stage_label:"Erro", message:`Erro: ${error.message}`});
        if (status){ status.textContent = `Erro: ${error.message}`; status.style.color = "#f3b6b6"; }
        if (typeof window.setStatus === "function") window.setStatus(`MuScriptor: ${error.message}`, "error");
      }finally{
        stopRef.stop = true;
        await poller.catch(() => undefined);
        if (button.querySelector("span")) button.querySelector("span").textContent = oldText;
        button.disabled = false;
      }
    };
    return true;
  }

  if (!init()){
    const timer = setInterval(() => { if (init()) clearInterval(timer); }, 250);
    setTimeout(() => clearInterval(timer), 15000);
  }
})();
