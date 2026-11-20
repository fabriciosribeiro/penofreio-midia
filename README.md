# penofreio-midia

Imagens aprovadas do Instagram do Pé no Freio e o robô que as publica na hora marcada.

- `fila.json`: um item por post (`quando`, `imagem`, `legenda`, `alt`, `ia`, `publicado`).
- `imagens/`: o JPEG de cada post (1080 × 1350). O repositório é público porque a API do Instagram busca a imagem por
  um link aberto; só entra aqui o que já foi aprovado para publicar.
- `.github/workflows/publicar.yml`: roda a cada 15 minutos e publica no máximo um post vencido por vez. Rodando à
  mão, o modo `teste` prepara o próximo post sem publicar.

O token do Instagram fica nos segredos do repositório (Settings → Secrets and variables → Actions) e nunca aparece
no código nem nos registros. A produção dos posts acontece no repositório privado de marketing.
