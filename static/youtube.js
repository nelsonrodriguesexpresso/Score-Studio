let scoreSourceMode = "file";
const originalAnalyzeHandler = $("go").onclick;
let youtubePreviewTimer = null;
let youtubePreviewData = null;

function ensureYoutubeFallback(){
  if($("youtubeFallback")) return;
  const style=document.createElement("style");
  style.textContent=`
    .youtube-fallback{margin-top:10px;border:1px solid #6b3e2f;background:#241813;border-radius:12px;padding:13px;display:flex;align-items:center;justify-content:space-between;gap:14px}
    .youtube-fallback strong,.youtube-fallback span{display:block}.youtube-fallback strong{font-size:11px;color:#ffd2bd}.youtube-fallback span{font-size:9px;line-height:1.5;color:#cda89a;margin-top:4px}
    .youtube-fallback .btn{flex:0 0 auto}
    @media(max-width:650px){.youtube-fallback{align-items:stretch;flex-direction:column}.youtube-fallback .btn{width:100%}}
  `;
  document.head.appendChild(style);

  const box=document.createElement("div");
  box.id="youtubeFallback";
  box.className="youtube-fallback hidden";
  box.innerHTML=`<div><strong>O YouTube bloqueou a leitura automática do áudio</strong><span id="youtubeFallbackText">Podes continuar carregando o ficheiro de áudio diretamente.</span></div><button id="useFileFallback" type="button" class="btn btn-primary">Carregar ficheiro</button>`;
  $("youtubePreview").insertAdjacentElement("afterend",box);
  $("useFileFallback").onclick=()=>{
    setSourceMode("file");
    setStatus("Escolhe o ficheiro MP3, WAV, M4A, FLAC ou OGG para continuar.");
    $("audio").click();
  };

  const help=document.querySelector(".youtube-help");
  if(help){
    help.textContent="Vídeos até 10 minutos. A pré-visualização pode funcionar mesmo quando o YouTube bloqueia a leitura automática do áudio. Nesse caso podes carregar o ficheiro diretamente.";
  }
}

function showYoutubeFallback(message){
  ensureYoutubeFallback();
  $("youtubeFallbackText").textContent=message||"Podes continuar carregando o ficheiro de áudio diretamente.";
  $("youtubeFallback").classList.remove("hidden");
}

function hideYoutubeFallback(){
  const box=$("youtubeFallback");
  if(box) box.classList.add("hidden");
}

function looksLikeYoutubeAccessBlock(message){
  const value=String(message||"").toLowerCase();
  return value.includes("bloqueou o acesso automático") ||
         value.includes("não ficou disponível para análise automática") ||
         value.includes("não ficou disponível para análise") ||
         value.includes("confirm you're not a bot") ||
         value.includes("confirm you’re not a bot");
}

function setSourceMode(mode){
  scoreSourceMode = mode;
  const isFile = mode === "file";
  $("sourceFileTab").classList.toggle("active", isFile);
  $("sourceYoutubeTab").classList.toggle("active", !isFile);
  $("fileSourcePane").classList.toggle("hidden", !isFile);
  $("youtubeSourcePane").classList.toggle("hidden", isFile);
  if(isFile){
    if(selectedFile) $("audioPreview").classList.remove("hidden");
  }else{
    $("audioPreview").classList.add("hidden");
  }
  $("status").classList.add("hidden");
}

ensureYoutubeFallback();
$("sourceFileTab").onclick = () => setSourceMode("file");
$("sourceYoutubeTab").onclick = () => setSourceMode("youtube");

