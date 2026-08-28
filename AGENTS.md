# Repository Guidelines

Este arquivo orienta agentes e contribuidores. A documentação técnica deve ser
escrita em português sempre que possível; na primeira ocorrência de um termo em
inglês, inclua o significado em português.

## Estrutura do Projeto

Hana é dividida em um backend Python e um frontend React/Tauri. O backend é a
raiz independente de `backend/`: `api/` contém rotas e serviços FastAPI,
`core/` coordena a execução, `providers/` integra modelos de IA (com
`provider_aliases.py` como mapa único de apelidos de provider), `memory/`
gerencia persistência, `modules/` reúne voz, visão e lembretes, `catalog/`
mantém o catálogo de modelos LLM/TTS/STT servido pelo banco, `bd/` cria as
tabelas por domínio (llm/tts/stt), `tools/` reúne as ferramentas que a IA pode
chamar (arquivo, terminal, teclado/mouse etc.), `mcp/` conecta servidores MCP
externos, `discord_bot/` roda o bot do Discord que consome este backend e
`persona/` guarda prompts e perfil da Hana. Scripts avulsos ficam em
`backend/scripts/`; testes ficam em `backend/tests/`. O frontend é a raiz
independente de `frontend/`, com código em `frontend/src/` e imagens em
`frontend/public/`. A URL do backend é lida da variável `VITE_BACKEND_URL`
(veja `frontend/.env.example`). Scripts, habilidades e imagens compartilhadas
ficam em `data/`; contratos ficam em `backend/docs/`.

Não misture frontend e backend. Eles se comunicam por API HTTP/WebSocket e
devem continuar capazes de ser publicados separadamente.

## Comandos Principais

Na raiz:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r backend/requirements.txt
```

Dentro de `backend/`, rode `uvicorn main:app --reload --port 8042`. Dentro de
`frontend/`, use `npm install`, `npm run dev` e `npm run build`. Para o aplicativo
desktop, use `npm run tauri dev` ou `npm run tauri build`. No Windows,
`Hana.cmd` inicia e `Desligar-Hana.cmd` encerra a aplicação.

## Estilo e Testes

Use quatro espaços no Python, `snake_case` para Python e `PascalCase` para
componentes React. Prefira tipos explícitos no TypeScript e evite `any` sem
necessidade. Comente funções difíceis de entender. Execute
`python -m pytest backend/tests/ -q` e coloque novos testes em `backend/tests/`
com nomes `test_*.py`. Para o frontend, execute `npm run build`.

## Modo de Colaboração

O objetivo é entender e validar o sistema antes de publicá-lo. Trabalhe em
etapas pequenas; explique uma coisa por vez; traduza termos técnicos; confirme
nomes quando a transcrição de voz parecer incorreta; e não dependa de ortografia
ou pontuação perfeitas para entender a intenção. Registre descobertas em
`backend/docs/` com exemplos simples: entradas, chamadas, dados salvos e
respostas. Não presuma que uma função funciona só porque existe: leia, teste e
registre o resultado.

## Segurança e Commits

Nunca envie `.env`, chaves, tokens, bancos locais ou dados de runtime. Use
`.env.example`. Revise CORS, autenticação e permissões antes de publicar. Use
prefixos de commit como `feat:`, `fix:` e `docs:`. Não faça commit sem
autorização explícita.
