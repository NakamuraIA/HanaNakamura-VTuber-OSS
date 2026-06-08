# Skill: Omni Decision Policy

Use esta skill para decidir se a Hana deve chamar o Omni ou responder sozinha.

## Quando Usar Omni

- Tarefas de computador local, processos, janelas, clipboard, OCR, arquivos locais ou automacao do PC.
- Inspecao de projeto, estrutura de pastas, logs locais, ambiente local ou status de processo.
- Acoes concretas no computador que Nakamura pediu explicitamente.
- Revisao de algo que Omni ja fez ou de uma execucao local que precisa de evidencia.
- Cancelamento de job Omni somente quando Nakamura pedir explicitamente para parar/cancelar/abortar; nesse caso use `agent_job_cancel`.

## Quando Nao Usar Omni

- Chat normal, opiniao, conversa casual, personalidade ou explicacao simples.
- TTS, STT, voz, imagem, prompts de imagem, web search, RAG ou configuracao que a Hana ja controla diretamente.
- Perguntas que podem ser respondidas com o contexto atual sem acessar o computador.
- Pedidos ambiguos que nao deixam claro qual maquina, pasta ou acao local deve ser usada.

## Escolha de Modo

- Use `mode="inspect"` para verificar, listar, diagnosticar, inspecionar ou quando Nakamura disser "sem editar nada".
- Use `mode="execute"` para executar uma acao concreta pedida por Nakamura.
- Use `mode="review"` para validar resultado anterior, revisar trabalho feito ou procurar defeito sem alterar automaticamente.
