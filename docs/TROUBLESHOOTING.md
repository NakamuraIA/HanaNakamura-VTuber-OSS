# Troubleshooting

## Backend nao responde

Rode:

```powershell
python main.py backend-only
```

Em outro terminal:

```powershell
python main.py healthcheck
```

O backend padrao deve responder em `http://127.0.0.1:8042/api/health`.

## Porta 8042 ou 5173 ja esta em uso

O supervisor atualizado reutiliza servicos saudaveis que ja estao rodando em
`8042` e `5173`, em vez de abrir subprocessos duplicados. Se aparecer um erro
de bind logo depois de uma mensagem de "pronto", provavelmente um terminal
antigo ainda esta executando a versao anterior do supervisor. Feche esse
terminal antigo ou pare o processo Python/Vite preso na porta e rode
`python main.py` novamente.

## Control Panel nao abre

Rode:

```powershell
cd control_panel
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

Ou use o supervisor:

```powershell
python main.py
```

## Chat responde que planner LLM nao esta conectado

Isso significa que o backend novo esta online, mas a etapa de planner/provider
LLM ainda nao foi plugada. O Agent Core deterministico continua respondendo
comandos estruturados como `tools`, `capabilities`, `file.read`,
`file.write`, `memory.search` e `memory.compact`.

## Memoria antiga nao aparece

Correto. A memoria antiga esta fora do runtime ativo. A memoria nova comeca
limpa e usa SQLite/FTS/JSONL.

## VTuber nao conecta

Correto por padrao. VTuber agora e interface/subagente opcional e deve ser
ativado por uma capacidade dedicada.

## RVC aparece ligado, mas o teste usa fallback Edge

`Testar RVC` sempre gera audio base com Edge TTS primeiro. Se o conversor
externo nao estiver configurado ou falhar, o backend toca o audio Edge original
e mostra `rvc_result=fallback` no Terminal Agente.

Antes do teste completo, rode `POST /api/voice/rvc/preflight` para verificar se
o wrapper externo, os caminhos configurados e o FFmpeg estao prontos sem gastar
uma conversao real.

Verifique em `Terminal Agente -> Config`:

- `scriptPath` aponta para o wrapper CLI RVC correto;
- `modelPath` aponta para um modelo `.pth` existente;
- `pythonPath` aponta para o ambiente que possui as dependencias do wrapper;
- `indexPath` e opcional, mas deve existir quando informado;
- FFmpeg esta disponivel se a entrada precisar ser convertida para WAV.

O log do Terminal Agente registra o motivo do fallback em `voice.rvc`.
