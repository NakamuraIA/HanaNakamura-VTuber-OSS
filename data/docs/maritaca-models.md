# Maritaca AI - Sabiá Models

Data de atualização: Julho 2026

Endpoint: `https://api.maritaca.ai`
API compatível com OpenAI.

Preços em **REAIS (R$)** — Moeda brasileira.

## Modelos Ativos

| Model ID | Contexto | Tools | Preço Input (1M tokens) | Preço Output (1M tokens) | Descrição |
|----------|----------|-------|------------------------|-------------------------|-----------|
| `sabia-4` | 128.000 | ✅ | R$ 5,00 | R$ 20,00 | Modelo mais avançado |
| `sabia-4-thinking` | 128.000 | ✅ | R$ 5,00 | R$ 40,00 | Modelo de raciocínio (thinking) |
| `sabiazinho-4` | 128.000 | ✅ | R$ 1,00 | R$ 4,00 | Modelo mais rápido |

### Inferência 100% no Brasil

Adicione o sufixo `-br-sp` ao model ID para garantir inferência em território nacional (preço ~30% maior):

| Model ID | Preço Input (1M) | Preço Output (1M) |
|----------|-----------------|------------------|
| `sabia-4-br-sp` | R$ 6,50 | R$ 26,00 |
| `sabia-4-thinking-br-sp` | R$ 6,50 | R$ 52,00 |
| `sabiazinho-4-br-sp` | R$ 1,30 | R$ 5,20 |

---

## Funcionalidades

- **Function Calling** ✅ — todas as variantes suportam
- **Visão** ❌ — modelos apenas texto
- **Contexto**: 128K tokens (todos)
- **Especialização**: Português brasileiro, contexto jurídico, educacional e institucional
- **Dados não são usados para treinamento** — descartados após a resposta

---

## Observações

- Modelos especializados em Português e contexto brasileiro.
- Não há modelos de visão/embedding disponíveis via API.
- API compatível com OpenAI (formato `/v1/chat/completions`).
- Documentação completa: https://docs.maritaca.ai
