# YouTube Music Download (yt-dlp + ffmpeg)

Baixa música do YouTube como MP3 direto na área de trabalho da Operador.

## Script associado

**Script:** `E:\Projeto_Hana_AI\data\scripts\youtube_download.py`

Use o script em vez de remontar o comando toda vez:

```
python E:\Projeto_Hana_AI\data\scripts\youtube_download.py "https://youtu.be/..."
```

### Flags
- `--output DIR` ou `-o DIR` — muda a pasta de saída (padrão: Desktop)
- `--clean` — apaga o .webm original depois da conversão (não implementado ainda)

## Fluxo manual (caso queira fazer na mão)

1. Extrair o URL do YouTube
2. Tentar baixar direto como MP3:
   ```
   python -m yt_dlp --extract-audio --audio-format mp3 -o "C:\Users\Operador\Desktop\%(title)s.%(ext)s" "<URL>"
   ```
3. Se falhar, baixar como webm:
   ```
   python -m yt_dlp -f bestaudio -o "C:\Users\Operador\Desktop\%(title)s.%(ext)s" "<URL>"
   ```
4. Converter webm pra MP3:
   ```
   C:\ffmpeg\ffmpeg.exe -i "<ARQUIVO.webm>" -vn -acodec libmp3lame -q:a 2 "<ARQUIVO.mp3>" -y
   ```

## Pré-requisitos (já instalados)

- **yt-dlp** — pip instalado
- **ffmpeg** — em `C:\ffmpeg\ffmpeg.exe`

## Pegadinhas

- yt-dlp às vezes não consegue baixar MP3 direto — fallback pra webm + conversão
- Usar `python -m yt_dlp`, não `yt-dlp` direto (não tá no PATH)
- Vídeos ao vivo ou >1h costumam falhar
- Títulos com `&`, `$`, aspas precisam de aspas duplas no caminho
