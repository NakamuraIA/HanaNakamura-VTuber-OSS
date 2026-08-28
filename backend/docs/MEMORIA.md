# A memória da Hana

> **Atualização 2026-08-05:** a tabela `facts` citada neste doc foi removida
> (era espelho duplicado de `memory_items`, nunca lida pelo caminho de
> verdade do chat). A "memória longa" agora é só `memory_items`
> (`backend/memory/store.py`, `MemoryStore`). O mapa das tabelas também está em
> `docs/TABELAS_BANCO_DE_DADOS.md`. As seções históricas abaixo ainda precisam
> de revisão antes da publicação.

O mapa. Se você só for ler uma linha, é esta:

> **Código = quem ela é. Banco = o que ela viveu.**

---

## 1. Onde mora

Um arquivo só, SQLite:

```
runtime/hana_memory.sqlite3
```

SQLite é banco sem servidor — é *um arquivo*. Backup é copiar. Reset é apagar.

`.db` e `.sqlite3` são a mesma coisa; só o nome muda.

---

## 2. As seis tabelas

| Tabela | O que é | Vai pro prompt? |
|---|---|---|
| `messages` | **memória curta** — a conversa, por canal | ✅ sim |
| `facts` | **memória longa** — fatos que a Hana salva | ✅ só o que combina (RAG) |
| `pinned` | **memória fixa** — regras suas | ✅ sempre, inteira |
| `chat_log` | histórico da tela | ❌ **nunca** |
| `settings` | configuração do app | ❌ nunca |
| `llm_models` | catálogo de modelos, domínio separado | ❌ nunca |

**Essa divisão é a coisa mais importante do arquivo.** As três primeiras custam
token toda mensagem. As três últimas são de graça.

---

## 3. A diferença entre curta e longa

Curta guarda **conversa**. Longa guarda **fato**.

```
CURTA (crua):
  user: nossa, odeio quando vc escreve muito
  hana: desculpa!
  user: sério, escreve curto
  hana: ok

LONGA (destilado):
  "Nakamura não gosta de respostas longas"
```

Quatro mensagens viram uma frase. Por isso o RAG funciona na longa e não na
curta — você não busca significado num monte de "pera" e "kkkk".

| | Curta | Longa |
|---|---|---|
| guarda | **toda** mensagem | só o que importa |
| escolhe por | **tempo** (as 80 últimas) | **assunto** (o que combina) |
| idade | só recente | qualquer uma |
| quem escreve | automático | a Hana, sozinha |

---

## 4. A memória fixa (`pinned`)

É a continuação do system prompt — mas em **banco**, não em código, pra você
editar sem tocar em arquivo.

- **Só a Nakamura escreve.** Não existe ferramenta que deixe a Hana escrever aqui.
- Entra em **toda** resposta, sem passar por busca.
- `position` define a ordem (menor primeiro). O que vem antes pesa mais.
- `enabled = 0` tira do prompt sem apagar — bom pra testar se uma regra é a
  causa de algum comportamento estranho.

Tipos: `regra`, `giria`, `tarefa`, `fato`.

---

## 5. A ordem do prompt

```
1. SYSTEM PROMPT      código    quem ela é
2. PINNED             banco     suas regras
3. FACTS (RAG)        banco     memórias que combinam com a pergunta
4. MESSAGES           banco     as últimas N falas DO CANAL
5. SUA PERGUNTA       agora     com o carimbo [AGORA]
```

**Por que nessa ordem:** a LLM presta mais atenção no começo e no fim; o miolo
ela lê por cima (o efeito tem nome: *lost in the middle*). Então o que nunca
muda vai no topo, material de consulta no meio, e o que importa agora no fim.

**O relógio fica no fim, junto da pergunta.** Se ficasse no system prompt, o
prefixo mudaria a cada turno e mataria o cache do provider — você pagaria o
prompt inteiro de novo toda mensagem por causa de um relógio.

Como fica na prática:

```
system:    [prompt] + [pinned]
system:    [facts]
user:      [sex 26/07 23:22 - Naka] vou dormir, boa noite Hana
assistant: [sex 26/07 23:22 - Hana] boa noite! descansa
user:      [AGORA - sáb 27/07 14:35 - Naka] oi Hana
```

O carimbo entra **dentro do texto** porque a API só aceita `role` + `content`:
data, autor e canal não atravessam de outro jeito.

---

## 6. O isolamento por canal

`messages` tem a coluna `channel`: `chat`, `discord`, `terminal`, `voice`.

Toda leitura filtra:

```sql
SELECT ... FROM messages WHERE channel = ? ORDER BY id DESC LIMIT 80
```

**Sem esse `WHERE`, o Discord enxerga conversa do terminal.** Foi exatamente
esse o bug que fazia a Hana citar no Discord uma conversa de voz de uma hora
antes.

---

## 7. As travas ficam no banco

Não no código:

```sql
role    CHECK (role IN ('user','assistant'))
channel CHECK (channel IN ('chat','discord','terminal','voice'))
content CHECK (length(content) BETWEEN 1 AND 8000)
```

Motivo: um bug em qualquer caller não consegue sujar a tabela. Trava no código
depende de todo mundo lembrar; trava no banco não esquece.

O que isso barra na prática:
- resultado de ferramenta virando "memória" (a resposta da Hana já é o resumo)
- base64 de imagem entupindo a conversa
- `'Discord'` com maiúscula virando um quinto canal fantasma
- mensagem vazia de turno que falhou no meio

---

## 8. Estado atual da migração

O `MemoryStore` antigo (`store.py`) ainda é a fonte de verdade enquanto o front
não migra. Mas todo `append_event` **espelha** a fala na tabela `messages` nova.

Escrever nos dois lugares é de propósito: a tabela já acumula histórico, então o
dia da troca não tem período cego. Quando o front migrar, muda a leitura e
pronto.

O espelho é travado por teste — se parar, o self-check quebra:

```bash
python -m backend.memory.core
```

---

## 9. A API

`/api/memoria/*` concentra as rotas atuais. A API antiga (`/api/memory/*`) foi
removida depois da migração do último consumidor, o ciclo de sono do frontend.

A regra: **endpoint é substantivo, não verbo.**

```
/memory/{id}/pin       ❌ verbo → vira um endpoint por ação
PUT /memoria/{id}      ✅ substantivo → um pra todas
```

Arquivar, restaurar e mandar pra lixeira são todos `PUT` com `status` diferente.
