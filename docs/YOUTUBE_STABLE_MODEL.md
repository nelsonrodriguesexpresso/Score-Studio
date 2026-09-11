# Score Studio — Modelo YouTube Estável

Validado em produção em 2026-09-11.

## Base técnica validada

- Python 3.11 slim
- ffmpeg e libsndfile1
- Deno 2.9.6 instalado no container
- `yt-dlp[default]`
- suporte EJS instalado pelo pacote do yt-dlp
- `youtube_source.py` sem forçar `player_client`
- quando existe autenticação, usar apenas o ficheiro de sessão configurado no servidor
- áudio temporário convertido para WAV
- limite de 15 minutos
- playlists desativadas
- timeout de 25 segundos
- 2 tentativas de download e 2 tentativas do extrator

## Regra de estabilidade

Não alterar `youtube_source.py`, `Dockerfile` ou `requirements.txt` em mudanças apenas visuais. O motor YouTube deve ser tratado como componente estável.

## Processo para futuras alterações

1. Criar branch de teste.
2. Testar fora de produção.
3. Confirmar a análise de um vídeo real.
4. Só depois promover para `main`.
5. Evitar redeploys desnecessários do serviço principal quando a mudança é apenas visual.

## Teste de referência

Vídeo usado para validação:

`https://www.youtube.com/watch?v=mGPdWAk8Ag0`

## Produção

Serviço Railway: `score-studio`

Domínio: `https://scorestudiomusic.up.railway.app`

Healthcheck: `/api/health`

## Backup de referência

Branch estável:

`backup/pro-ui-youtube-working-2026-09-11`

Esta branch corresponde ao estado em que a nova interface profissional e o YouTube estavam confirmados a funcionar.

## Combinação que resolveu o problema

`yt-dlp[default] + EJS + Deno 2.9.6 + autenticação de sessão no servidor`

Node 24 não é necessário para esta configuração.
