# AGENTS.md

Regras de trabalho para agentes Codex neste projeto.

## Projeto ativo

- O workspace principal e `E:\Projeto_Hana_AI`.
- O backend novo fica em `!Hana_Agent_OSS/`.
- O frontend/painel fica em `control_panel/`.
- A pasta legacy `src/` nao deve ser reativada sem decisao explicita.

## Prioridade atual

1. Fazer o nucleo funcional da Hana funcionar primeiro.
2. Manter provider de LLM, STT e TTS separados.
3. Configurar um provider por vez; LLM comeca em Gemini API e STT comeca em Groq Whisper.
4. Evitar implementar recursos grandes antes da base estar estavel.
5. Manter baixa latencia no fluxo de voz e Terminal Agente.

## Regras de edicao

- Sempre ler a estrutura atual antes de alterar arquivos.
- Nao sobrescrever mudancas existentes sem entender de onde vieram.
- Nao reverter alteracoes do usuario sem pedido explicito.
- Usar o padrao existente do projeto antes de criar uma abstracao nova.
- Evitar arquivos grandes demais; se passar de um tamanho dificil de manter, separar em modulos.
- Nao misturar frontend pesado com logica de backend.
- Sempre comentar em Ingles no Python ou Typescript cada modulo ou função para ficar facil do agente entender

## Documentacao obrigatoria

- Sempre que alterar codigo, atualizar a documentacao relacionada.
- Se adicionar feature nova, atualizar `README.md` e docs publicos de uso quando a feature for publica.
- Se remover, renomear ou mudar comportamento, atualizar `README.md` e docs publicos quando afetar o usuario.
- Se a mudanca for interna, registrar em docs privados/status internos, nao em docs publicos.
- Ao final de cada tarefa com alteracao, relatar quais docs foram atualizados.

## Providers

- `providers` de LLM nao sao a mesma coisa que `providers` de STT/TTS.
- LLM principal do Cerebro & Voz e configuracao do Chat devem continuar separadas.
- STT deve ter contrato proprio: audio entra, texto sai.
- TTS deve ter contrato proprio: texto limpo entra, audio sai.
- Provider Gemini inicial deve ser tratado como Gemini API/AI Studio, nao Google Cloud Platform.
- Nao trocar, remover ou substituir modelos de LLM definidos no catalogo do projeto por preferencia do agente.
- Modelos padrao, modelos visiveis na UI e ordem/prioridade dos modelos sao decisoes do usuario.
- Se um modelo parecer invalido, desatualizado ou problemático, o agente deve avisar e explicar o risco antes de qualquer alteracao.

## Terminal Agente

- O Terminal Agente deve registrar o fluxo operacional da Hana:
  - fala/audio do usuario;
  - texto transcrito;
  - pensamento/planejamento quando for exibivel;
  - chamada de ferramenta;
  - resultado de ferramenta;
  - resposta final;
  - texto enviado para TTS;
  - erros e avisos.
- O terminal deve ser leve, copiavel e nao travar com historico grande.
- Nem tudo que aparece no terminal deve ser falado pela TTS.
- Links, codigo, markdown bruto e pontuacao desnecessaria nao devem ser enviados diretamente para TTS.

## STT

- O primeiro STT ativo e `groq_whisper`, usando Groq API com `whisper-large-v3`.
- `gemini_audio` fica como provider STT planejado para audio gravado via Gemini multimodal.
- Gemini Live API deve ser tratado como provider separado no futuro.
- FFmpeg pode ser usado como normalizador/conversor opcional.
- Caminho local conhecido do FFmpeg neste PC:
  - `C:\Ffmpeg\ffmpeg.exe`
- O caminho do FFmpeg deve ser configuravel, nao espalhado pelo codigo.

## MCP e ferramentas

- MCP deve ser tratado como camada de ferramentas, nao como logica central da Hana.
- Ferramentas com acao no PC precisam de permissao/controle antes de execucao sensivel.
- Nao conectar acoes destrutivas sem confirmacao explicita.

## Validacao

Quando alterar backend/frontend, validar conforme o escopo:

- Backend Python:
  - `python -m compileall main.py !Hana_Agent_OSS/src`
  - testes Python aplicaveis
- Frontend:
  - `npm run build` em `control_panel/`
- Tauri:
  - `cargo check` em `control_panel/src-tauri/`
- UI:
  - quando alterar tela, abrir e conferir visualmente quando possivel.

## Git

- A arvore pode estar suja por migracoes em andamento.
- Nao limpar, resetar ou descartar arquivos sem pedido explicito.
- Nao assumir que toda mudanca atual foi feita pelo agente atual.
- Se o usuario pedir novo repositorio, preparar sem empurrar codigo para remoto antigo.

## Relatorio final

Ao terminar uma tarefa, informar:

- o que foi feito;
- arquivos alterados;
- antes/depois;
- validacoes executadas;
- riscos ou pontos abertos;
- documentacao atualizada.
