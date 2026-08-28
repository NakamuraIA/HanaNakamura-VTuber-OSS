# OpenRouter

Data de atualização: Julho 2026

## Não mantemos catálogo local

O OpenRouter tem **centenas de modelos** de dezenas de providers, e o catálogo muda **quase todo dia** — modelos novos entram, outros saem, preços mudam.

Por isso, **não faz sentido** manter uma lista hardcoded aqui. Nós nos conectamos **diretamente no endpoint deles** e o catálogo é buscado em tempo real.

## Endpoint principal (Chat Completions)

```
https://openrouter.ai/api/v1/chat/completions
```

Usamos o **formato OpenAI** (`/v1/chat/completions`) para TODOS os providers. Basta trocar o `base_url` e a `api_key` no SDK da OpenAI.

## Consultar modelos disponíveis

```bash
curl -H "Authorization: Bearer $OPENROUTER_API_KEY" \
  https://openrouter.ai/api/v1/models
```

## Configuração (OpenAI SDK)

```python
from openai import OpenAI

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key="sk-or-v1-...",
)

response = client.chat.completions.create(
    model="qwen/qwen3.7-max",  # formato: provider/model-id
    messages=[{"role": "user", "content": "Hello!"}],
)
```

## Observações

- OpenRouter roteia requisições para o melhor provider disponível.
- Suporta fallback automático se um provider cair.
- Model IDs seguem o formato `provider/model-id` (ex: `openai/gpt-4o`, `anthropic/claude-sonnet-4`, `qwen/qwen3.7-max`).
- Sufixo `:nitro` roteia para o provider mais rápido do modelo.
- Para lista atualizada em tempo real: `GET /v1/models` ou https://openrouter.ai/models
