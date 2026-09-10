let scoreSourceMode = "file";
const originalAnalyzeHandler = $("go").onclick;
let youtubePreviewTimer = null;
let youtubePreviewData = null;

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

$("sourceFileTab").onclick = () => setSourceMode("file");
$("sourceYoutubeTab").onclick = () => setSourceMode("youtube");

async function loadYoutubePreview(){
  const url=$("youtubeUrl").value.trim();
  if(!url){$("youtubePreview").classList.add("hidden");youtubePreviewData=null;return;}
  $("youtubePreviewBtn").disabled=true;
  $("youtubePreviewBtn").textContent="A ler…";
  const fd=new FormData();
  fd.append("url",url);
  try{
    const response=await fetch("/api/youtube-info",{method:"POST",body:fd});
    const data=await response.json();
    if(!response.ok||!data.ok)throw new Error(data.error||"Não foi possível ler o vídeo.");
    youtubePreviewData=data;
    $("youtubeTitle").textContent=data.title||"Vídeo do YouTube";
    const parts=[];
    if(data.uploader)parts.push(data.uploader);
    if(data.duration)parts.push(formatDuration(data.duration));
    $("youtubeMeta").textContent=parts.join(" · ")||"Pronto para analisar";
    if(data.thumbnail){$("youtubeThumb").src=data.thumbnail;$("youtubeThumb").classList.remove("hidden");}
    else{$("youtubeThumb").classList.add("hidden");}
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

  $("go").disabled = true;
  setStatus("A obter o áudio temporário do YouTube e a preparar a análise.");
  startProgress();
  $("progressText").textContent = "A obter o áudio do YouTube…";

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
    if(!response.ok || !data.ok) throw new Error((data.error || "Erro na análise") + (data.detail ? ` ${data.detail}` : ""));

    analysis = data;
    if(youtubePreviewData){
      analysis.thumbnail=analysis.thumbnail||youtubePreviewData.thumbnail;
      analysis.video_id=analysis.video_id||youtubePreviewData.video_id;
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
    setStatus(`Erro: ${error.message}`, "error");
  }finally{
    $("go").disabled = false;
  }
};

setSourceMode("file");
