/* Audio cues follow chronological occurrences, independently of PDF repeats. */
(() => {
  let cues = [], revision = 0, levelRevision = 0, busy = false;
  window.addEventListener("mixerlevelschange", () => { levelRevision++; });
  const urls = {};
  const status = (message, error=false) => {
    $("guideStatus").textContent = message;
    $("guideStatus").className = "status" + (error ? " error" : "");
  };
  function clearAudio() {
    liveMixer.clear();
    for (const kind of ["click", "cues", "mix"]) {
      const player = $(kind + "Preview"), link = $(kind + "Download");
      player.pause(); player.removeAttribute("src"); player.load();
      player.classList.add("hidden"); link.classList.add("hidden"); link.removeAttribute("href");
      if (urls[kind]) URL.revokeObjectURL(urls[kind]);
      delete urls[kind];
    }
  }
  function invalidate() {
    revision++; clearAudio();
    status("Configuração alterada. Gera novamente as pistas para usar estes valores.");
  }
  function accents() {
    const old = $("guideAccent").value;
    const count = Number($("guideMeter").value.split("/")[0]);
    $("guideAccent").replaceChildren(...Array.from({length: count}, (_, i) => {
      const option = document.createElement("option"); option.value = i;
      option.textContent = `Batida ${i + 1}`; return option;
    }));
    $("guideAccent").value = Number(old) < count ? (old || "0") : "0";
  }
  function render() {
    const box = $("cueTimeline"); box.replaceChildren();
    cues.forEach((cue, index) => {
      const row = document.createElement("div"); row.className = "guide-cue-row";
      const label = document.createElement("label"); label.className = "field";
      const caption = document.createElement("span"); caption.textContent = `Aviso ${index + 1}`;
      const name = document.createElement("input"); name.value = cue.name; name.maxLength = 60;
      name.setAttribute("list", "cueNames"); name.required = true;
      name.oninput = () => { cue.name = name.value; invalidate(); };
      label.append(caption, name);
      const timeLabel = document.createElement("label"); timeLabel.className = "field";
      const timeCaption = document.createElement("span"); timeCaption.textContent = "Entrada (segundos)";
      const time = document.createElement("input"); time.type = "number"; time.min = "0";
      time.max = analysis?.audio_duration || analysis?.duration || 1800; time.step = "0.01";
      time.value = cue.start; time.required = true;
      time.oninput = () => { cue.start = time.value === "" ? null : Number(time.value); invalidate(); };
      timeLabel.append(timeCaption, time);
      const remove = document.createElement("button"); remove.type = "button";
      remove.className = "icon-btn danger"; remove.textContent = "×";
      remove.setAttribute("aria-label", `Remover aviso ${index + 1}`);
      remove.onclick = () => { cues.splice(index, 1); render(); invalidate(); };
      row.append(label, timeLabel, remove); box.append(row);
    });
  }
  const originalPopulate = populateReview;
  populateReview = function() {
    originalPopulate(); revision++; clearAudio();
    cues = (analysis.cue_sections || []).map(s => ({name: s.name === "INTRO" ? "Introdução" : s.name, start: Math.round(s.start * 100) / 100}));
    $("guideMode").value = analysis.beat_times?.length >= 2 ? "detected" : "fixed";
    $("guideTempo").value = analysis.tempo || 120;
    $("guideTempo").disabled = $("guideMode").value !== "fixed";
    $("guideMeter").value = analysis.meter || "4/4";
    $("guideOffset").value = 0; accents(); $("guideAccent").value = "0";
    render(); status("Revê os avisos e gera cada pista. Duração máxima: 30 minutos.");
  };
  $("addCue").onclick = () => {
    if (cues.length >= 128) return status("Limite de 128 avisos atingido.", true);
    cues.push({name: "Solo", start: 0}); render(); invalidate();
  };
  for (const id of ["guideMode", "guideTempo", "guideMeter", "guideOffset", "guideAccent", "guideLead"]) {
    $(id).addEventListener("input", () => {
      if (id === "guideMeter") accents();
      $("guideTempo").disabled = $("guideMode").value !== "fixed";
      invalidate();
    });
  }
  async function generate(kind) {
    if (!analysis || busy) return;
    const fields = kind === "click" ? [$("guideTempo"), $("guideOffset")] : [...$("guidePanel").querySelectorAll("input")];
    if (fields.some(field => !field.reportValidity())) return;
    const currentRevision = revision, currentLevels = levelRevision;
    const data = {kind, title: $("title").value || analysis.title,
      duration: analysis.audio_duration || analysis.duration,
      tempo: Number($("guideTempo").value), meter: $("guideMeter").value,
      mode: $("guideMode").value, beat_times: analysis.beat_times || [],
      offset: Number($("guideOffset").value), accent: Number($("guideAccent").value),
      lead_beats: Number($("guideLead").value), cue_sections: cues, playback_token: analysis.playback_token,
      ...liveMixer.levels()};
    busy = true; $("generateClick").disabled = $("generateCues").disabled = $("generateMix").disabled = $("exportMix").disabled = true;
    status(kind === "mix" || kind === "desk" ? "A preparar música, click e avisos…" : kind === "click" ? "A gerar o click…" : "A gerar o guia de voz em português de Portugal…");
    try {
      if (kind === "desk") await liveMixer.unlock();
      const response = await fetch(kind === "desk" ? "/api/mixer-session" : kind === "mix" ? "/api/playback-mix" : "/api/audio-guide", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(data)});
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.error || `Não foi possível gerar a pista (${response.status}).`);
      }
      if (kind === "desk") {
        const session = await response.json();
        if (currentRevision !== revision) return status("Os dados mudaram. Prepara novamente a mesa.");
        liveMixer.load(session.url);
        return status("Mesa pronta. Carrega em Reproduzir e ajusta os faders enquanto ouves.");
      }
      const blob = await response.blob();
      if (kind === "mix" && currentLevels !== levelRevision) return status("Os volumes mudaram durante a exportação. Exporta novamente para incluir os valores atuais.");
      if (currentRevision !== revision) return status("Os dados mudaram durante a geração. Gera novamente a pista.");
      if (urls[kind]) URL.revokeObjectURL(urls[kind]);
      urls[kind] = URL.createObjectURL(blob);
      const player = $(kind + "Preview"), link = $(kind + "Download");
      if (kind !== "mix") { player.src = urls[kind]; player.classList.remove("hidden"); }
      link.href = urls[kind]; link.download = `${kind === "mix" ? "Mistura" : kind === "click" ? "Click" : "Guia_Voz_PT-PT"}_${data.title.replace(/[^\p{L}\p{N} _-]/gu, "_").slice(0, 100)}.${kind === "mix" ? "mp3" : "wav"}`;
      link.classList.remove("hidden");
      status(kind === "mix" ? "MP3 pronto para descarregar com os volumes selecionados." : "Pista pronta. Ouve o resultado e descarrega o WAV.");
    } catch (error) { status(error.message, true); }
    finally { busy = false; $("generateClick").disabled = $("generateCues").disabled = $("generateMix").disabled = $("exportMix").disabled = false; }
  }
  $("generateMix").onclick = () => generate("desk");
  $("exportMix").onclick = () => generate("mix");
  $("generateClick").onclick = () => generate("click");
  $("generateCues").onclick = () => generate("cues");
  for (const id of ["player", "clickPreview", "cuesPreview", "mixPreview"]) {
    $(id).addEventListener("play", () => {
      for (const other of ["player", "clickPreview", "cuesPreview", "mixPreview"]) if (id !== other) $(other).pause();
    });
  }
  window.addEventListener("beforeunload", clearAudio);
  accents();
})();

