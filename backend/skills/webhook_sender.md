# Webhook Sender (Discord)

Envia arquivos (imagens, zips, textos) para um webhook do Discord via HTTP.

## Script associado

**Script:** `E:\Projeto_Hana_AI\data\scripts\webhook_sender.py`

Use o script em vez de remontar o comando toda vez:

```bash
python E:\Projeto_Hana_AI\data\scripts\webhook_sender.py --file "C:\caminho\arquivo.png"
```

### Parâmetros

- `--file` ou `-f` — Caminho completo do arquivo a enviar
- `--webhook` ou `-w` — URL do webhook (opcional, usa o padrão)
- `--url` — URL direta de download (opcional, baixa e envia)

### Exemplos

```bash
# Enviar imagem local
python E:\Projeto_Hana_AI\data\scripts\webhook_sender.py --file "C:\Users\Nakamura\Downloads\foto.webp"

# Enviar com webhook diferente
python E:\Projeto_Hana_AI\data\scripts\webhook_sender.py -f "C:\foto.jpg" -w "https://discord.com/api/webhooks/..."

# Baixar de URL e enviar
python E:\Projeto_Hana_AI\data\scripts\webhook_sender.py --url "https://exemplo.com/imagem.jpg"
```

## Pré-requisitos

- **Python 3.x** com `requests` instalado (`pip install requests`)
- URL de webhook do Discord válida

## Pegadinhas

- Limite do Discord: ~8MB (sem Nitro) / ~25MB (sem Nitro) / ~50MB (Nitro Boost)
- Arquivos maiores que 25MB precisam ser divididos ou enviados por outro meio
- O webhook pode expirar (403) se for de servidor temporário
- Imagens .webp, .png, .jpg e .gif são renderizadas inline no Discord
- 413 = arquivo grande demais pro plano atual
- 403 = webhook inválido/expirado
- 200 = sucesso
- **Emojis no nome do arquivo**: o Windows/Python pode falhar ao resolver caminhos com emoji (ex: `gabriel 🤔.webp`). O script tenta fallback via PowerShell e busca por nome parcial. Se falhar, copie o arquivo pra pasta de downloads sem emoji no nome.
