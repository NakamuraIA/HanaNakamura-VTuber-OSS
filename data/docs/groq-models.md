# Groq Models - GroqCloud

Data de atualização: Julho 2026

## Modelos Ativos (Produção)

| Model ID | Contexto | Visão | Tools | Preço Input (1M) | Preço Output (1M) | Velocidade |
|----------|----------|-------|-------|------------------|-------------------|------------|
| `openai/gpt-oss-120b` | 131.072 | ❌ | ✅ browser search, code execution | $0.15 | $0.60 | ~500 t/s |
| `openai/gpt-oss-20b` | 131.072 | ❌ | ✅ | $0.075 | $0.30 | ~1000 t/s |
| `whisper-large-v3` | STT | — | — | $0.111/hora | — | — |
| `whisper-large-v3-turbo` | STT | — | — | $0.04/hora | — | — |

## Sistemas (Produção)

| Model ID | Contexto | Preço | Velocidade | Recursos |
|----------|----------|-------|------------|----------|
| `groq/compound` | 131.072 | Grátis | ~450 t/s | Web search, code execution, multi-step reasoning |
| `groq/compound-mini` | 131.072 | Grátis | ~450 t/s | Web search, code execution, multi-step reasoning |

## Modelos Preview (não produção)

| Model ID | Contexto | Visão | Tools | Preço Input (1M) | Preço Output (1M) | Velocidade |
|----------|----------|-------|-------|------------------|-------------------|------------|
| `qwen/qwen3.6-27b` | 131.072 | ✅ img | ✅ | $0.60 | $3.00 | ~500 t/s |
| `canopylabs/orpheus-v1-english` | TTS | — | — | $22.00/1M caracteres | — | — |
| `canopylabs/orpheus-arabic-saudi` | TTS | — | — | $40.00/1M caracteres | — | — |
| `openai/gpt-oss-safeguard-20b` | 131.072 | ❌ | ✅ content moderation | $0.075 | $0.30 | ~1000 t/s |
| `minimaxai/minimax-m2.7` | 196.608 | ❌ | ✅ enterprise | Enterprise | Enterprise | ~260 t/s |
| `meta-llama/llama-prompt-guard-2-22m` | 512 | ❌ | ❌ | $0.03 | $0.03 | — |
| `meta-llama/llama-prompt-guard-2-86m` | 512 | ❌ | ❌ | $0.04 | $0.04 | — |

---

## Modelos em Depreciação

### Shutdown em 16/08/2026

| Modelo | Substituir por |
|--------|---------------|
| `llama-3.1-8b-instant` | `openai/gpt-oss-20b` |
| `llama-3.3-70b-versatile` | `openai/gpt-oss-120b` ou `qwen/qwen3.6-27b` |

### Shutdown em 17/07/2026

| Modelo | Substituir por |
|--------|---------------|
| `qwen/qwen3-32b` | `openai/gpt-oss-120b` |
| `meta-llama/llama-4-scout-17b-16e-instruct` | `openai/gpt-oss-120b` ou `qwen/qwen3.6-27b` |

### Shutdown em 15/04/2026

| Modelo | Substituir por |
|--------|---------------|
| `moonshotai/kimi-k2-instruct-0905` | `openai/gpt-oss-120b` |

### Shutdown em 09/03/2026

| Modelo | Substituir por |
|--------|---------------|
| `meta-llama/llama-4-maverick-17b-128e-instruct` | `openai/gpt-oss-120b` |

### Shutdown em 05/03/2026

| Modelo | Substituir por |
|--------|---------------|
| `meta-llama/llama-guard-4-12b` | `openai/gpt-oss-safeguard-20b` |

### Shutdown em 31/12/2025

| Modelo | Substituir por |
|--------|---------------|
| `playai-tts` | `canopylabs/orpheus-v1-english` |
| `playai-tts-arabic` | `canopylabs/orpheus-arabic-saudi` |

### Shutdown outubro 2025

| Modelo | Shutdown | Substituir por |
|--------|----------|---------------|
| `moonshotai/kimi-k2-instruct` | 10/10/25 | `openai/gpt-oss-120b` |
| `gemma2-9b-it` | 08/10/25 | `llama-3.1-8b-instant` |
| `deepseek-r1-distill-llama-70b` | 02/10/25 | `llama-3.3-70b-versatile` ou `openai/gpt-oss-120b` |

### Shutdown agosto 2025

| Modelo | Shutdown | Substituir por |
|--------|----------|---------------|
| `llama3-70b-8192` | 30/08/25 | `llama-3.3-70b-versatile` |
| `llama3-8b-8192` | 30/08/25 | `llama-3.1-8b-instant` |
| `distil-whisper-large-v3-en` | 23/08/25 | `whisper-large-v3-turbo` |

### Shutdown julho 2025

| Modelo | Shutdown | Substituir por |
|--------|----------|---------------|
| `mistral-saba-24b` | 30/07/25 | `qwen/qwen3-32b` |
| `qwen-qwq-32b` | 14/07/25 | `qwen/qwen3-32b` |

### Shutdown abril 2025 (vários)

| Modelo | Substituir por |
|--------|---------------|
| `llama-3.2-1b-preview` | `llama-3.1-8b-instant` |
| `llama-3.2-3b-preview` | `llama-3.1-8b-instant` |
| `llama-3.2-11b-vision-preview` | `meta-llama/llama-4-scout-17b-16e-instruct` |
| `llama-3.2-90b-vision-preview` | `meta-llama/llama-4-scout-17b-16e-instruct` |
| `deepseek-r1-distill-qwen-32b` | `qwen-qwq-32b` |
| `qwen-2.5-32b` | `qwen-qwq-32b` |
| `qwen-2.5-coder-32b` | `qwen-qwq-32b` / `openai/gpt-oss-120b` |
| `llama-3.3-70b-specdec` | `llama-3.3-70b-versatile` |
| `deepseek-r1-distill-llama-70b-specdec` | `deepseek-r1-distill-llama-70b` |

### Depreciações mais antigas (2024)

| Modelo | Shutdown | Substituir por |
|--------|----------|---------------|
| `mixtral-8x7b-32768` | 20/03/25 | `llama-3.3-70b-versatile` |
| `llama-3.1-70b-versatile` | 24/01/25 | `llama-3.3-70b-versatile` |
| `llama-3.1-70b-specdec` | 24/01/25 | `llama-3.3-70b-specdec` |
| `llama3-groq-8b-8192-tool-use-preview` | 06/01/25 | `llama-3.3-70b-versatile` |
| `llama3-groq-70b-8192-tool-use-preview` | 06/01/25 | `llama-3.3-70b-versatile` |
| `gemma-7b-it` | 18/12/24 | `gemma2-9b-it` |
| `llama-3.2-90b-text-preview` | 25/11/24 | `llama-3.2-90b-vision-preview` |
| `llava-v1.5-7b-4096-preview` | 28/10/24 | `llama-3.2-11b-vision-preview` |
| `llama-3.2-11b-text-preview` | 28/10/24 | `llama-3.2-11b-vision-preview` |

---

## Observações

- `llama-3.1-8b-instant` e `llama-3.3-70b-versatile` são oficialmente **deprecados** (shutdown 16/08/2026). A Groq está migrando todo mundo pro GPT-OSS.
- O endpoint da Groq é compatível com OpenAI: `https://api.groq.com/openai/v1`
- Planos: Developer (free com rate limits) e Enterprise (committed-spend, sem deprecações forçadas).
- Preview models podem ser descontinuados a qualquer momento sem aviso prévio.
