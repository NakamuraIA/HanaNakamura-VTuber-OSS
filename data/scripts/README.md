# Scripts da Hana

Código executável reutilizável que a Hana cria pra si mesma (Python, JS, TS, etc.).

- A Hana cria scripts aqui com a ferramenta `script.create` (nunca com `file.write`
  num caminho chutado).
- Ela roda os scripts com `terminal.run`, ex.: `python data/scripts/<nome>.py`.
- As **skills** (`data/skills/*.md`) são os manuais que apontam para estes scripts.