async function loadYoutubePreview(){
  const url=$("youtubeUrl").value.trim();
  if(!url){
    $("youtubePreview").classList.add("hidden");
    youtubePreviewData=null;
    hideYoutubeFallback();
    return;
  }
  hideYoutubeFallback();
  $("youtubePreviewBtn").disabled=true;
  $("youtubePreviewBtn").textContent="A ler…";
  const fd=new FormData();
  fd.append("url",url);
  try{
    const response=await fetch("/api/youtube-info",{method:"POST",body:fd});
    const raw=await response.text();
    let data;
    try{data=JSON.parse(raw);}catch{throw new Error("Não foi possível interpretar a resposta do YouTube.");}
    if(!response.ok||!data.ok)throw new Error(data.error||"Não foi possível ler o vídeo.");
    youtubePreviewData=data;
    $("youtubeTitle").textContent=data.title||"Vídeo do YouTube";
    const parts=[];
    if(data.uploader)parts.push(data.uploader);
    if(data.duration)parts.push(formatDuration(data.duration));
    if(!parts.length)parts.push("Pré-visualização disponível");
    $("youtubeMeta").textContent=parts.join(" · ");
    if(data.thumbnail){
      $("youtubeThumb").src=data.thumbnail;
      $("youtubeThumb").classList.remove("hidden");
    }else{
      $("youtubeThumb").classList.add("hidden");
    }
    $("youtubePreview").classList.remove("hidden");
    $("status").classList.add("hidden");
  }catch(error){
    youtubePreviewData=null;
    $("youtubePreview").classList.add("hidden");
    setStatus(`YouTube: ${error.message}`,"error");
  }finally{
    $("youtubePreviewBtn").disabled=false;
    $("youtubePreviewBtn").textContent="Pré-visualizar";
  }
}

$("youtubePreviewBtn").onclick=loadYoutubePreview;
$("youtubeUrl").addEventListener("input",()=>{
  clearTimeout(youtubePreviewTimer);
  hideYoutubeFallback();
  youtubePreviewTimer=setTimeout(loadYoutubePreview,900);
});
$("youtubeUrl").addEventListener("keydown", event => {
  if(event.key === "Enter"){
    event.preventDefault();
    $("go").click();
  }
});

$("go").onclick = async () => {
  if(scoreSourceMode === "file") return originalAnalyzeHandler();

  const url = $("youtubeUrl").value.trim();
  if(!url){setStatus("Cola primeiro um link do YouTube.", "error");return;}
  if(!rightsOk())return;

  hideYoutubeFallback();
  $("go").disabled = true;
  setStatus("A tentar obter o áudio temporário do YouTube para análise.");
  startProgress();
  $("progressText").textContent = "A tentar obter o áudio do YouTube…";

  const fd = new FormData();
  fd.append("url", url);
  fd.append("instrument", $("instrument").value);
  fd.append("rights_confirmed","true");

  try{
    const response = await fetch("/api/analyze-youtube", {method:"POST", body:fd});
    const raw = await response.text();
    let data;
    try{ data = JSON.parse(raw); }
    catch{ throw new Error(`Resposta inválida do servidor: ${raw.substring(0,160)}`); }

    if(!response.ok || !data.ok){
      const message=(data.error || "Erro na análise") + (data.detail ? ` ${data.detail}` : "");
      if(looksLikeYoutubeAccessBlock(message)){
        showYoutubeFallback(data.error || "O YouTube não disponibilizou o áudio ao servidor. Carrega o ficheiro para continuar.");
      }
      throw new Error(message);
    }

    analysis = data;
    if(youtubePreviewData){
      analysis.thumbnail=analysis.thumbnail||youtubePreviewData.thumbnail;
      analysis.video_id=analysis.video_id||youtubePreviewData.video_id;
      analysis.artist=analysis.artist||youtubePreviewData.uploader||"";
    }
    populateReview();
    finishProgress();
    setStatus("Análise concluída a partir do YouTube. Revê agora acordes e notas.", "success");
    $("reviewCard").classList.remove("hidden");
    $("exportCard").classList.remove("hidden");
    setActiveStep(2);
    setTimeout(() => $("reviewCard").scrollIntoView({behavior:"smooth", block:"start"}), 250);
  }catch(error){
    failProgress();
    if(looksLikeYoutubeAccessBlock(error.message)){
      setStatus("O vídeo foi reconhecido, mas o YouTube bloqueou o acesso automático ao áudio neste servidor. Usa o botão ‘Carregar ficheiro’ para continuar.","error");
    }else{
      setStatus(`Erro: ${error.message}`, "error");
    }
  }finally{
    $("go").disabled = false;
  }
};

setSourceMode("file");
