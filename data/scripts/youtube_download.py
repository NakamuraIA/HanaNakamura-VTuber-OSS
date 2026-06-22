#!/usr/bin/env python3
"""
YouTube Music Downloader — Hana Agent OSS
Baixa musica do YouTube como MP3.
Uso: python youtube_download.py <URL> [--output DIR]
"""

import argparse
import os
import subprocess
import sys
import re

YT_DLP = ["python", "-m", "yt_dlp"]
FFMPEG = r"C:\ffmpeg\ffmpeg.exe"
DESKTOP = r"C:\Users\Operador\Desktop"


def clean_url(raw: str) -> str:
    """Remove aspas e espaços extras da URL."""
    return raw.strip().strip('"').strip("'")


def find_newest_file(output_dir: str, ext: str):
    files = [os.path.join(output_dir, f) for f in os.listdir(output_dir) if f.endswith(ext)]
    if files:
        return max(files, key=os.path.getmtime)
    return None


def download_mp3(url: str, output_dir: str):
    os.makedirs(output_dir, exist_ok=True)
    template = os.path.join(output_dir, "%(title)s.%(ext)s")
    cmd = YT_DLP + [
        "--extract-audio",
        "--audio-format", "mp3",
        "-o", template,
        url
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode == 0:
        mp3 = find_newest_file(output_dir, ".mp3")
        if mp3:
            return True, mp3
        for line in result.stderr.split("\n"):
            if "[ExtractAudio] Destination" in line:
                path = line.split("Destination: ")[-1].strip()
                if os.path.exists(path):
                    return True, path
        return False, "MP3 nao encontrado apos download"
    return False, result.stderr


def download_webm(url: str, output_dir: str):
    os.makedirs(output_dir, exist_ok=True)
    template = os.path.join(output_dir, "%(title)s.%(ext)s")
    cmd = YT_DLP + [
        "-f", "bestaudio",
        "-o", template,
        url
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        return False, result.stderr
    webm = find_newest_file(output_dir, ".webm")
    if webm:
        return True, webm
    for line in result.stderr.split("\n"):
        if "[Metadata] Adding metadata to" in line:
            path = line.split("to ")[-1].strip().strip('"')
            if path.endswith(".webm") and os.path.exists(path):
                return True, path
    return False, "Webm nao encontrado"


def convert_to_mp3(webm_path: str, output_dir: str = None):
    if output_dir is None:
        output_dir = os.path.dirname(webm_path)
    base = os.path.splitext(os.path.basename(webm_path))[0]
    mp3_path = os.path.join(output_dir, f"{base}.mp3")
    cmd = [
        FFMPEG, "-i", webm_path,
        "-vn", "-acodec", "libmp3lame", "-q:a", "2",
        mp3_path, "-y"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode == 0 and os.path.exists(mp3_path):
        return True, mp3_path
    return False, result.stderr


def main():
    parser = argparse.ArgumentParser(description="Baixa musica do YouTube como MP3")
    parser.add_argument("url", help="URL do YouTube")
    parser.add_argument("--output", "-o", default=DESKTOP,
                        help=f"Pasta de saida (padrao: {DESKTOP})")
    args = parser.parse_args()

    url = clean_url(args.url)

    print(f"[HANADL] Baixando: {url}")
    print(f"[HANADL] Salvando em: {args.output}")

    ok, result = download_mp3(url, args.output)
    if ok:
        print(f"[HANADL] OK - MP3 salvo: {result}")
        return 0

    print(f"[HANADL] Falhou MP3 direto, baixando como webm...")
    print(f"[HANADL] Erro: {result[:200]}")

    ok, webm = download_webm(url, args.output)
    if not ok:
        print(f"[HANADL] FALHA no download: {webm[:200]}")
        return 1

    print(f"[HANADL] Webm baixado: {webm}")

    ok, mp3 = convert_to_mp3(webm, args.output)
    if not ok:
        print(f"[HANADL] FALHA na conversao: {mp3[:200]}")
        return 1

    print(f"[HANADL] OK - MP3 convertido: {mp3}")
    print(f"[HANADL] Webm original: {webm}")

    return 0


if __name__ == "__main__":
    main()