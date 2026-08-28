"""Baixa video de qualquer site suportado pelo yt-dlp, so com o link.

YouTube, Twitter/X, TikTok, Instagram, Twitch, Reddit e mais mil — o yt-dlp
resolve o site sozinho, entao nao existe "script pra cada site".

    python data/scripts/baixar_video.py "https://..."
    python data/scripts/baixar_video.py "https://..." --audio          # so o MP3
    python data/scripts/baixar_video.py "https://..." -o "D:\\Videos"
    python data/scripts/baixar_video.py "https://..." --qualidade 720

Salva no Desktop por padrao.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

DESTINO_PADRAO = Path.home() / "Desktop"


def main() -> int:
    p = argparse.ArgumentParser(description="Baixa video/audio de um link.")
    p.add_argument("url", help="Link do video")
    p.add_argument("--output", "-o", default=str(DESTINO_PADRAO), help="Pasta de saida (padrao: Desktop)")
    p.add_argument("--audio", "-a", action="store_true", help="Baixa so o audio, em MP3")
    p.add_argument("--qualidade", "-q", default="", help="Altura maxima: 480, 720, 1080. Vazio = melhor disponivel")
    args = p.parse_args()

    try:
        import yt_dlp
    except ImportError:
        print("yt-dlp nao instalado. Rode:  pip install yt-dlp")
        return 1

    destino = Path(args.output).expanduser().resolve()
    destino.mkdir(parents=True, exist_ok=True)

    # `%(title)s` vira o nome do arquivo; `restrictfilenames` tira acento e espaco,
    # senao o caminho quebra em comando de terminal depois.
    opcoes: dict = {
        "outtmpl": str(destino / "%(title)s.%(ext)s"),
        "restrictfilenames": True,
        "noplaylist": True,  # link de video dentro de playlist baixa SO o video
        "quiet": False,
        "no_warnings": True,
    }

    if args.audio:
        opcoes["format"] = "bestaudio/best"
        opcoes["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]
    elif args.qualidade:
        # Junta o melhor video ate a altura pedida com o melhor audio.
        opcoes["format"] = f"bestvideo[height<={args.qualidade}]+bestaudio/best[height<={args.qualidade}]"
        opcoes["merge_output_format"] = "mp4"
    else:
        opcoes["format"] = "bestvideo+bestaudio/best"
        opcoes["merge_output_format"] = "mp4"

    print(f"Baixando de: {args.url}")
    print(f"Salvando em: {destino}\n")

    try:
        with yt_dlp.YoutubeDL(opcoes) as ydl:
            info = ydl.extract_info(args.url, download=True)
    except Exception as exc:  # noqa: BLE001 - o erro do yt-dlp e a informacao util
        print(f"\nFalhou: {exc}")
        print("Causas comuns: video privado, precisa login, regiao bloqueada, ou yt-dlp desatualizado.")
        print("Se for site grande, tente:  pip install -U yt-dlp")
        return 1

    titulo = info.get("title", "video")
    print(f"\nPronto: {titulo}")
    print(f"Em: {destino}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
