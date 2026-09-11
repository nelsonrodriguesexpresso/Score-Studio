# Score Studio — Audio por pistas (v1)

Objetivo: adicionar separação opcional do áudio em quatro pistas sem alterar o motor estável de obtenção de áudio do YouTube.

Pistas previstas:
- Voz
- Baixo
- Bateria
- Outros

Princípios:
- A separação acontece apenas depois de o áudio já estar disponível no servidor.
- O ficheiro `youtube_source.py` não deve ser alterado por esta funcionalidade.
- A separação é opcional e só é executada quando o utilizador ativa “Separar áudio por pistas”.
- As pistas são temporárias e eliminadas automaticamente.
- A primeira implementação deve ser validada num serviço de teste antes de qualquer promoção para produção.
