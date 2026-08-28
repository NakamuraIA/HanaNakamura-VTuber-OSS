# Aula 1 — Como uma mensagem atravessa a Hana

Este documento é um mapa inicial. Ele não afirma que tudo está perfeito: cada
etapa será confirmada com testes.

## A separação principal

```text
frontend (tela React/Tauri)
        │ HTTP e WebSocket
        ▼
backend (Python/FastAPI)
        │
        ├── memória e configurações no SQLite
        ├── provedor de modelo (Groq, OpenRouter, Gemini etc.)
        └── ferramentas locais, voz, imagem e Discord
```

O frontend não importa arquivos Python. Ele chama a API. Por isso, podemos
trocar o frontend sem reescrever o backend, desde que o novo frontend respeite
as mesmas rotas e mensagens.

## Fluxo de uma mensagem comum

1. `frontend/src/api/chat.ts` abre o WebSocket `WS /ws/chat` e envia um JSON
   com texto, histórico, provedor, modelo e anexos.
2. `backend/api/routers/chat.py` aceita a conexão e encaminha o JSON para
   `backend/api/services/chat.py`.
3. `handle_chat_payload()` decide se é conversa comum ou modo agente.
4. `run_text_turn()` monta o contexto: persona, histórico, memórias relevantes,
   anexos e configurações.
5. `ProviderSelector` chama o provedor escolhido. Quando há transmissão ao
   vivo, o backend envia partes da resposta; no fim, envia o texto limpo.
6. A resposta é gravada na memória e o frontend recebe eventos como `chunk`
   (pedaço), `final` (texto final), `meta` (informações), `media` (mídia) e
   `done` (terminou).

## Fluxo do Agent Core

Quando a mensagem pede uma ferramenta, `HanaAgentCore.run()` cria um
`AgentRequest` (pedido do agente), carrega o contexto, chama o `planner`
(planejador), executa a ferramenta e passa o resultado pelo `verifier`
(verificador). O resultado vira um `AgentResponse` (resposta do agente).

```text
pedido → planner (planeja) → executor (executa) → verifier (confere) → resposta
```

## Onde os dados são salvos

- `runtime/hana_memory.sqlite3`: memória curta, memória longa, memória fixa,
  configurações, modelos, histórico e tabelas internas do Agent Core.
- `runtime/hana_events.jsonl`: eventos recentes de canais, como terminal e voz.

`backend/paths.py` é o `paths` (caminhos): concentra os endereços para evitar
que cada arquivo invente seu próprio caminho. `runtime` significa “ambiente de
execução”: a pasta onde a Hana guarda dados que surgem enquanto ela funciona.

## Pequeno dicionário

- `API`: forma organizada de um programa conversar com outro.
- `endpoint`: endereço específico da API, por exemplo `/api/chat/history`.
- `WebSocket`: conexão que fica aberta para enviar eventos em tempo real.
- `provider`: provedor do modelo de IA.
- `storage`: armazenamento; código que salva e lê dados.
- `protocol`: protocolo; formatos e objetos combinados entre partes do sistema.
- `client`: cliente; programa que faz a chamada. O frontend é cliente do backend.
- `pinned`: fixado; uma memória marcada para ter prioridade.
- `__main__.py`: arquivo usado quando um pacote Python é executado diretamente.
- `main.py`: arquivo que normalmente concentra uma entrada de execução; aqui ele
  encaminha a inicialização para `backend.api.server`.

## Próxima aula e teste

O próximo passo é abrir as tabelas SQLite, registrar suas colunas e executar um
teste pequeno de salvar, buscar, fixar, atualizar e apagar uma memória. Depois
vamos comparar o resultado do SQL com o que a API promete.
