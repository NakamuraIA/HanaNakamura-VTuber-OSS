# YouTube Transcrição (yt-dlp + whisper_video + Groq)

Baixa vídeo do YouTube, extrai áudio e transcreve com **whisper-large-v3** via **Groq API**. Gera um `.md` com timestamps.

## Script associado

**Script:** `E:\Projeto_Hana_AI\data\scripts\youtube_transcribe.py`

```bash
python E:\Projeto_Hana_AI\data\scripts\youtube_transcribe.py "URL_DO_YOUTUBE"
```

## Flags

| Flag | Descrição |
|------|-----------|
| `--output DIR` / `-o DIR` | Pasta onde salvar o .md (padrão: Desktop) |

## Exemplos

```bash
# Salvar no Desktop
python youtube_transcribe.py "https://youtu.be/dQw4w9WgXcQ"

# Salvar numa pasta específica
python youtube_transcribe.py "https://youtu.be/dQw4w9WgXcQ" -o "C:\Users\Nakamura\Videos\transcricoes"
```

## Fluxo interno

1. **yt-dlp** baixa o melhor MP4 disponível numa pasta temporária
2. **whisper_video** (`E:\whisper_video\main.py`) recebe o caminho do vídeo:
   - Extrai áudio com ffmpeg
   - Divide em chunks de ~20MB (limite do Groq)
   - Envia cada chunk pro Groq API (whisper-large-v3) com offset de tempo
   - Gera `.md` com timestamps na pasta `E:\whisper_video\output\`
3. Copia o `.md` pro destino escolhido
4. Limpa a pasta temporária e o `.md` do output do whisper

## Pré-requisitos (já instalados)

- **yt-dlp** — pip instalado
- **ffmpeg** — em `C:\ffmpeg\ffmpeg.exe`
- **whisper_video** — em `E:\whisper_video\` (com `.env` configurado com chave Groq)
- **rich** — pip instalado (usado pelo whisper_video)

## Pegadinhas

- Vídeos >2h podem estourar o limite de tempo do Groq (depende do plano)
- A chave Groq fica em `E:\whisper_video\.env` — se não tiver configurada, o whisper_video falha
- O script limpa o `.md` do output do whisper após copiar — se algo der erro na cópia, a transcrição original ainda está em `E:\whisper_video\output\`
- Vídeos bloqueados por região ou restritos podem falhar no yt-dlp
