"""Transcreve audio ou video 100% offline, com Whisper local.

Nada sai da maquina — diferente do whisper_video, que manda o audio pra Groq.
Use quando o conteudo for privado, quando nao houver internet, ou quando a cota
da API tiver estourado.

    python data/scripts/transcrever_local.py "video.mp4"
    python data/scripts/transcrever_local.py "audio.mp3" --modelo small
    python data/scripts/transcrever_local.py "call.wav" -o "C:\\Users\\Nakamura\\Desktop"

Salva um .md com o texto corrido e os timestamps ao lado.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Esta maquina roda CPU (torch sem CUDA). Modelo grande fica inviavel:
# 'medium' passa de 10 min pra cada 10 min de audio. 'small' e o teto pratico.
MODELOS = ("tiny", "base", "small", "medium", "large")
PADRAO = "small"


def formatar_tempo(segundos: float) -> str:
    m, s = divmod(int(segundos), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def main() -> int:
    p = argparse.ArgumentParser(description="Transcreve audio/video offline com Whisper local.")
    p.add_argument("arquivo", help="Caminho do audio ou video")
    p.add_argument("--modelo", "-m", default=PADRAO, choices=MODELOS,
                   help=f"Tamanho do modelo (padrao: {PADRAO}). Maior = melhor e MUITO mais lento em CPU.")
    p.add_argument("--idioma", "-l", default="pt", help="Idioma do audio (padrao: pt). 'auto' detecta sozinho.")
    p.add_argument("--output", "-o", default="", help="Pasta de saida (padrao: ao lado do arquivo)")
    args = p.parse_args()

    entrada = Path(args.arquivo).expanduser().resolve()
    if not entrada.is_file():
        print(f"Arquivo nao encontrado: {entrada}")
        return 1

    try:
        import whisper
    except ImportError:
        print("Whisper local nao instalado. Rode:  pip install openai-whisper")
        return 1

    destino = Path(args.output).expanduser().resolve() if args.output else entrada.parent
    destino.mkdir(parents=True, exist_ok=True)
    saida = destino / f"{entrada.stem}.transcricao.md"

    print(f"Modelo   : {args.modelo}  (primeira vez baixa ~1GB e demora)")
    print(f"Arquivo  : {entrada.name}")
    print("Transcrevendo... em CPU isso leva mais ou menos o tempo do proprio audio.\n")

    inicio = time.time()
    modelo = whisper.load_model(args.modelo)
    resultado = modelo.transcribe(
        str(entrada),
        language=None if args.idioma == "auto" else args.idioma,
        verbose=False,
    )
    levou = time.time() - inicio

    linhas = [
        f"# Transcricao — {entrada.name}",
        "",
        f"- Modelo: whisper `{args.modelo}` (local, offline)",
        f"- Idioma: {resultado.get('language', args.idioma)}",
        f"- Levou: {formatar_tempo(levou)}",
        "",
        "## Texto",
        "",
        resultado["text"].strip(),
        "",
        "## Com timestamps",
        "",
    ]
    for seg in resultado.get("segments", []):
        linhas.append(f"**[{formatar_tempo(seg['start'])}]** {seg['text'].strip()}")

    saida.write_text("\n".join(linhas), encoding="utf-8")
    print(f"\nPronto em {formatar_tempo(levou)}")
    print(f"Salvo em: {saida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
