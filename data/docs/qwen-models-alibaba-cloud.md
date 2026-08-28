# Qwen Models - Alibaba Cloud (DashScope / Model Studio)

Data de atualização: Agosto 2026

> Fontes: [QwenCloud — Text generation models e Pricing](https://docs.qwencloud.com/developer-guides/getting-started/text-generation-models)
> e [Alibaba Cloud Model Studio — modelos, preços e limites](https://www.alibabacloud.com/help/en/model-studio/models).
> Preços em USD por 1M de tokens. Muitos modelos têm desconto promocional
> (fora de pico/noturno) — os valores abaixo são os preços de tabela (list price).

## Modelos Ativos (Recomendados)

### Texto

| Model ID | Contexto | Visão | Tools | Preço Input (1M) | Preço Output (1M) |
|----------|----------|-------|-------|------------------|-------------------|
| `qwen3.8-max` | 1.000.000 | ❌ | ✅ | $2.50 | $7.50 |
| `qwen3.7-max` | 1.000.000 | ❌ | ✅ | $2.50 | $7.50 |
| `qwen3.7-plus` | 1.000.000 | ✅ (img+video) | ✅ | $0.40 (≤256K) / $1.20 (256K–1M) | $1.60 (≤256K) / $4.80 (256K–1M) |
| `qwen3.7-flash` | 1.000.000 | ✅ (img+video) | ✅ | $0.03 (≤32K) / $0.10 (32–256K) / $0.20 (256K–1M) | $0.13 / $0.40 / $0.80 |
| `qwen3.6-max-preview` | 262.144 | ❌ | ✅ | $1.30 (≤128K) / $2.00 (128–256K) | $7.80 / $12.00 |
| `qwen3.6-plus` | 1.000.000 | ✅ | ✅ | $0.50 (≤256K) / $2.00 (256K–1M) | $3.00 / $6.00 |
| `qwen3.6-flash` | 1.000.000 | ✅ (img+video) | ✅ | $0.25 (≤256K) / $1.00 (256K–1M) | $1.50 / $4.00 |
| `qwen3.5-plus` | 1.000.000 | ✅ | ✅ | $0.40 (≤256K) / $0.50 (256K–1M) | $2.40 / $3.00 |
| `qwen3.5-flash` | 1.000.000 | ✅ | ✅ | $0.10 | $0.40 |
| `qwen-plus` (alias estável) | 1.000.000 | ❌ | ✅ | $0.40 (≤256K) / $1.20 (256K–1M) | $4.00 / $12.00 |
| `qwen-flash` (alias estável) | 1.000.000 | ❌ | ✅ | $0.05 (≤256K) / $0.25 (256K–1M) | $0.40 / $2.00 |
| `qwen-long` | 10.000.000 | ❌ | ✅ | N/D | N/D |

Notas:
- `qwen3.7-max` é texto-only (input text). Já o snapshot `qwen3.7-max-2026-06-08`
  adiciona entendimento visual multimodal (percepção de cenários reais).
- `qwen3.7-plus` e `qwen3.7-flash` são os modelos de texto/visão recomendados.
- Thinking mode: suportado por todos os Qwen3+ (híbridos — alternáveis por pedido).
- Entradas de imagem/vídeo são convertidas em tokens (~1 token por 32×32 px).

### Omni / Multimodal

| Model ID | Modalidades | Input (1M) | Output (1M) |
|----------|-------------|------------|-------------|
| `qwen3.5-omni-plus` | Texto, Imagem, Áudio, Vídeo | $1.40 (texto/img/vídeo) / $11.00 (áudio) | $8.30 (texto) / $44.00 (texto+áudio) |
| `qwen3.5-omni-plus-realtime` | Tempo real (WS), fala-fala, vídeo | $2.10 / $16.50 (áudio) | $12.40 / $62.00 |

### VL (Visão-Linguagem)

| Model ID | Contexto | Preço Input (1M) | Preço Output (1M) |
|----------|----------|------------------|-------------------|
| `qwen3-vl-plus` | 262.144 | $0.20 (≤32K) / $0.30 (32–128K) / $0.60 (128–256K) | $1.60 / $2.40 / $4.80 |
| `qwen3-vl-flash` | 262.144 | $0.05 (≤32K) / $0.075 (32–128K) / $0.12 (128–256K) | $0.40 / $0.60 / $0.96 |

Entrada de imagem/vídeo → saída de texto (image-to-text). Modelos `qwen2.5-vl-*`
(de código aberto) entraram na lista "Legacy" — ver seção descontinuados.

### Embeddings & Rerank

| Model ID | Tipo | Preço (1M) |
|----------|------|------------|
| `text-embedding-v4` | Embeddings (texto; saída grátis) | $0.07 |
| `tongyi-embedding-vision-plus` | Embeddings multimodais (img/vídeo) | $0.09 |
| `qwen3-rerank` | Reranking (texto) | $0.10 |

### Imagem / Vídeo (Qwen)

| Model ID | Tipo |
|----------|------|
| `qwen-image-2.0-pro` | Geração multimodal (unifica geração e edição) |

---

## Família DeepSeek (disponível via Alibaba Model Studio / QwenCloud)

Scope: modelos DeepSeek oferecidos pela plataforma. Ignorados modelos de terceiros.

| Model ID | Contexto | Max Output | Thinking | Function Calling | Preço Input (1M) | Preço Output (1M) |
|----------|----------|-----------|----------|------------------|------------------|-------------------|
| `deepseek-v4-pro` | 1.000.000 | 384k* | ✅ (default) | ✅ | $2.40 | $4.80 |
| `deepseek-v4-flash` | 1.000.000 | 384k* | ✅ (default) | ✅ | $0.20 | $0.40 |
| `deepseek-v4-flash-0731` | 1.000.000 | 384k* | ✅ (default) | ✅ | $0.20 | $0.40 |
| `deepseek-v3.2` | 131.072 | 64k | ✅ (32k budget) | ✅ | $0.57 | $1.71 |

Notas:
- `deepseek-v4-pro/flash` compartilham um orçamento total de **384k tokens**
  entre output e thinking (*). Suportam context cache.
- `deepseek-v4-flash-0731` é o snapshot atual do V4 Flash.
- **Não suportam** Built-in Tools nem Structured Output (ao contrário dos Qwen3.7).
- Legacy DeepSeek v3/v3.1/r1 ainda listados na China, mas fora do escopo ativo aqui.

---

## Modelos Descontinuados / Em Depreciação

### Depreciação programada para Outubro 10, 2026

| Modelo | Substituir por |
|--------|---------------|
| `qwen3.6-max-preview` | `qwen3.7-max` |
| `qwen3-max-preview` | `qwen3.7-max` |
| `qwen3-max` | `qwen3.7-max` |
| `qwen3-vl-flash` | `qwen3.6-flash` |
| `qwen3-coder-plus` | `qwen3.7-plus` |
| `qwen3-max-2026-01-23` | `qwen3.7-max` |
| `qwen3-max-2025-09-23` | `qwen3.7-max` |
| `qwen3-vl-8b-instruct/thinking` | `qwen3.6-flash` |
| `qwen3-vl-30b-a3b-instruct/thinking` | `qwen3.7-plus` |
| `qwen3-vl-32b-instruct/thinking` | `qwen3.7-plus` |
| `qwen3-vl-235b-a22b-thinking` | `qwen3.7-plus` |
| `qwen3-coder-next` | `qwen3.7-plus` |
| `qwen3-coder-30b-a3b-instruct` | `qwen3.7-plus` |
| `qwen3-8b/14b/30b/32b/235b` (open source) | `qwen3.6-flash` / `qwen3.7-plus` |
| `qwen3-next-80b-a3b-instruct/thinking` | `qwen3.7-plus` |

### Serie Qwen3.6 / Qwen3.5 de código aberto promovida a "Legacy"

A documentação oficial recomenda **Qwen3.6** para projetos novos. Os seguintes
viraram catálogo legado (não recomendado para novos projetos):

| Modelo | Status |
|--------|--------|
| `qwen3.5-397b-a17b` / `qwen3.5-122b-a10b` / `qwen3.5-27b` / `qwen3.5-35b-a3b` | Legacy (open source) |
| `qwen3.6-35b-a3b` / `qwen3.6-27b` | Mobilidade open source (sem execution via API recomendada) |
| `qwen2.5-vl-72b/32b/7b/3b-instruct` | Legacy · substituir por `qwen3-vl-plus`/`qwen3-vl-flash` |
| `qwen3-coder-plus/flash/next` e snapshots | Legacy · substituir por `qwen3.7-plus` |

### Decommissionamento Maio 13-31, 2026

| Modelo | Substituir por |
|--------|---------------|
| `qwen-turbo` / `qwen-turbo-latest` / `qwen-turbo-2025-04-28` | `qwen-flash` / `qwen3.6-flash` |
| `qwen-max` / `qwen-max-latest` / `qwen-max-2025-01-25` | `qwen3.7-max` / `qwen3-max` / `qwen3.6-plus` |
| `qwen-vl-max` / `qwen-vl-plus` (e snapshots) | `qwen3-vl-plus` / `qwen3-vl-flash` |

### Deprecado Janeiro 30, 2026

| Modelo | Substituir por |
|--------|---------------|
| `qwen-plus-2024-11-27` / `2024-11-25` / `2024-09-19` / `2024-08-06` | `qwen-plus-2025-12-01` |
| `qwen-turbo-2024-09-19` | `qwen-flash-2025-07-28` |
| `qwen-vl-max-2024-10-30` / `2024-08-09` | `qwen3-vl-plus-2025-12-19` |
| `qwen-vl-plus-2024-08-09` | `qwen3-vl-flash-2025-10-15` |

### Deprecado Agosto 20, 2025

| Modelo | Substituir por |
|--------|---------------|
| `qwen2-72b-instruct` | `qwen-plus` |
| `qwen2-57b-a14b-instruct` | `qwen-plus` |
| `qwen2-7b-instruct` | `qwen-plus` |
| `qwen1.5-110b-chat` | `qwen-plus` |
| `qwen1.5-72b-chat` | `qwen-plus` |
| `qwen1.5-32b-chat` | `qwen-plus` |
| `qwen1.5-14b-chat` | `qwen-plus` |
| `qwen1.5-7b-chat` | `qwen-plus` |

### Rerank

| Modelo | Depreciação | Substituir por |
|--------|-------------|---------------|
| `gte-rerank` | Maio 30, 2026 | `qwen3-rerank` |

### DeepSeek

| Modelo | Status |
|--------|--------|
| `deepseek-r1` / `deepseek-r1-0528` | Legacy (China) para novos projetos |
| `deepseek-v3` / `deepseek-v3.1` | Legados; usar `deepseek-v4-*` |
| `deepseek-r1-distill-llama-8b` | **Discontinued** — usar DeepSeek/Kimi |

---

## Detalhes dos modelos recomendados

### qwen3.7-flash

- Contexto: 1.000.000 tokens (janela total)
- Max Output: 64k | Thinking Budget: 256k
- Modalidades: Texto, Imagem, Vídeo → Texto
- Function Calling: ✅ | Web Search (built-in tools): ✅ | Structured Output: ✅
- Snapshot: `qwen3.7-flash-2026-07-15`
- Preço: $0.03/$0.13 (≤32K), $0.10/$0.40 (32–256K), $0.20/$0.80 (256K–1M)
- Rate Limit: 15.000 RPM (US) / até 30.000 RPM (China)
- Melhorias: compreensão multimodal reforçada, reconhecimento de objetos, percepção espacial, agente multimodal.

### qwen3.7-max

- Contexto: 1.000.000 | Max Output: 65.536 | Thinking Budget: 262.144
- Modalidades: Texto → Texto (texto-only; snapshot `2026-06-08` ganha visão)
- Function Calling: ✅ | Built-in tools (Web Search): ✅ | Streaming: ✅ (non-streaming suportado)
- Preço: $2.50 / $7.50 (list; 50% off promocional em períodos)
- Free quota (Intl): 1M tokens

---

## Observações

- A API da Alibaba Cloud é compatível com OpenAI (formato `/v1/chat/completions`), Anthropic e SDK nativo DashScope.
- **Capacidades por modelo** (contexto, max output, thinking budget, etc.) são a fonte
  oficial de QwenCloud/Alibaba. O preço "de catálogo" (list price) pode divergir do
  que aparece no console por causa de promoções.
- **Free Tier / Free Trial:** a maioria dos modelos Qwen3.x tem **cota gratuita de
  1M tokens** (internacional); embeddings/rerank tem free tier próprio. Verificar no
  console por região.
- Endpoint internacional: `https://dashscope-intl.aliyuncs.com/compatible-mode/v1`