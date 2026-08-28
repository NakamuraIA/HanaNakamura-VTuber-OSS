# Gemini Models - Google AI Studio (Gemini API)

Data de atualização: Julho 2026

Endpoint: `https://generativelanguage.googleapis.com/v1beta`
API key gerada em: https://aistudio.google.com/apikey

## Modelos Stable (Produção)

| Model ID | Contexto | Visão | Audio | Tools | Preço |
|----------|----------|-------|-------|-------|-------|
| `gemini-3.6-flash` | 1.048.576 | ✅ | ✅ | ✅ | Pago |
| `gemini-3.5-flash` | 1.048.576 | ✅ | ✅ | ✅ | Pago |
| `gemini-3.5-flash-lite` | 1.048.576 | ✅ | ✅ | ✅ | Pago |
| `gemini-3.1-flash-lite` | 1.048.576 | ✅ | ✅ | ✅ | Pago |
| `gemini-2.5-flash` | 1.048.576 | ✅ | ✅ | ✅ | Pago / Free tier |
| `gemini-2.5-flash-lite` | 1.048.576 | ✅ | ✅ | ✅ | Pago / Free tier |
| `gemini-2.5-pro` | 1.048.576 | ✅ | ✅ | ✅ | Pago |

## Modelos Preview

| Model ID | Descrição |
|----------|-----------|
| `gemini-3.1-pro-preview` | Raciocínio avançado, agente, vibe coding |
| `gemini-3-flash-preview` | Performance frontier-class |
| `gemini-3.5-live-translate-preview` | Tradução fala-fala em tempo real (70+ idiomas) |
| `gemini-3.1-flash-live-preview` | Áudio-a-áudio em tempo real, diálogo |
| `gemini-3.1-flash-tts-preview` | Síntese de fala com controle de estilo |
| `gemini-omni-flash` | Geração e edição de vídeo conversacional |
| `gemini-2.5-flash-live-preview` | Agentes de voz bidirecionais (Live API) |
| `gemini-2.5-flash-tts-preview` | TTS rápido e controlável |
| `gemini-2.5-pro-tts-preview` | TTS alta fidelidade |

## Modelos de Imagem (Nano Banana)

| Model ID | Descrição |
|----------|-----------|
| `gemini-3.1-flash-image` (Nano Banana 2) | Geração/edição de imagens, alta eficiência |
| `gemini-3.1-flash-lite-image` (Nano Banana 2 Lite) | Ultra-rápido, baixo custo |
| `gemini-3-pro-image` (Nano Banana Pro) | 4K, layouts complexos, texto preciso |

## Modelos Especializados

| Model ID | Descrição |
|----------|-----------|
| `gemini-2.5-computer-use-preview` | Automação de UI (ver tela, clicar, digitar) |
| `deep-research-preview` | Pesquisa autônoma multi-fontes |
| `deep-research-max-preview` | Pesquisa máxima abrangência |
| `antigravity-preview` | Agente sandbox Linux (código, arquivos, web) |
| `gemini-embedding-2` | Embeddings multimodais (texto, imagem, audio, video, PDF) |
| `gemini-embedding-001` | Embeddings texto |

## Modelos de Música (Lyria)

| Model ID | Descrição |
|----------|-----------|
| `lyria-3-pro-preview` | Músicas completas |
| `lyria-3-clip-preview` | Clipes/loops até 30s |
| `lyria-realtime-exp` | Streaming em tempo real |

## Modelos de Vídeo (Veo)

| Model ID | Descrição |
|----------|-----------|
| `veo-3.1-generate-preview` | Vídeo cinematográfico com áudio |
| `veo-3.1-lite-generate-preview` | Vídeo rápido e barato |

## Modelos Anteriores (Depreciados / Shutdown)

| Modelo | Status |
|--------|--------|
| `gemini-2.0-flash` | Shut down |
| `gemini-2.0-flash-lite` | Shut down |
| `gemini-3.1-flash-lite-preview` | Shut down |
| `gemini-3-pro-preview` | Shut down |
| `imagen-4` | Deprecated |

## Observações

- **Free Tier** (Google AI Studio): modelos Flash (2.5) com rate limits. Pro models são pagos desde Abril/2026.
- **Contexto**: TODOS os modelos atuais têm 1.048.576 tokens (1M).
- **Google Search**: Disponível como ferramenta integrada.
- **Live API**: Para agentes de voz/vídeo em tempo real (WebSocket).
- **temperature/top_p/top_k** estão deprecados — modelos mais recentes usam configuração padrão.
- API compatível com OpenAI via endpoint separado.
- Chat em: https://aistudio.google.com
