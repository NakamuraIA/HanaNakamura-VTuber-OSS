# Skill: Omni Result Review

Use esta skill depois que `omni_supervise` retornar.

## Interpretacao

- `ok=false`: a ponte falhou ou o Omni recusou; mostre o `error` real e nao invente causa.
- `completion_status="running"` ou retorno com `job_id`: o Omni apenas iniciou um job em background; nao trate como conclusao.
- `completion_status="done"`: considere concluido somente se houver evidencia suficiente.
- `completion_status="needs_review"`: explique que ainda precisa revisao ou nova rodada; nao diga que terminou.
- `completion_status="blocked"`: explique o bloqueio real e qual informacao ou acao humana falta.

## Como Responder

- Resuma o resultado em linguagem clara para Nakamura.
- Mostre evidencias concretas quando a tarefa for tecnica.
- Se o erro for de schema, HTTP, timeout, Omni indisponivel ou permissao, preserve o texto real.
- Se o job foi apenas iniciado, informe que o relatorio final ficara no Terminal Agent e continue a conversa normalmente.
- Se o resultado nao atender `acceptance`, diga exatamente o que faltou.

## Limites

- Nao transformar erro real em desculpa generica.
- Nao dizer que editou, criou, apagou ou validou algo sem evidencia no retorno.
- Nao chamar Omni de novo em loop se a tarefa ficou ambigua ou bloqueada por falta de decisao humana.
