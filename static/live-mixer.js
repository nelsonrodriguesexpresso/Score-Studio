/* A single streamed four-channel timeline keeps all tracks sample-aligned. */
window.liveMixer = (() => {
  const audio = document.getElementById('mixPreview');
  const keys = ['Music', 'Click', 'Cues', 'Master'];
  let context, gains, ready = false;
  const el = id => document.getElementById(id);
  const effective = key => el('mute' + key).getAttribute('aria-pressed') === 'true' ? 0 : Number(el('mix' + key).value) / 100;
  function update() {
    keys.forEach(key => {
      const value = Number(el('mix' + key).value);
      el('mix' + key + 'Value').textContent = value + '%';
      el('mix' + key).style.setProperty('--level', value + '%');
      if (gains) gains[key].gain.setTargetAtTime(effective(key), context.currentTime, .015);
    });
    el('mixDownload').classList.add('hidden');
    window.dispatchEvent(new Event('mixerlevelschange'));
  }
  keys.forEach(key => {
    el('mix' + key).addEventListener('input', update);
    el('mute' + key).onclick = () => {
      const button = el('mute' + key);
      button.setAttribute('aria-pressed', String(button.getAttribute('aria-pressed') !== 'true'));
      update();
    };
  });
  async function unlock() {
    if (!context) {
      const AudioContext = window.AudioContext || window.webkitAudioContext;
      if (!AudioContext) throw new Error('Este navegador não suporta a mesa interativa. Podes exportar a mistura MP3.');
      context = new AudioContext();
      const source = context.createMediaElementSource(audio);
      const split = context.createChannelSplitter(4);
      const stereo = context.createChannelMerger(2);
      gains = Object.fromEntries(keys.map(key => [key, context.createGain()]));
      source.connect(split);
      split.connect(stereo, 0, 0); split.connect(stereo, 1, 1);
      stereo.connect(gains.Music);
      split.connect(gains.Click, 2); split.connect(gains.Cues, 3);
      for (const key of ['Music', 'Click', 'Cues']) gains[key].connect(gains.Master);
      const limiter = context.createDynamicsCompressor();
      limiter.threshold.value = -1; limiter.knee.value = 0; limiter.ratio.value = 20;
      limiter.attack.value = .003; limiter.release.value = .1;
      gains.Master.connect(limiter); limiter.connect(context.destination);
      update();
    }
    await context.resume();
  }
  const clock = t => `${Math.floor((t || 0) / 60)}:${String(Math.floor((t || 0) % 60)).padStart(2, '0')}`;
  function time() {
    const duration = Number.isFinite(audio.duration) ? audio.duration : 0;
    el('mixerSeek').max = duration || 1;
    el('mixerSeek').value = audio.currentTime || 0;
    el('mixerTime').textContent = `${clock(audio.currentTime)} / ${clock(duration)}`;
    el('mixerPlay').textContent = audio.paused ? 'Reproduzir' : 'Pausar';
  }
  ['timeupdate', 'loadedmetadata', 'play', 'pause', 'ended'].forEach(event => audio.addEventListener(event, time));
  audio.addEventListener('error', () => {
    if (ready) { el('guideStatus').textContent = 'Não foi possível reproduzir esta sessão. Prepara novamente a mesa ou exporta o MP3.'; el('guideStatus').className = 'status error'; }
  });
  el('mixerSeek').addEventListener('input', () => { if (ready && Number.isFinite(audio.duration)) audio.currentTime = Number(el('mixerSeek').value); });
  el('mixerPlay').onclick = async () => {
    if (!ready) return;
    try { await unlock(); if (audio.paused) await audio.play(); else audio.pause(); }
    catch (error) { el('guideStatus').textContent = error.message; el('guideStatus').className = 'status error'; }
  };
  update();
  return {
    unlock,
    load(url) { audio.src = url; ready = true; el('mixerTransport').classList.remove('hidden'); audio.load(); },
    clear() { ready = false; audio.pause(); el('mixerTransport').classList.add('hidden'); },
    levels() { const master = effective('Master'); return {music_volume: effective('Music') * master * 100, click_volume: effective('Click') * master * 100, cues_volume: effective('Cues') * master * 100}; }
  };
})();
