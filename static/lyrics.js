(() => {
  function injectLyricsEditor(){
    const technical = document.querySelector("#reviewCard .technical");
    if(!technical || document.getElementById("lyricsText")) return;
    const box = document.createElement("section");
    box.className = "lyrics-editor";
    box.innerHTML = `
      <div class="lyrics-heading">
        <div><span class="kicker">LETRA DETETADA</span><h3>Letra da música</h3></div>
        <span id="lyricsLanguage" class="lyrics-language"></span>
      </div>
      <p id="lyricsNotice" class="lyrics-notice">A letra foi transcrita automaticamente a partir do áudio. Revê e corrige antes de exportar.</p>
      <textarea id="lyricsText" rows="14" placeholder="Não foi possível detetar a letra desta música."></textarea>`;
    technical.insertAdjacentElement("afterend", box);
  }

  function injectLyricsExport(){
    const grid = document.querySelector("#exportCard .export-grid");
    if(!grid || document.getElementById("pdfLyrics")) return;
    const card = document.createElement("article");
    card.className = "export-card";
    card.innerHTML = `
      <div class="export-icon">✎</div>
      <div><span class="export-label">LETRA DA MÚSICA</span><h3>Letra + acordes</h3>
      <p>Cria um documento com a letra revista e os acordes detetados.</p></div>
      <button id="pdfLyrics" class="btn btn-secondary">Exportar PDF Letra</button>`;
    grid.appendChild(card);
    document.getElementById("pdfLyrics").onclick = exportLyricsPdf;
  }


  async function pollLyrics(jobId){
    const notice = document.getElementById("lyricsNotice");
    const text = document.getElementById("lyricsText");
    const language = document.getElementById("lyricsLanguage");
    if(!jobId || !notice || !text) return;
    notice.textContent = "A transcrever a letra em segundo plano… Podes continuar a rever os acordes.";
    for(let attempt=0; attempt<300; attempt++){
      await new Promise(resolve => setTimeout(resolve, 3000));
      try{
        const response = await fetch("/api/lyrics/" + encodeURIComponent(jobId), {cache:"no-store"});
        const data = await response.json();
        if(!response.ok || !data.ok) throw new Error(data.error || "Erro na transcrição.");
        if(data.status === "processing") continue;
        if(data.status === "complete"){
          analysis.lyrics = data.lyrics || "";
          analysis.lyrics_language = data.language || "";
          text.value = analysis.lyrics;
          language.textContent = analysis.lyrics_language ? analysis.lyrics_language.toUpperCase() : "";
          notice.textContent = "Transcrição concluída. Revê e corrige eventuais palavras antes de exportar.";
          notice.classList.remove("warning");
          return;
        }
        notice.textContent = (data.error || "Não foi possível transcrever a letra.") + " Podes escrever ou colar a letra manualmente.";
        notice.classList.add("warning");
        return;
      }catch(error){
        if(attempt < 4) continue;
        notice.textContent = "A ligação à transcrição foi interrompida. A análise dos acordes continua disponível.";
        notice.classList.add("warning");
        return;
      }
    }
    notice.textContent = "A transcrição está a demorar mais do que o previsto.";
    notice.classList.add("warning");
  }

  const originalPopulateReview = window.populateReview;
  window.populateReview = function(){
    originalPopulateReview.apply(this, arguments);
    injectLyricsEditor();
    const text = document.getElementById("lyricsText");
    const notice = document.getElementById("lyricsNotice");
    const language = document.getElementById("lyricsLanguage");
    text.value = analysis?.lyrics || "";
    language.textContent = analysis?.lyrics_language ? analysis.lyrics_language.toUpperCase() : "";
    if(analysis?.lyrics_error){
      notice.textContent = analysis.lyrics_error + " Podes escrever ou colar a letra manualmente.";
      notice.classList.add("warning");
    }else if(analysis?.lyrics_job){
      pollLyrics(analysis.lyrics_job);
    }else{
      notice.textContent = "Transcrição automática: revê e corrige eventuais palavras antes de exportar.";
      notice.classList.remove("warning");
    }
  };

  async function exportLyricsPdf(){
    if(!analysis) return;
    syncMetadata();
    const btn = document.getElementById("pdfLyrics");
    btn.disabled = true;
    setExportStatus("A criar o PDF da letra…");
    const data = {
      kind:"lyrics",
      title:analysis.title,
      instrument:analysis.instrument,
      tempo:analysis.tempo,
      key:analysis.key,
      meter:analysis.meter,
      sections:analysis.sections,
      lyrics:document.getElementById("lyricsText")?.value || ""
    };
    try{
      const response = await fetch("/api/export",{
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify(data)
      });
      if(!response.ok) throw new Error((await response.text()).slice(0,200));
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "Letra_Acordes_" + (analysis.title || "Música") + ".pdf";
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 2000);
      setExportStatus("PDF da letra criado com sucesso.","success");
      toast("PDF da letra pronto");
    }catch(error){
      setExportStatus("Erro: " + error.message,"error");
    }finally{
      btn.disabled = false;
    }
  }

  injectLyricsEditor();
  injectLyricsExport();
})();
