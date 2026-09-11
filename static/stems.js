(() => {
  const trackIcons = {vocals:"🎤", bass:"🎸", drums:"🥁", other:"🎹"};
  let mixerTimer = null;

  function injectStemOption(){
    const action = document.querySelector(".analysis-action");
    if(!action || document.getElementById("separateStems")) return;
    const box = document.createElement("div");
    box.className = "stem-option";
    box.innerHTML = `
      <div class="stem-option-copy">
        <strong>Áudio por pistas</strong>
        <span>Separa automaticamente Voz, Baixo, Bateria e Outros. A análise demora mais quando esta opção está ativa.</span>
      </div>
      <label class="stem-toggle">
        <input id="separateStems" type="checkbox">
        <span class="stem-switch" aria-hidden="true"></span>
        <span>Separar pistas</span>
      </label>`;
    action.parentNode.insertBefore(box, action);
  }

  function injectMixer(){
    const review = document.getElementById("reviewCard");
    const summary = review?.querySelector(".summary-grid");
    if(!review || !summary || document.getElementById("stemsHost")) return;
    const host = document.createElement("div");
    host.id = "stemsHost";
    host.className = "hidden";
    summary.insertAdjacentElement("afterend", host);
  }

  function patchAnalyzeRequests(){
    const nativeFetch = window.fetch.bind(window);
    window.fetch = (input, init = {}) => {
      const url = typeof input === "string" ? input : input?.url || "";
      if((url === "/api/analyze" || url === "/api/analyze-youtube") && init.body instanceof FormData){
        if(!init.body.has("separate_stems")){
          const enabled = Boolean(document.getElementById("separateStems")?.checked);
          init.body.append("separate_stems", enabled ? "true" : "false");
        }
      }
      return nativeFetch(input, init);
    };
  }

  function formatTime(value){
    const seconds = Math.max(0, Number(value) || 0);
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${String(s).padStart(2,"0")}`;
  }

  function stopMixerTimer(){
    if(mixerTimer){ clearInterval(mixerTimer); mixerTimer = null; }
  }

  function renderWarning(message){
    const host = document.getElementById("stemsHost");
    if(!host) return;
    stopMixerTimer();
    host.className = "";
    host.innerHTML = `<div class="stems-warning"><strong>As pistas não ficaram disponíveis.</strong><br>${escapeHtml(message || "A análise musical foi concluída normalmente.")}</div>`;
  }

  function renderMixer(stems){
    const host = document.getElementById("stemsHost");
    if(!host || !stems?.tracks?.length){
      if(host){ host.className = "hidden"; host.innerHTML = ""; }
      return;
    }

    stopMixerTimer();
    host.className = "";
    host.innerHTML = `
      <section class="stems-card">
        <div class="stems-card-head">
          <div>
            <span class="kicker">ÁUDIO POR PISTAS</span>
            <h3>Misturador de ensaio</h3>
            <p>Ouve instrumentos isolados, usa Solo ou Mute e ajusta o volume de cada pista.</p>
          </div>
          <span class="stems-expiry">Temporário · 30 min</span>
        </div>
        <div class="stems-master">
          <button id="stemsPlay" type="button" title="Reproduzir">▶</button>
          <input id="stemsSeek" type="range" min="0" max="1000" value="0" aria-label="Posição da música">
          <span id="stemsTime" class="stems-time">0:00 / 0:00</span>
        </div>
        <div id="stemsTracks" class="stems-tracks"></div>
      </section>`;

    const tracksBox = document.getElementById("stemsTracks");
    const players = [];

    stems.tracks.forEach(track => {
      const row = document.createElement("div");
      row.className = "stem-track";
      row.dataset.stem = track.id;
      row.innerHTML = `
        <div class="stem-name"><span class="stem-dot"></span><span>${trackIcons[track.id] || "♪"} ${escapeHtml(track.label || track.id)}</span></div>
        <div class="stem-actions">
          <button class="solo" type="button">SOLO</button>
          <button class="mute" type="button">MUTE</button>
        </div>
        <div class="stem-volume"><input type="range" min="0" max="100" value="100" aria-label="Volume"><span>100</span></div>`;
      const audio = new Audio(track.url);
      audio.preload = "metadata";
      players.push({track, row, audio, solo:false, mute:false, volume:1});
      tracksBox.appendChild(row);
    });

    const playBtn = document.getElementById("stemsPlay");
    const seek = document.getElementById("stemsSeek");
    const time = document.getElementById("stemsTime");
    let playing = false;
    let duration = 0;

    function applyMix(){
      const hasSolo = players.some(p => p.solo);
      players.forEach(p => {
        const audible = !p.mute && (!hasSolo || p.solo);
        p.audio.muted = !audible;
        p.audio.volume = p.volume;
        p.row.classList.toggle("suppressed", !audible);
      });
    }

    function setPlaying(next){
      playing = next;
      playBtn.textContent = playing ? "❚❚" : "▶";
      playBtn.title = playing ? "Pausa" : "Reproduzir";
    }

    function masterCurrent(){
      const first = players[0]?.audio;
      return first?.currentTime || 0;
    }

    function updateClock(){
      const current = masterCurrent();
      const maxDuration = Math.max(...players.map(p => Number(p.audio.duration) || 0), 0);
      if(maxDuration > 0) duration = maxDuration;
      if(duration > 0 && !seek.matches(":active")) seek.value = String(Math.round((current / duration) * 1000));
      time.textContent = `${formatTime(current)} / ${formatTime(duration)}`;
      if(playing && duration > 0 && current >= duration - .15) setPlaying(false);
    }

    players.forEach(p => {
      p.audio.addEventListener("loadedmetadata", updateClock);
      const soloBtn = p.row.querySelector(".solo");
      const muteBtn = p.row.querySelector(".mute");
      const volume = p.row.querySelector(".stem-volume input");
      const volumeText = p.row.querySelector(".stem-volume span");

      soloBtn.onclick = () => {
        p.solo = !p.solo;
        soloBtn.classList.toggle("active", p.solo);
        applyMix();
      };
      muteBtn.onclick = () => {
        p.mute = !p.mute;
        muteBtn.classList.toggle("active", p.mute);
        applyMix();
      };
      volume.oninput = () => {
        p.volume = Math.max(0, Math.min(1, Number(volume.value) / 100));
        p.audio.volume = p.volume;
        volumeText.textContent = String(volume.value);
      };
    });

    playBtn.onclick = async () => {
      if(playing){
        players.forEach(p => p.audio.pause());
        setPlaying(false);
        return;
      }
      const target = masterCurrent();
      players.forEach(p => { if(Math.abs(p.audio.currentTime - target) > .08) p.audio.currentTime = target; });
      applyMix();
      try{
        await Promise.all(players.map(p => p.audio.play()));
        setPlaying(true);
      }catch(error){
        toast("Não foi possível iniciar todas as pistas.");
      }
    };

    seek.oninput = () => {
      if(!duration) return;
      const next = (Number(seek.value) / 1000) * duration;
      players.forEach(p => { p.audio.currentTime = next; });
      updateClock();
    };

    applyMix();
    mixerTimer = setInterval(() => {
      if(playing && players.length > 1){
        const master = players[0].audio.currentTime;
        players.slice(1).forEach(p => {
          if(Math.abs(p.audio.currentTime - master) > .16) p.audio.currentTime = master;
        });
      }
      updateClock();
    }, 250);
  }

  function patchReview(){
    const original = window.populateReview;
    if(typeof original !== "function") return;
    window.populateReview = function(){
      original.apply(this, arguments);
      if(window.analysis?.stems?.tracks?.length) renderMixer(window.analysis.stems);
      else if(window.analysis?.stems_error) renderWarning(window.analysis.stems_error);
      else {
        const host = document.getElementById("stemsHost");
        if(host){ host.className = "hidden"; host.innerHTML = ""; }
      }
    };
  }

  injectStemOption();
  injectMixer();
  patchAnalyzeRequests();
  patchReview();
})();
