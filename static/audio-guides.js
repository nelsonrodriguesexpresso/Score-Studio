/* Audio cues follow chronological occurrences, independently of PDF repeats. */
(() => {
  let cues = [], revision = 0, busy = false;
  const urls = {};
  const status = (message, error=false) => {
    $("guideStatus").textContent = message;
    $("guideStatus").className = "status" + (error ? " error" : "");
  };
  function clearAudio() {
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
  for (const id of ["guideMode", "guideTempo", "guideMeter", "guideOffset", "guideAccent", "guideLead", "mixMusic", "mixClick", "mixCues"]) {
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
    const currentRevision = revision;
    const data = {kind, title: $("title").value || analysis.title,
      duration: analysis.audio_duration || analysis.duration,
      tempo: Number($("guideTempo").value), meter: $("guideMeter").value,
      mode: $("guideMode").value, beat_times: analysis.beat_times || [],
      offset: Number($("guideOffset").value), accent: Number($("guideAccent").value),
      lead_beats: Number($("guideLead").value), cue_sections: cues, playback_token: analysis.playback_token,
      music_volume: Number($("mixMusic").value), click_volume: Number($("mixClick").value), cues_volume: Number($("mixCues").value)};
    busy = true; $("generateClick").disabled = $("generateCues").disabled = $("generateMix").disabled = true;
    status(kind === "mix" ? "A preparar música, click e avisos…" : kind === "click" ? "A gerar o click…" : "A gerar o guia de voz em português de Portugal…");
    try {
      const response = await fetch(kind === "mix" ? "/api/playback-mix" : "/api/audio-guide", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(data)});
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.error || `Não foi possível gerar a pista (${response.status}).`);
      }
      const blob = await response.blob();
      if (currentRevision !== revision) return status("Os dados mudaram durante a geração. Gera novamente a pista.");
      if (urls[kind]) URL.revokeObjectURL(urls[kind]);
      urls[kind] = URL.createObjectURL(blob);
      const player = $(kind + "Preview"), link = $(kind + "Download");
      player.src = urls[kind]; player.classList.remove("hidden");
      link.href = urls[kind]; link.download = `${kind === "mix" ? "Mistura" : kind === "click" ? "Click" : "Guia_Voz_PT-PT"}_${data.title.replace(/[^\p{L}\p{N} _-]/gu, "_").slice(0, 100)}.${kind === "mix" ? "mp3" : "wav"}`;
      link.classList.remove("hidden");
      status(kind === "mix" ? "Mistura pronta. Carrega em reproduzir para ouvir as três pistas." : "Pista pronta. Ouve o resultado e descarrega o WAV.");
    } catch (error) { status(error.message, true); }
    finally { busy = false; $("generateClick").disabled = $("generateCues").disabled = $("generateMix").disabled = false; }
  }
  $("generateMix").onclick = () => generate("mix");
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