/* PWA install + update controls. */
(() => {
  const topActions = document.querySelector(".top-actions");
  if (!topActions) return;

  const currentVersion = (document.querySelector(".version")?.textContent || "").replace(/^v/i, "").trim();
  let deferredInstallPrompt = null;
  let latestVersion = null;
  let updateAvailable = false;

  const style = document.createElement("style");
  style.textContent = `
    .pwa-action{border:1px solid rgba(255,255,255,.16);background:rgba(255,255,255,.06);color:inherit;border-radius:999px;padding:8px 12px;font:inherit;font-size:12px;font-weight:700;cursor:pointer;white-space:nowrap;transition:.2s ease}
    .pwa-action:hover{transform:translateY(-1px);background:rgba(255,255,255,.11)}
    .pwa-action.update-ready{border-color:#59e8a9;background:rgba(89,232,169,.13);color:#9af6c8}
    .pwa-action:disabled{opacity:.58;cursor:default;transform:none}
    .pwa-modal-backdrop{position:fixed;inset:0;background:rgba(0,0,0,.65);display:grid;place-items:center;padding:20px;z-index:9999}
    .pwa-modal{width:min(520px,100%);background:#0d1713;border:1px solid rgba(255,255,255,.13);border-radius:20px;padding:24px;box-shadow:0 28px 80px rgba(0,0,0,.42);color:#eef8f3}
    .pwa-modal h3{margin:0 0 10px;font-size:21px}.pwa-modal p{margin:8px 0;color:#b7c7bf;line-height:1.55}.pwa-modal-actions{display:flex;gap:10px;justify-content:flex-end;margin-top:20px;flex-wrap:wrap}
    .pwa-modal .pwa-primary{background:#59e8a9;color:#07110d;border:0;border-radius:12px;padding:10px 14px;font-weight:800;cursor:pointer}.pwa-modal .pwa-secondary{background:transparent;color:#eaf5ef;border:1px solid rgba(255,255,255,.2);border-radius:12px;padding:10px 14px;font-weight:700;cursor:pointer}
    @media(max-width:760px){.top-actions{gap:6px;flex-wrap:wrap;justify-content:flex-end}.pwa-action{padding:7px 9px;font-size:11px}}
  `;
  document.head.appendChild(style);

  const manifest = document.createElement("link");
  manifest.rel = "manifest";
  manifest.href = `/manifest.webmanifest?v=${encodeURIComponent(currentVersion || "latest")}`;
  document.head.appendChild(manifest);

  const mobileCapable = document.createElement("meta");
  mobileCapable.name = "mobile-web-app-capable";
  mobileCapable.content = "yes";
  document.head.appendChild(mobileCapable);

  const installButton = document.createElement("button");
  installButton.type = "button";
  installButton.className = "pwa-action";
  installButton.textContent = "⬇ Instalar no ambiente de trabalho";

  const updateButton = document.createElement("button");
  updateButton.type = "button";
  updateButton.className = "pwa-action";
  updateButton.textContent = "↻ Verificar atualização";

  topActions.prepend(updateButton);
  topActions.prepend(installButton);

  function modal(title, paragraphs, actions = []) {
    const backdrop = document.createElement("div");
    backdrop.className = "pwa-modal-backdrop";
    const card = document.createElement("div");
    card.className = "pwa-modal";
    const heading = document.createElement("h3");
    heading.textContent = title;
    card.appendChild(heading);
    paragraphs.forEach((text) => {
      const p = document.createElement("p");
      p.textContent = text;
      card.appendChild(p);
    });
    const actionBox = document.createElement("div");
    actionBox.className = "pwa-modal-actions";
    actions.forEach((action) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = action.primary ? "pwa-primary" : "pwa-secondary";
      button.textContent = action.label;
      button.onclick = () => {
        if (action.run) action.run();
        if (action.close !== false) backdrop.remove();
      };
      actionBox.appendChild(button);
    });
    const close = document.createElement("button");
    close.type = "button";
    close.className = "pwa-secondary";
    close.textContent = "Fechar";
    close.onclick = () => backdrop.remove();
    actionBox.appendChild(close);
    card.appendChild(actionBox);
    backdrop.appendChild(card);
    backdrop.addEventListener("click", (event) => { if (event.target === backdrop) backdrop.remove(); });
    document.body.appendChild(backdrop);
  }

  function installedMode() {
    return window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true;
  }

  function refreshInstallState() {
    if (installedMode()) {
      installButton.textContent = "✓ Instalado no ambiente de trabalho";
      installButton.disabled = true;
    } else {
      installButton.textContent = "⬇ Instalar no ambiente de trabalho";
      installButton.disabled = false;
    }
  }

  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    deferredInstallPrompt = event;
    refreshInstallState();
  });

  window.addEventListener("appinstalled", () => {
    deferredInstallPrompt = null;
    refreshInstallState();
  });

  installButton.addEventListener("click", async () => {
    if (installedMode()) return refreshInstallState();
    if (deferredInstallPrompt) {
      deferredInstallPrompt.prompt();
      await deferredInstallPrompt.userChoice;
      deferredInstallPrompt = null;
      refreshInstallState();
      return;
    }
    modal(
      "Instalar o Score Studio",
      [
        "Se o botão de instalação do navegador ainda não estiver disponível, usa o menu do Chrome/Edge e escolhe “Instalar Score Studio” ou “Criar atalho”.",
        "Depois de instalado, o Score Studio abre numa janela própria e fica disponível a partir do Ambiente de Trabalho/Menu Iniciar."
      ]
    );
  });

  async function checkUpdates(manual = false) {
    updateButton.disabled = true;
    updateButton.textContent = "↻ A verificar…";
    try {
      const response = await fetch(`/api/update-status?t=${Date.now()}`, {cache: "no-store"});
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.error || "Falha ao verificar atualização.");

      latestVersion = data.latest_version;
      updateAvailable = Boolean(data.update_available);
      updateButton.classList.toggle("update-ready", updateAvailable);
      updateButton.textContent = updateAvailable
        ? `● Nova versão v${latestVersion}`
        : `✓ Atualizado v${data.current_version}`;

      if (updateAvailable && manual) showUpdateInfo();
      if (!updateAvailable) {
        setTimeout(() => {
          if (!updateAvailable) updateButton.textContent = "↻ Verificar atualização";
        }, 3500);
      }
    } catch (error) {
      updateButton.textContent = "⚠ Não foi possível verificar";
      if (manual) modal("Verificação de atualização", [error.message || "Não foi possível verificar atualizações neste momento."]);
      setTimeout(() => { updateButton.textContent = "↻ Verificar atualização"; }, 4000);
    } finally {
      updateButton.disabled = false;
    }
  }

  function showUpdateInfo() {
    modal(
      `Nova versão v${latestVersion} disponível`,
      [
        `Estás a usar a versão v${currentVersion || "atual"}. Existe uma versão mais recente no GitHub.`,
        "Neste computador, a atualização é feita a partir do instalador local para manter o MuScriptor e o arranque automático intactos."
      ],
      [{
        label: "Abrir versão no GitHub",
        primary: true,
        run: () => window.open("https://github.com/nelsonrodriguesexpresso/Score-Studio/tree/feature/muscriptor-local-worker", "_blank", "noopener")
      }]
    );
  }

  updateButton.addEventListener("click", () => {
    if (updateAvailable) showUpdateInfo();
    else checkUpdates(true);
  });

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register(`/service-worker.js?v=${encodeURIComponent(currentVersion || "latest")}`, {scope: "/"}).catch(() => undefined);
  }

  refreshInstallState();
  setTimeout(() => checkUpdates(false), 1800);
})();
