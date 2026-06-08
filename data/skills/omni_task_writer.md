# Skill: Omni Task Writer

Use esta skill para escrever chamadas `omni_supervise(task, mode, acceptance, max_rounds)` claras e previsiveis.

## Como Escrever `task`

- Comece com o objetivo final em uma frase objetiva.
- Inclua caminho alvo completo quando existir.
- Inclua restricoes como "sem editar nada", "nao apagar arquivos", "nao tocar em .env" ou "somente inspecao".
- Diga quais evidencias o Omni deve devolver.
- Diga que o relatorio deve voltar para a Hana revisar antes de responder ao Nakamura.

## Como Escrever `acceptance`

- `acceptance` deve ser texto simples, nunca array/lista JSON.
- Use criterios separados por ponto e virgula.
- Inclua a condicao de sucesso e a evidencia minima.
- Exemplo: `relatar 5 riscos com caminhos; nao editar arquivos; citar comandos ou arquivos inspecionados`.

## Boas Praticas

- Para inspecao, use `max_rounds=1` ou `max_rounds=2` quando a tarefa puder precisar de uma rodada de correcao.
- Para execucao, use criterios de aceite que permitam saber se a acao realmente terminou.
- Para revisao, inclua o que foi feito antes e o que deve ser verificado.
