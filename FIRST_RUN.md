# Primeira instalação da Hana

`Hana-First-Run.cmd` é usado **uma única vez**. Ele prepara o projeto; depois,
o uso diário é sempre pelo `Hana.cmd`.

## Antes de começar

Instale:

- Python 3.11 ou mais novo;
- Node.js na versão LTS, que já inclui o npm.

## Instalação automática

1. Baixe ou clone o projeto.
2. Dê duplo clique em `Hana-First-Run.cmd`.
3. Espere as cinco etapas terminarem.
4. Abra `.env` e preencha pelo menos uma chave de LLM.
5. Dê duplo clique em `Hana.cmd` para ligar a Hana.

O instalador:

- preserva um `.env` que já exista;
- cria o ambiente Python e instala as dependências;
- instala as dependências do frontend;
- cria `runtime/hana_memory.sqlite3` somente quando não existe;
- carrega uma vez os catálogos públicos de LLM, TTS e STT.

Se um banco já existir, ele não será alterado. Executar o First Run outra vez
também não traz de volta modelos que você apagou.

## Instalação manual equivalente

Na raiz do projeto:

```powershell
Copy-Item .env.example .env
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
Set-Location frontend
npm install
Set-Location ..
.venv\Scripts\python.exe -m backend.setup.database initialize
```

## Restaurar modelos públicos manualmente

A prévia não escreve no banco:

```powershell
.venv\Scripts\python.exe -m backend.setup.database restore llm
```

Depois de conferir a lista, a confirmação explícita faz a restauração:

```powershell
.venv\Scripts\python.exe -m backend.setup.database restore llm --confirm
```

Troque `llm` por `tts` ou `stt` conforme o catálogo desejado. A restauração
adiciona ou atualiza somente os padrões públicos confirmados; não apaga modelos
extras nem altera memória, perfil ou configurações.

Com o backend ligado, a mesma ação aparece no Swagger em
`Setup e recuperação`. Primeiro execute a prévia e só depois mude `confirm`
para `true`.

