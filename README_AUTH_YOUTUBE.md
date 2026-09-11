# YouTube autenticado no Score Studio

O Score Studio pode usar um ficheiro `cookies.txt` de uma conta YouTube dedicada sem guardar esse ficheiro no GitHub.

## Variável de ambiente

Definir no Railway:

`YOUTUBE_COOKIES_B64`

O valor deve ser o conteúdo completo do ficheiro `cookies.txt` em formato Netscape, convertido para Base64.

A aplicação descodifica o segredo apenas em runtime para `/tmp/scorestudio-youtube-cookies.txt`, com permissões restritas, e fornece esse ficheiro ao yt-dlp.

## Segurança

- Usar uma conta Google/YouTube dedicada ao Score Studio, não uma conta pessoal.
- Não guardar cookies no repositório.
- Não colocar o valor da variável em logs ou mensagens públicas.
- Se a sessão expirar, gerar um novo `cookies.txt` e substituir apenas o segredo no Railway.
