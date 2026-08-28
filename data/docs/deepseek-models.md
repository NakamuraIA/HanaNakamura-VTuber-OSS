# DeepSeek Models - API Oficial (China)

Data de atualização: Julho 2026

Endpoint: `https://api.deepseek.com`
API compatível com OpenAI e Anthropic.

## Modelos Ativos

| Model ID | Parâmetros (Total / Ativos) | Contexto | Max Output | Thinking Mode | Tools | Preço Input (Cache Miss) | Preço Input (Cache Hit) | Preço Output |
|----------|---------------------------|----------|------------|---------------|-------|------------------------|------------------------|-------------|
| `deepseek-v4-flash` | 284B / 13B | 1.000.000 | 384.000 | ✅ (default) + non-thinking | ✅ | $0.14 | $0.0028 | $0.28 |
| `deepseek-v4-pro` | 1.6T / 49B | 1.000.000 | 384.000 | ✅ + non-thinking | ✅ | $0.435 | $0.003625 | $0.87 |

### Recursos compatíveis (ambos)
- JSON Output ✅
- Tool Calls ✅
- Chat Prefix Completion (Beta) ✅
- FIM Completion (Beta) - modo non-thinking apenas
- Concorrência: Flash = 2500 req, Pro = 500 req

---

## Modelos Depreciados

| Modelo | Depreciação | Substituir por |
|--------|-------------|---------------|
| `deepseek-chat` | **24/07/2026 15:59 UTC** 🔴 | `deepseek-v4-flash` (modo non-thinking) |
| `deepseek-reasoner` | **24/07/2026 15:59 UTC** 🔴 | `deepseek-v4-flash` (modo thinking) |

> `deepseek-chat` e `deepseek-reasoner` nunca foram modelos separados — eram apenas aliases que roteavam para o V4-Flash. Desde 24/07/2026, esses nomes não funcionam mais.

---

## Observações

- DeepSeek só tem **2 modelos** na API oficial (`v4-flash` e `v4-pro`).
- Ambos são open-weight (MIT License) disponíveis no Hugging Face.
- `deepseek-v4-pro` foi lançado em 24/04/2026 como preview.
- `deepseek-v4-flash` é ~3x mais barato que o Pro e suficiente para a maioria dos casos.
- Cache Hit tem desconto massivo (~98% de desconto no input).
- Conteúdo do thinking é retornado no campo `reasoning_content` da resposta (quando em thinking mode).
