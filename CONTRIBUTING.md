# Como Contribuir

Obrigado por ajudar a melhorar a Hana.

## Antes de começar

1. Leia [README.md](README.md) e [FIRST_RUN.md](FIRST_RUN.md).
2. Procure uma issue (registro de problema) parecida antes de abrir outra.
3. Para mudanças grandes, descreva a proposta antes de implementar.

## Regras básicas

- faça mudanças pequenas e com objetivo claro;
- não misture uma refatoração ampla com uma correção de bug;
- mantenha frontend e backend independentes e comunicando-se pela API;
- escreva documentação técnica em português sempre que possível;
- nunca inclua `.env`, chaves, bancos, registros ou dados pessoais;
- preserve dados existentes e compatibilidade pública, salvo decisão explícita.

## Validação

Para mudanças no backend:

```powershell
python -m pytest backend/tests/ -q
```

Para mudanças no frontend:

```powershell
cd frontend
npm run build
```

Inclua um teste quando a mudança corrigir lógica que possa voltar a quebrar.

## Pull request

Um pull request (pedido de integração) deve informar:

- o problema resolvido;
- o que mudou;
- como foi validado;
- riscos ou testes manuais ainda pendentes.

Use prefixos simples nos commits: `fix:`, `feat:`, `docs:` ou `refactor:`.

