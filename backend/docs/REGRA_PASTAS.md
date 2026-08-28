# Regra das pastas — uma responsabilidade por lugar

Status: contrato aplicado ao catálogo em 2026-08-22.

A confusão que gerou esta regra: a mesma responsabilidade estava em dois lugares
ao mesmo tempo (duas pastas criando tabela, duas guardando dado de API), então
ninguém sabia onde procurar nem onde mexer.

## A regra

```text
bd/         só CRIA tabela        (llm.py, tts.py, stt.py...)
catalog/    só LÊ/ESCREVE dado    (um repositório por domínio)
providers/  só FALA com a API     (url, chave, request)
setup/      coordena a PRIMEIRA instalação e a carga pública
```

Uma pasta, uma pergunta:

| Pasta | Responde |
| --- | --- |
| `bd/` | "que colunas essa tabela tem?" |
| `catalog/` | "o que esse modelo consegue fazer?" |
| `providers/` | "como eu mando a mensagem pra essa API?" |
| `setup/` | "como preparo um banco novo sem hardcode?" |

## O que isso implica

- `bd/` não lê dado, não chama API. Só `CREATE TABLE IF NOT EXISTS`, em Python.
- `catalog/` não cria tabela, não chama API. Só lê e escreve o que já existe.
- `providers/` não cria tabela, não guarda catálogo de modelo. Só endpoint,
  chave e formato da requisição.
- `setup/` valida os JSONs antes de escrever, chama os donos dos schemas e não
  participa do uso diário da Hana.

## Estado da migração

| Situação | Resultado |
| --- | --- |
| `catalog/schema.py` criava `provider_models` | resolvido: arquivo removido; `bd/` é o dono do schema |
| `memory/core.py` lia e escrevia catálogo | resolvido: memória não conhece mais modelos |
| `model_overrides` tinha dois donos | resolvido: fica somente sob `bd/llm.py` |
| `catalog/tts/fishaudio.py` guardava URL de STT sem chamador | removido em 2026-08-22; a integração TTS ativa continua temporariamente em `modules/voice/` |
| `catalog/repository.py` lia o cache antigo | resolvido: lê e escreve `llm_models` |
| `providers/*/catalog.py` com lista de modelo fixa | vira fallback temporário, some depois (ver `DECISOES_ARQUITETURA_CATALOGO.md`, "Critério de sucesso") |

`catalog/llm/execution_policy.py` continua onde está — decidir estratégia de
execução (streaming, tools, raciocínio) é leitura de capacidade, não criação de
tabela nem chamada de API.
