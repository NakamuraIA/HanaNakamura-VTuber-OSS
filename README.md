<div align="center">

<img src="data/image/banner.png" alt="Hana — assistente local" width="75%" />

<br/><br/>

# 🌸 Hana

### Uma IA que mora no seu PC.

**Fala · Escuta · Lembra · Age**
E **nada** sai da sua máquina.

<br/>

![status](https://img.shields.io/badge/status-viva%20e%20crescendo-ff5fa2?style=for-the-badge)
![local first](https://img.shields.io/badge/local--first-100%25-22d3ee?style=for-the-badge)
![sem nuvem](https://img.shields.io/badge/seus%20dados-ficam%20aqui-a855f7?style=for-the-badge)
![python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![react](https://img.shields.io/badge/React-Tauri-61DAFB?style=for-the-badge&logo=react&logoColor=black)
![rust](https://img.shields.io/badge/Rust-Tauri-000000?style=for-the-badge&logo=rust&logoColor=white)
![license](https://img.shields.io/badge/license-AGPL--3.0-orange?style=for-the-badge)

<br/>

> _"Toda IA esquece você quando fecha a aba._
> _Esta não."_

</div>

---

## ⚡ Em uma frase

Você baixa. Roda. E ela **te conhece** — porque a memória dela é um arquivo no
seu disco, não uma conta num servidor de alguém.

<div align="center">

### 🔑 A ideia que explica tudo

# **Código = quem ela é.**
# **Banco = o que ela viveu.**

_Apagar a memória dá amnésia, não lobotomia:_
_ela continua sendo ela, só não te conhece mais._

</div>

---

## 📑 Índice

- [🚀 Primeira instalação](#-primeira-instalação)
- [🧠 As três memórias](#-as-três-memórias)
- [🛠️ O que ela sabe fazer](#️-o-que-ela-sabe-fazer)
- [🗂️ As quatro pastas](#️-as-quatro-pastas)
- [🎛️ Providers](#️-providers)
- [🔒 Segurança — leia isto](#-segurança--leia-isto)
- [🧪 Testes](#-testes)
- [🩹 Quando der ruim](#-quando-der-ruim)
- [📚 Documentação](#-documentação)
- [⚖️ Licença](#️-licença)

---

## 🚀 Primeira instalação

```bash
git clone https://github.com/NakamuraIA/HanaNakamura-VTuber-OSS.git hana
cd hana
```

No Windows, dê duplo clique em **`Hana-First-Run.cmd`**. Pelo terminal, o
comando equivalente é:

```powershell
.\Hana-First-Run.cmd
```

Ele verifica Python, Node e npm; prepara backend, frontend, banco e catálogos
públicos. Depois, abra o `.env` criado e ponha **uma** chave de LLM. Só uma já
basta.

Passo a passo e instalação manual: [FIRST_RUN.md](FIRST_RUN.md).

**Depois da primeira instalação**, é sempre assim:

<div align="center">

### 🖱️ Duplo clique em **`Hana.cmd`**

_Ela liga sozinha. Sem terminal, sem comando._
_Pra desligar: **`Desligar-Hana.cmd`**._

</div>

<summary>🧑‍💻 <b>Prefere terminal? (clique)</b></summary>

<br/>

**Dois terminais.** Um pro back, um pro front.

```bash
# terminal 1 — backend
cd backend
.venv\Scripts\activate
uvicorn main:app --reload --port 8042
```

```bash
# terminal 2 — frontend
cd frontend
npm run dev
```

Abre em **http://localhost:1425**.

> **A regra que evita 90% da confusão:**
> Python roda de **`backend/`**. Node roda de **`frontend/`**.
> `npm` na raiz dá `ENOENT: package.json`.


### 🖥️ App desktop (Tauri)

```bash
cd frontend
npm run tauri dev    # abre com live-reload (dev)
npm run tauri build  # gera o .exe em src-tauri/target/release/
```

O executável fica em `frontend/src-tauri/target/release/hana-control-center.exe`.

---

## 🧠 As três memórias

Aqui é onde este projeto é diferente. Não é "histórico de chat" — são **três
memórias com propósitos diferentes**, e a divisão importa:

<div align="center">

| | O que guarda | Quem escreve | Como entra no prompt |
|:---:|---|:---:|---|
| 💬 **Curta** | a conversa recente | automático | as últimas N falas, **isoladas por canal** |
| 🧠 **Longa** | fatos destilados | **ela mesma** | só o que combina com a pergunta (RAG) |
| 📌 **Fixa** | suas regras | **só você** | sempre, inteira |

</div>

**Curta guarda conversa. Longa guarda fato.** A diferença:

```
CURTA (crua):                        LONGA (destilado):
  você: nossa, odeio texto longo
  hana: desculpa!                 →   "Nakamura não gosta
  você: sério, escreve curto           de respostas longas"
  hana: ok
```

Quatro mensagens viram uma frase. É por isso que a busca funciona numa e não na
outra — você não acha significado num monte de "pera" e "kkkk".

### 📌 A memória fixa é a estrela

É a **continuação do system prompt** — mas em banco, editável pela tela:

```
[REGRAS FIXAS — valem sempre, em todo turno]
- (regra) responda sempre curto
- (giria) me chama de Naka
- (tarefa) o projeto X está na fase de testes
```

**Só você escreve.** Ela não tem ferramenta que grave ali — é leitura pura.
Desligar uma regra tira do prompt **sem apagar**, ótimo pra descobrir qual está
causando algum comportamento estranho.

<summary>🔬 <b>Por dentro: um arquivo, seis tabelas (clique)</b></summary>

<br/>

```
runtime/hana_memory.sqlite3
├── messages          curta — conversa, por canal        → prompt ✅
├── facts             longa — RAG com FTS5/BM25          → prompt ✅
├── pinned            fixa — suas regras                 → prompt ✅
├── chat_log          histórico da tela                  → prompt ❌ nunca
├── settings          configuração do app                → prompt ❌
└── skills            os manuais que ela lê e escreve    → só o índice
```

**Essa divisão é a coisa mais importante do projeto.** As três primeiras custam
token toda mensagem. As outras são de graça.

**As travas ficam no banco, não no código:**

```sql
role    CHECK (role IN ('user','assistant'))
channel CHECK (channel IN ('chat','discord','terminal','voice'))
content CHECK (length(content) BETWEEN 1 AND 8000)
```

Trava no código depende de todo mundo lembrar. Trava no banco não esquece — um
bug em qualquer caller **não consegue** sujar a tabela.

O isolamento por canal não é enfeite: sem ele, o Discord enxerga a conversa de
voz. Já aconteceu, e tem teste pra nunca mais.

Detalhes: [backend/docs/MEMORIA.md](backend/docs/MEMORIA.md)

---

## 🛠️ O que ela sabe fazer

**33 ferramentas.** As que importam:

<div align="center">

| 🖐️ Mãos | 🧠 Cabeça | 🎨 Criação |
|---|---|---|
| roda comando no terminal | busca na web (Tavily) | gera e edita imagem |
| lê e escreve arquivo | salva e corrige memória | fala (TTS) e escuta (STT) |
| digita e clica por você | lê e escreve as próprias skills | avatar VTuber |
| vê a tela | agenda lembretes | responde no Discord |

</div>

### 📚 Skills: ela aprende e anota sozinha

Skill = o **manual** (quando/como fazer, as pegadinhas).
Script = o **código** que executa.

Quando ela descobre um truque usando uma skill, **anota nela**:

```markdown
## Notas da Hana (aprendidas em uso)
- [2026-07-27] usar --audio-format mp3, senão vem opus
```

Na próxima vez ela já sabe. Sem você ensinar de novo.

---

## 🗂️ As quatro pastas

```
hana/
├── backend/     🐍 Python — a Hana de verdade
├── frontend/    ⚛️ React + Tauri — a telinha
├── data/        📚 skills, scripts e imagens
└── runtime/     💾 memória e mídia  ← a ÚNICA pasta que ela escreve
```

<div align="center">

### 💾 Backup = copiar `runtime/`
### 🔄 Reset = apagar `runtime/`

</div>

> Copie a **pasta inteira**, não só o `.sqlite3`. O banco usa WAL, então as
> escritas mais recentes podem estar num arquivo `-wal` ao lado. Ou desligue a
> Hana antes — no desligamento limpo o WAL é aplicado no banco.

Se ela escrever fora de `runtime/`, **é bug**. Regra fácil de checar.

---

## 🎛️ Providers

Escolha na tela, troque quando quiser. **Uma chave já basta pra começar.**

<div align="center">

| 🧠 Cérebro | 🎙️ Voz | 🔍 Busca |
|---|---|---|
| DeepSeek · Gemini · Groq | Edge _(grátis, sem chave)_ | Tavily |
| OpenRouter · Qwen · Maritaca | Google Cloud · ElevenLabs · Fish | via MCP |

</div>

**Sugestão pra começar:** DeepSeek (barato e rápido) + Edge TTS (grátis).

<details>
<summary>🎚️ <b>Controle de raciocínio unificado (clique)</b></summary>

<br/>

Cada provider chama "pensar antes de responder" de um jeito diferente. A Hana
unifica isso num knob só na tela:

| Provider | O que ele expõe de verdade |
|---|---|
| **Gemini 3.x** | `thinking_level`: low / high |
| **Gemini 2.5.x** | `thinking_budget`: -1 dinâmico, 0 desliga |
| **DeepSeek** | 2 níveis reais + desligado |
| **OpenRouter** | escala contínua: none → max |
| **Groq / Qwen** | liga/desliga |

⚠️ Modelos **Pro** de qualquer família **não** desligam o raciocínio de vez —
a Hana usa o mínimo permitido em vez de mentir que desligou.

Detalhes: [backend/docs/](backend/docs/)

</details>

---

## 🔒 Segurança — leia isto

Este projeto entrega uma IA que **roda comando no seu PC**. Três coisas que
você precisa saber:

<div align="center">

| ⚠️ | |
|:---:|---|
| **1** | A API **não tem senha**. Ela só escuta em `127.0.0.1` — mantenha assim |
| **2** | O bot do Discord obedece **ninguém** até você pôr seu ID no `.env` |
| **3** | O `.env` tem chave de verdade. Nunca commite |

</div>

**Não troque `HANA_BACKEND_HOST` pra `0.0.0.0`.** Parece inofensivo ("quero
acessar do celular"), mas entrega shell sem senha pra qualquer aparelho da rede.

O CORS só aceita `localhost` e o app Tauri — de propósito. Com ele aberto,
qualquer aba do navegador poderia mandar a Hana rodar comando. Tem teste
travando isso.

---

## 🧪 Testes

```bash
python -m pytest backend/tests/ -q
```

```bash
python -m backend.memory.core
```

Os testes daqui não são enfeite — cada um trava um bug que **já aconteceu** e
que **não dá erro nenhum** quando volta:

| 🧪 | O que ele impede |
|---|---|
| `test_vazamento_canal` | o Discord ler a conversa de voz |
| `test_ferramentas_expostas` | o prompt prometer ferramenta que ela não pode chamar |
| `test_persona_publica` | dado pessoal voltar pro código que vai pro GitHub |
| `test_limpar_memoria` | o "apagar tudo" mentir e deixar conversa pra trás |
| `test_prompt_fixas` | o relógio voltar pro meio do prompt e matar o cache |
| `test_cors` | o CORS voltar a aceitar qualquer origem |

---

## 🩹 Quando der ruim

| Erro | Causa |
|---|---|
| `ENOENT: package.json` | rodou `npm` na raiz — vá pra `frontend/` |
| `No module named 'backend'` | rodou Python dentro de `backend/` — use `uvicorn main:app` de dentro de `backend/` |
| `address already in use` | já tem algo na 8042 ou 1425 |
| Tela branca no app | o backend não subiu — rode o `Hana.cmd` |
| Ela não responde no Discord | falta `HANA_OWNER_ID` no `.env` |
| `fts5: syntax error` | atualize — foi corrigido |

---

## 📚 Documentação

| 📄 | |
|---|---|
| [MEMORIA.md](backend/docs/MEMORIA.md) | 🧠 as três memórias, por dentro |
| [ARCHITECTURE.md](backend/docs/ARCHITECTURE.md) | visão geral |
| [MODULE_CONTRACT.md](backend/docs/MODULE_CONTRACT.md) | como escrever um módulo |
| **Swagger** | `http://localhost:8042/docs` — **em português** |

---

## ⚖️ Licença

**AGPL-3.0-only.** Veja [LICENSE](LICENSE).

Em português claro: use, modifique e distribua à vontade — mas se rodar isto
como serviço na web, **tem que abrir o código**. É a licença que impede alguém
de pegar este projeto, vender como SaaS e fechar.

A identidade **Hana Nakamura**, a marca e os assets do personagem são
protegidos separadamente. Veja [NOTICE](NOTICE) e [TRADEMARK.md](TRADEMARK.md).

---

<div align="center">

  <h2>⭐ Star History</h2>

  <br><br>

  <img src="https://count.getloli.com/@Naka_Naka?name=Naka_Naka&theme=gelbooru&padding=7&offset=0&align=top&scale=1&pixelated=1&darkmode=auto" alt="Moe Counter" />

  <br/><br/>

  **🌸 Feita com cuidado, rodando em casa. 🌸**

</div>
