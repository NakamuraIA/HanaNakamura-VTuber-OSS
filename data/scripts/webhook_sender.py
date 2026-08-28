#!/usr/bin/env python3
"""
Webhook Sender - Envia arquivos para webhook do Discord.
Uso: python webhook_sender.py --file <caminho>
     python webhook_sender.py --url <url_para_baixar>
     python webhook_sender.py --dir <pasta>  (envia o primeiro arquivo)
"""

import os
import sys
import argparse
import glob
import requests
from pathlib import Path

# A URL do webhook E credencial: quem tiver ela posta no seu canal. Vem do .env
# (fora do git) — este arquivo vai pro repo publico, entao nunca escreva aqui.
DEFAULT_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")
MAX_SIZE_BYTES = 50 * 1024 * 1024


def resolve_path(raw: str) -> str:
    """Tenta resolver wildcard/emoji no nome do arquivo."""
    if os.path.exists(raw):
        return raw

    basedir = os.path.dirname(raw) or "."
    name_stem = os.path.splitext(os.path.basename(raw))[0]

    # Expande wildcard pelo nome (com ou sem extensão)
    matches = sorted(glob.glob(os.path.join(basedir, "*" + name_stem + "*")))
    if matches:
        return matches[0]

    return resolve_path_powershell(raw)


def resolve_path_powershell(raw: str) -> str:
    """Usa PowerShell pra resolver caminho com emoji via Get-ChildItem."""
    import subprocess

    ps_script = (
        f"$f = Get-ChildItem -LiteralPath '{raw}' -ErrorAction SilentlyContinue; "
        f"if (-not $f) {{ $f = Get-ChildItem (Split-Path '{raw}') -Filter ('*' + (Get-Item '{raw}' -ErrorAction SilentlyContinue | %{{$_.BaseName}}) + '*') -ErrorAction SilentlyContinue }}; "
        f"if ($f) {{ Write-Output $f.FullName }} else {{ Write-Output '__NAO_ACHOU__' }}"
    )
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True, text=True, timeout=10
        )
        out = r.stdout.strip()
        if out and out != "__NAO_ACHOU__" and os.path.exists(out):
            return out
    except Exception:
        pass
    return raw


def send_file(file_path: str, webhook_url: str) -> dict:
    path = Path(resolve_path(file_path))

    if not path.exists():
        return {"ok": False, "error": f"Arquivo não encontrado: {file_path}"}

    file_size = path.stat().st_size
    if file_size > MAX_SIZE_BYTES:
        return {"ok": False, "error": f"Arquivo muito grande: {file_size/1024/1024:.1f}MB (limite ~50MB)"}

    try:
        with open(path, "rb") as f:
            files = {"file": (path.name, f)}
            resp = requests.post(webhook_url, files=files, timeout=120)
        result = {
            "ok": resp.status_code == 200,
            "status": resp.status_code,
            "size_kb": round(file_size / 1024, 1),
            "filename": path.name,
        }
        if resp.status_code == 200:
            result["response"] = "Enviado com sucesso!"
        elif resp.status_code == 413:
            result["response"] = "Arquivo muito grande para o Discord (413)"
        elif resp.status_code == 403:
            result["response"] = "Webhook inválido ou expirado (403)"
        else:
            result["response"] = resp.text[:200]
        return result
    except requests.exceptions.Timeout:
        return {"ok": False, "error": "Timeout na requisição"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def send_from_url(download_url: str, webhook_url: str) -> dict:
    try:
        resp = requests.get(download_url, stream=True, timeout=60)
        if resp.status_code != 200:
            return {"ok": False, "error": f"Falha ao baixar: HTTP {resp.status_code}"}
        content_length = resp.headers.get("content-length")
        if content_length and int(content_length) > MAX_SIZE_BYTES:
            return {"ok": False, "error": f"Arquivo muito grande: {int(content_length)/1024/1024:.1f}MB"}
        filename = download_url.split("/")[-1].split("?")[0] or "download"
        files = {"file": (filename, resp.content)}
        post_resp = requests.post(webhook_url, files=files, timeout=120)
        return {
            "ok": post_resp.status_code == 200,
            "status": post_resp.status_code,
            "filename": filename,
            "response": "Sucesso!" if post_resp.status_code == 200 else post_resp.text[:200],
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def main():
    parser = argparse.ArgumentParser(description="Envia arquivo para webhook do Discord")
    parser.add_argument("--file", "-f", help="Caminho do arquivo local")
    parser.add_argument("--webhook", "-w", default=DEFAULT_WEBHOOK, help="URL do webhook")
    parser.add_argument("--url", help="URL de download remoto")
    args = parser.parse_args()

    if not args.file and not args.url:
        print("ERRO: Use --file ou --url")
        sys.exit(1)

    if not args.webhook:
        print("ERRO: nenhum webhook configurado.")
        print("Ponha no .env:  DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...")
        print("Ou passe na hora:  --webhook \"https://...\"")
        sys.exit(1)

    if args.file:
        result = send_file(args.file, args.webhook)
    else:
        result = send_from_url(args.url, args.webhook)

    if result.get("ok"):
        print(f"OK: {result.get('filename')} ({result.get('size_kb', '?')}KB) - Status {result.get('status')}")
    else:
        print(f"FALHOU: {result.get('error', 'erro desconhecido')}")
        sys.exit(1)


if __name__ == "__main__":
    main()
