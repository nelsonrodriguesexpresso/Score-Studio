# Score Studio — ponto de recuperação de 15/09/2026

Cópia da branch main guardada em backup/score-studio-working-2026-09-15 a pedido do utilizador, que confirmou que a aplicação está a funcionar. Esta branch inclui o código e este registo para facilitar updates futuros.

## Aplicação e alojamento

- Aplicação: https://scorestudiomusic.up.railway.app
- Repositório: nelsonrodriguesexpresso/Score-Studio
- Versão indicada na aplicação: 5.5.0.
- Railway projeto: 77723a2c-8533-4013-96e2-39771606cbda
- Ambiente: 601ddf12-e5c5-4d4e-98a6-1452afb40fa8
- Serviço principal: score-studio (6ab44d5c-5247-4a97-a5d1-276ef8997248).
- Deployment verificado: 8bece18c-1e51-4b66-9deb-2d4a980afc93, SUCCESS.
- Commit da correção registado nesta conversa: b4b5287d5e7e630734de8094ded68e561a616ed7 (PR #25).

## Estado e decisões a preservar

- Análise de ficheiros de áudio e de links YouTube; BPM, tonalidade, acordes e estrutura musical; exportação de documentos/PDF.
- Opção de letras removida a pedido do utilizador, após erros de transcrição. Não reintroduzir sem novo pedido.
- Sem separação por pistas e sem adicionar serviços pagos ou aumentar recursos com custos sem autorização.
- Correção recente preserva alterações do ficheiro de cookies durante a execução quando a configuração inicial não muda e impede downloads concorrentes. As mensagens distinguem bloqueio anti-bot de falha de autenticação.
- Evidência de funcionamento: logs Railway de 15/09/2026 às 19:34 UTC mostram download YouTube a 100% e POST /api/analyze-youtube com 200 OK. O utilizador confirmou o funcionamento.
- Esta evidência não garante que todos os vídeos funcionem ou que o YouTube não volte a exigir autenticação.

## Próximos updates

Partir da main atual, consultar este ponto de recuperação e preservar as decisões acima. Validar as alterações relevantes antes de publicar. Não considerar apenas o estado SUCCESS do deployment ou a página inicial como teste completo do YouTube.

Esta cópia guarda código e documentação; não inclui segredos, cookies, variáveis privadas do Railway ou ficheiros temporários enviados pelos utilizadores. Não colocar credenciais no repositório.
