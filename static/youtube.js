let scoreSourceMode = "file";
const originalAnalyzeHandler = $("go").onclick;

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

$("youtubeUrl").addEventListener("keydown", event => {
  if(event.key === "Enter"){
    event.preventDefault();
    $("go").click();
  }
});

$("go").onclick = async () => {
  if(scoreSourceMode === "file"){
    return originalAnalyzeHandler();
  }

  const url = $("youtubeUrl").value.trim();
  if(!url){
    setStatus("Cola primeiro um link do YouTube.", "error");
    return;
  }

  $("go").disabled = true;
  setStatus("A obter o áudio do YouTube e a preparar a análise.");
  startProgress();
  $("progressText").textContent = "A obter o áudio do YouTube…";

  const fd = new FormData();
  fd.append("url", url);
  fd.append("instrument", $("instrument").value);

  try{
    const response = await fetch("/api/analyze-youtube", {method:"POST", body:fd});
    const raw = await response.text();
    let data;
    try{ data = JSON.parse(raw); }
    catch{ throw new Error(`Resposta inválida do servidor: ${raw.substring(0,160)}`); }

    if(!response.ok || !data.ok){
      throw new Error((data.error || "Erro na análise") + (data.detail ? ` ${data.detail}` : ""));
    }

    analysis = data;
    populateReview();
    finishProgress();
    setStatus("Análise concluída a partir do YouTube. Revê agora os resultados.", "success");
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
