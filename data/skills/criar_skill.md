# Criar uma nova skill

Quando o Operador (ou você mesma) perceber que aprendeu um procedimento reutilizável
— baixar música do YouTube, converter um arquivo, um fluxo de pesquisa, etc. — salve
isso como uma **skill** para não reaprender da próxima vez.

## Como criar (jeito certo)

Use a ferramenta **`skill.create`**. Ela grava o arquivo `.md` na SUA pasta de skills
(`data/skills/`) automaticamente. Você não precisa saber nem digitar o caminho.

Argumentos:
- `name`: id curto em minúsculas, com `_` (ex.: `youtube_music_download`)
- `content`: a skill inteira em Markdown — passo a passo, ferramentas usadas e as
  manhas/pegadinhas que você descobriu na prática
- `title` (opcional): título legível
- `overwrite` (opcional): `true` só se quiser substituir uma skill existente de propósito

## Regra importante

NUNCA crie uma skill escrevendo o arquivo com `file.write` num caminho que você
"acha" que é o certo. Pastas como `...\bot_dc\.agent\skills\` pertencem a OUTROS bots
do PC, não a você. Sua única pasta de skills é `data/skills/` — e `skill.create` já
escreve lá sozinha. Se errar o caminho, a skill some e não carrega no seu prompt.

## Estrutura recomendada de uma skill

```
# Título da skill

Para que serve, em uma linha.

## Passo a passo
1. ...
2. ...

## Ferramentas usadas
- ...

## Pegadinhas
- ...
```

## Skill x Script (importante)

- **Skill** (`data/skills/x.md`) = o manual: quando usar, como usar, pegadinhas.
- **Script** (`data/scripts/x.py` ou `.js`/`.ts`/`.ps1`...) = o código que realmente faz.

Quando a tarefa envolve **código reutilizável** (baixar, converter, automatizar),
não remonte o comando toda vez. Crie um **script** com a ferramenta `script.create`
(ele grava em `data/scripts/` sozinho) e rode com `terminal.run`, por exemplo:

```
python data/scripts/youtube_download.py <url>
```

E faça a **skill apontar para o script** — a doc explica, o script executa. Assim você
não erra o comando e reaproveita o que já funcionou.

Igual às skills: NUNCA crie script com `file.write` num caminho chutado. Use
`script.create`. Para ver/ler scripts existentes: `script.list` e `script.read`.

## Depois de criar

A skill nova passa a ser injetada no seu prompt no próximo turno. Conforme for usando
e descobrindo melhorias, use `skill.note` para anexar dicas datadas nela.
