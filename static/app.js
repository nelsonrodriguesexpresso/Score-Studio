const $ = id => document.getElementById(id);
let analysis = null;
let selectedFile = null;
let progressTimer = null;
let objectUrl = null;
let rehearsalAudio = null;
let youtubePlayer = null;
let youtubeTimer = null;

const instrumentLabels = { bass5: "Baixo", guitar: "Guitarra", piano: "Piano / Teclado" };

function toast(message){
  const el=$("toast");
  el.textContent=message;
  el.classList.add("show");
  clearTimeout(el._timer);
  el._timer=setTimeout(()=>el.classList.remove("show"),2400);
}
function setStatus(message,type=""){
  const el=$("status");
  el.textContent=message;
  el.className="status"+(type?` ${type}`:"");
  el.classList.remove("hidden");
}
function setExportStatus(message,type=""){
  const el=$("exportStatus");
  el.textContent=message;
  el.className="status"+(type?` ${type}`:"");
  el.classList.remove("hidden");
}
function formatBytes(bytes){
  if(bytes<1024)return `${bytes} B`;
  if(bytes<1024*1024)return `${(bytes/1024).toFixed(1)} KB`;
  return `${(bytes/1024/1024).toFixed(1)} MB`;
}
function formatDuration(seconds){
  const min=Math.floor(seconds/60),sec=Math.round(seconds%60);
  return `${min}:${String(sec).padStart(2,"0")}`;
}
function escapeHtml(value){
  return String(value??"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}
function rightsOk(){
  if(!$("rightsConfirmed").checked){
    setStatus("Confirma primeiro que tens autorização para analisar este conteúdo.","error");
    $("rightsConfirmed").focus();
    return false;
  }
  return true;
}

function selectFile(file){
  if(!file)return;
  if(file.size > 50*1024*1024){
    setStatus("O ficheiro excede o limite público de 50 MB.","error");
    return;
  }
  selectedFile=file;
  $("fileTitle").textContent=file.name;
  $("fname").textContent=`${formatBytes(file.size)} · pronto para analisar`;
  $("audioName").textContent=file.name;
  $("audioSize").textContent=formatBytes(file.size);
  if(objectUrl)URL.revokeObjectURL(objectUrl);
  objectUrl=URL.createObjectURL(file);
  $("player").src=objectUrl;
  $("audioPreview").classList.remove("hidden");
  $("status").classList.add("hidden");
}

$("chooseFile").onclick=e=>{e.stopPropagation();$("audio").click();};
$("dropzone").onclick=()=>$("audio").click();
$("dropzone").onkeydown=e=>{if(e.key==="Enter"||e.key===" "){$("audio").click();e.preventDefault();}};
$("audio").onchange=()=>selectFile($("audio").files[0]);
["dragenter","dragover"].forEach(evt=>$("dropzone").addEventListener(evt,e=>{e.preventDefault();$("dropzone").classList.add("drag");}));
["dragleave","drop"].forEach(evt=>$("dropzone").addEventListener(evt,e=>{e.preventDefault();$("dropzone").classList.remove("drag");}));
$("dropzone").addEventListener("drop",e=>selectFile(e.dataTransfer.files[0]));

function startProgress(){
  clearInterval(progressTimer);
  $("progressBox").classList.remove("hidden");
  let value=4;
  const stages=[
    [8,"A separar focos instrumentais…"],
    [25,"A detetar BPM…"],
    [42,"A estimar a tonalidade…"],
    [58,"A transcrever notas…"],
    [72,"A analisar os acordes…"],
    [85,"A organizar a estrutura…"],
    [94,"A finalizar resultados…"]
  ];
  let stage=0;
  const update=()=>{
    if(stage<stages.length&&value>=stages[stage][0]){$("progressText").textContent=stages[stage][1];stage++;}
    $("progressPercent").textContent=`${Math.round(value)}%`;
    $("progressBar").style.width=`${value}%`;
    value=Math.min(94,value+Math.max(1,(94-value)*.06));
  };
  update();
  progressTimer=setInterval(update,600);
}
function finishProgress(){
  clearInterval(progressTimer);
  $("progressText").textContent="Análise concluída";
  $("progressPercent").textContent="100%";
  $("progressBar").style.width="100%";
  setTimeout(()=>$("progressBox").classList.add("hidden"),700);
}
function failProgress(){clearInterval(progressTimer);$("progressBox").classList.add("hidden");}
function setActiveStep(number){document.querySelectorAll(".step").forEach((s,i)=>s.classList.toggle("active",i===number-1));}
document.querySelectorAll(".step").forEach(btn=>btn.onclick=()=>{const target=$(btn.dataset.target);if(target&&!target.classList.contains("hidden"))target.scrollIntoView({behavior:"smooth",block:"start"});});

$("go").onclick=async()=>{
  if(!selectedFile){setStatus("Escolhe primeiro uma música.","error");return;}
  if(!rightsOk())return;
  $("go").disabled=true;
  setStatus("A análise está em curso. O tempo depende da duração da música.");
  startProgress();
  const fd=new FormData();
  fd.append("file",selectedFile);
  fd.append("instrument",$("instrument").value);
  fd.append("rights_confirmed","true");
  try{
    const response=await fetch("/api/analyze",{method:"POST",body:fd});
    const raw=await response.text();
    let data;
    try{data=JSON.parse(raw);}catch{throw new Error(`Resposta inválida do servidor: ${raw.substring(0,160)}`);}
    if(!response.ok||!data.ok)throw new Error((data.error||"Erro na análise")+(data.detail?` ${data.detail}`:""));
    analysis=data;
    populateReview();
    finishProgress();
    setStatus("Análise concluída. Revê agora acordes e notas.","success");
    $("reviewCard").classList.remove("hidden");
    $("exportCard").classList.remove("hidden");
    setActiveStep(2);
    setTimeout(()=>$("reviewCard").scrollIntoView({behavior:"smooth",block:"start"}),250);
  }catch(error){
    failProgress();
    setStatus(`Erro: ${error.message}`,"error");
  }finally{$("go").disabled=false;}
};

function normalizeSections(){
  if(!analysis) return;
  analysis.sections=(analysis.sections||[]).map((s,i)=>{
    const chords=Array.isArray(s.chords)?s.chords:[];
    let notes=Array.isArray(s.notes)?s.notes:[];
    notes=chords.map((_,idx)=>Array.isArray(notes[idx])?notes[idx]:(typeof notes[idx]==="string"?notes[idx].split(/\s+/).filter(Boolean):[]));
    return {name:s.name||`SECÇÃO ${i+1}`,repeat:Math.max(1,Number(s.repeat)||1),chords,notes};
  });
}

function populateReview(){
  normalizeSections();
  $("title").value=analysis.title||selectedFile?.name.replace(/\.[^.]+$/,"")||"Música";
  $("artistInput").value=analysis.artist||analysis.uploader||"";
  $("bpmInput").value=analysis.tempo||120;
  $("keyInput").value=analysis.key||"C";
  $("meterInput").value=analysis.meter||"4/4";
  $("durationValue").textContent=formatDuration(analysis.duration||0);
  $("barsValue").textContent=analysis.bars_analyzed||countBars();
  $("instrumentValue").textContent=instrumentLabels[analysis.instrument]||"Instrumento";
  $("signal").textContent=analysis.analysis_signal||"-";
  $("focusValue").textContent=analysis.separation?.focus||instrumentLabels[analysis.instrument]||"-";
  $("separationMode").textContent=analysis.separation?.mode||"Análise harmónica";
  $("notes").innerHTML=(analysis.detected_notes||[]).map(n=>`<span>${escapeHtml(n)}</span>`).join("")||"<span>Sem notas estáveis</span>";
  $("tabExportCard").classList.toggle("disabled-card",analysis.instrument==="piano");
  $("pdfTab").disabled=analysis.instrument==="piano";
  renderSections();
  setupRehearsal();
}

function countBars(){return (analysis?.sections||[]).reduce((sum,s)=>sum+(s.chords?.length||0),0);}
function syncMetadata(){
  if(!analysis)return;
  analysis.title=$("title").value||"Música";
  analysis.artist=$("artistInput").value||"";
  analysis.tempo=Number($("bpmInput").value)||120;
  analysis.key=$("keyInput").value||"C";
  analysis.meter=$("meterInput").value||"4/4";
  $("barsValue").textContent=countBars();
}
["title","artistInput","bpmInput","keyInput","meterInput"].forEach(id=>$(id).addEventListener("input",syncMetadata));

function renderSections(){
  const box=$("sections");
  box.innerHTML="";
  (analysis.sections||[]).forEach((section,index)=>{
    const el=document.createElement("article");
    el.className="section-card";
    const measures=(section.chords||[]).map((chord,chordIndex)=>{
      const noteText=(section.notes?.[chordIndex]||[]).join(" ");
      return `<div class="measure-editor">
        <div class="measure-editor-top"><span>Compasso ${chordIndex+1}</span><button data-remove-chord="${index}:${chordIndex}" title="Remover compasso">×</button></div>
        <label><small>Acorde</small><input class="chord-input" data-chord-section="${index}" data-chord-index="${chordIndex}" value="${escapeHtml(chord)}" aria-label="Acorde do compasso ${chordIndex+1}"></label>
        <label><small>Notas</small><input class="note-input" data-note-section="${index}" data-note-index="${chordIndex}" value="${escapeHtml(noteText)}" placeholder="E2 B2 E3 B2" aria-label="Notas do compasso ${chordIndex+1}"></label>
      </div>`;
    }).join("");
    el.innerHTML=`<div class="section-card-header">
      <div class="section-index">${String(index+1).padStart(2,"0")}</div>
      <input class="section-name" data-section-name="${index}" value="${escapeHtml(section.name||`SECÇÃO ${index+1}`)}" aria-label="Nome da secção">
      <label class="repeat-wrap"><span>Repetições</span><input data-repeat="${index}" type="number" min="1" value="${section.repeat||1}"></label>
      <div class="section-menu"><button class="icon-btn" data-up="${index}" title="Subir secção">↑</button><button class="icon-btn" data-down="${index}" title="Descer secção">↓</button><button class="icon-btn" data-copy="${index}" title="Duplicar secção">⧉</button><button class="icon-btn danger" data-remove="${index}" title="Remover secção">×</button></div>
    </div>
    <div class="chords-label"><span>Editor por compasso</span><button class="text-btn" data-add-chord="${index}">+ Adicionar compasso</button></div>
    <div class="measure-grid">${measures}</div>`;
    box.appendChild(el);
  });
  box.querySelectorAll("[data-section-name]").forEach(el=>el.oninput=()=>analysis.sections[+el.dataset.sectionName].name=el.value);
  box.querySelectorAll("[data-repeat]").forEach(el=>el.oninput=()=>analysis.sections[+el.dataset.repeat].repeat=Math.max(1,+el.value||1));
  box.querySelectorAll("[data-chord-section]").forEach(el=>el.oninput=()=>analysis.sections[+el.dataset.chordSection].chords[+el.dataset.chordIndex]=el.value.trim());
  box.querySelectorAll("[data-note-section]").forEach(el=>el.oninput=()=>analysis.sections[+el.dataset.noteSection].notes[+el.dataset.noteIndex]=el.value.trim().split(/\s+/).filter(Boolean).slice(0,4));
  box.querySelectorAll("[data-add-chord]").forEach(el=>el.onclick=()=>{const s=analysis.sections[+el.dataset.addChord];s.chords.push("C");s.notes.push([]);renderSections();syncMetadata();});
  box.querySelectorAll("[data-remove-chord]").forEach(el=>el.onclick=()=>{const [s,c]=el.dataset.removeChord.split(":").map(Number);analysis.sections[s].chords.splice(c,1);analysis.sections[s].notes.splice(c,1);renderSections();syncMetadata();});
  box.querySelectorAll("[data-remove]").forEach(el=>el.onclick=()=>{analysis.sections.splice(+el.dataset.remove,1);renderSections();syncMetadata();});
  box.querySelectorAll("[data-copy]").forEach(el=>el.onclick=()=>{const i=+el.dataset.copy;analysis.sections.splice(i+1,0,JSON.parse(JSON.stringify(analysis.sections[i])));renderSections();syncMetadata();});
  box.querySelectorAll("[data-up]").forEach(el=>el.onclick=()=>moveSection(+el.dataset.up,-1));
  box.querySelectorAll("[data-down]").forEach(el=>el.onclick=()=>moveSection(+el.dataset.down,1));
}
function moveSection(index,direction){
  const target=index+direction;
  if(target<0||target>=analysis.sections.length)return;
  [analysis.sections[index],analysis.sections[target]]=[analysis.sections[target],analysis.sections[index]];
  renderSections();
}
$("addSection").onclick=()=>{analysis.sections.push({name:"NOVA SECÇÃO",repeat:1,chords:["C","G","Am","F"],notes:[[],[],[],[]]});renderSections();syncMetadata();};
$("goExport").onclick=()=>{syncMetadata();setActiveStep(3);$("exportCard").scrollIntoView({behavior:"smooth",block:"start"});};

function renderTimeline(){
  const box=$("syncBars");
  box.innerHTML="";
  (analysis?.timeline||[]).forEach((item,index)=>{
    const btn=document.createElement("button");
    btn.type="button";
    btn.className="sync-bar";
    btn.dataset.syncIndex=String(index);
    btn.innerHTML=`<span>${item.bar}</span><strong>${escapeHtml(item.chord||"-")}</strong>`;
    btn.onclick=()=>seekTimeline(item.start||0);
    box.appendChild(btn);
  });
}

function highlightTimeline(time){
  const timeline=analysis?.timeline||[];
  if(!timeline.length)return;
  let idx=timeline.findIndex(item=>time>=Number(item.start||0)&&time<Number(item.end||0));
  if(idx<0){idx=timeline.reduce((best,item,i)=>Number(item.start||0)<=time?i:best,0);}
  const item=timeline[idx];
  $("syncBar").textContent=item?.bar||"-";
  $("syncChord").textContent=item?.chord||"-";
  document.querySelectorAll(".sync-bar.active").forEach(el=>el.classList.remove("active"));
  const active=document.querySelector(`[data-sync-index="${idx}"]`);
  if(active){
    active.classList.add("active");
    if(active.offsetLeft < $("syncBars").scrollLeft || active.offsetLeft+active.offsetWidth > $("syncBars").scrollLeft+$("syncBars").clientWidth){active.scrollIntoView({behavior:"smooth",block:"nearest",inline:"center"});}
  }
}

function seekTimeline(seconds){
  if(analysis?.source==="youtube"&&youtubePlayer&&typeof youtubePlayer.seekTo==="function"){
    youtubePlayer.seekTo(Number(seconds)||0,true);
    return;
  }
  if(rehearsalAudio){rehearsalAudio.currentTime=Number(seconds)||0;rehearsalAudio.play().catch(()=>{});}
}

function stopYouTubeSync(){
  clearInterval(youtubeTimer);
  youtubeTimer=null;
  try{if(youtubePlayer&&youtubePlayer.destroy)youtubePlayer.destroy();}catch{}
  youtubePlayer=null;
}

function setupYouTubePlayer(videoId){
  stopYouTubeSync();
  const mount=$("youtubeRehearsal");
  mount.classList.remove("hidden");
  mount.innerHTML='<div id="ytPlayerMount"></div>';
  $("syncHelp").textContent="O vídeo original é reproduzido pelo YouTube. O compasso estimado acompanha o tempo do vídeo.";

  const create=()=>{
    if(!window.YT||!window.YT.Player)return;
    youtubePlayer=new YT.Player("ytPlayerMount",{
      videoId,
      playerVars:{rel:0,playsinline:1},
      events:{onReady:()=>{youtubeTimer=setInterval(()=>{try{highlightTimeline(youtubePlayer.getCurrentTime());}catch{}},450);}}
    });
  };
  if(window.YT&&window.YT.Player){create();return;}
  if(!document.getElementById("youtubeIframeApi")){
    const tag=document.createElement("script");
    tag.id="youtubeIframeApi";
    tag.src="https://www.youtube.com/iframe_api";
    document.head.appendChild(tag);
  }
  const previous=window.onYouTubeIframeAPIReady;
  window.onYouTubeIframeAPIReady=()=>{if(typeof previous==="function")previous();create();};
}

function setupRehearsal(){
  stopYouTubeSync();
  if(rehearsalAudio){rehearsalAudio.pause();rehearsalAudio.remove();rehearsalAudio=null;}
  $("youtubeRehearsal").classList.add("hidden");
  $("youtubeRehearsal").innerHTML="";
  renderTimeline();
  highlightTimeline(0);

  if(analysis?.source==="youtube"&&analysis.video_id){
    setupYouTubePlayer(analysis.video_id);
  }else if(objectUrl){
    rehearsalAudio=document.createElement("audio");
    rehearsalAudio.controls=true;
    rehearsalAudio.preload="metadata";
    rehearsalAudio.src=objectUrl;
    rehearsalAudio.className="rehearsal-audio";
    rehearsalAudio.addEventListener("timeupdate",()=>highlightTimeline(rehearsalAudio.currentTime));
    const mount=$("youtubeRehearsal");
    mount.classList.remove("hidden");
    mount.appendChild(rehearsalAudio);
    $("syncHelp").textContent="Reproduz o ficheiro carregado. O compasso estimado fica realçado automaticamente.";
  }else{
    $("syncHelp").textContent="A linha temporal está disponível, mas não existe um leitor de áudio nesta sessão.";
  }
}

function payload(kind){
  syncMetadata();
  return {
    kind,
    title:analysis.title,
    artist:analysis.artist||"",
    instrument:analysis.instrument,
    tempo:analysis.tempo,
    key:analysis.key,
    meter:analysis.meter,
    sections:analysis.sections,
    cover:$("pdfCover").checked,
    source:analysis.source||"file"
  };
}
async function exportPdf(kind){
  if(!analysis)return;
  const map={score:"pdfScore",chart:"pdfChart",tab:"pdfTab",structure:"pdfStructure"};
  const btn=$(map[kind]);
  btn.disabled=true;
  setExportStatus("A criar o PDF…");
  try{
    const response=await fetch("/api/export",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload(kind))});
    if(!response.ok){
      const raw=await response.text();
      let msg=raw;
      try{const data=JSON.parse(raw);msg=(data.error||"Erro")+(data.detail?` ${data.detail}`:"");}catch{}
      throw new Error(msg);
    }
    const blob=await response.blob();
    const url=URL.createObjectURL(blob);
    const prefixes={score:"Pauta_",chart:"Partitura_Acordes_",tab:"TAB_",structure:"Estrutura_"};
    const a=document.createElement("a");
    a.href=url;
    a.download=(prefixes[kind]||"Score_")+(analysis.title||"Música")+".pdf";
    document.body.appendChild(a);a.click();a.remove();
    setTimeout(()=>URL.revokeObjectURL(url),2000);
    setExportStatus("PDF criado com sucesso.","success");
    toast("PDF pronto");
  }catch(error){setExportStatus(`Erro: ${error.message}`,"error");}
  finally{btn.disabled=(kind==="tab"&&analysis.instrument==="piano");}
}
$("pdfScore").onclick=()=>exportPdf("score");
$("pdfChart").onclick=()=>exportPdf("chart");
$("pdfTab").onclick=()=>exportPdf("tab");
$("pdfStructure").onclick=()=>exportPdf("structure");
