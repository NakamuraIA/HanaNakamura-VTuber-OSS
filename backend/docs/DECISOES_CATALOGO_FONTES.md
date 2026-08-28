# Decisões — De onde vem o catálogo de modelos

Status: decisões tomadas em 2026-08-01. Implementação ainda não começou.

Este documento complementa `DECISOES_ARQUITETURA_CATALOGO.md`. Ele responde uma
pergunta que o outro não respondia: **de onde a Hana tira a lista de modelos de
cada provider**.

Onde os dois divergirem, este aqui é mais novo. A seção "Correções ao documento
anterior" lista as diferenças.

---

## 1. A regra central

Nem todo provider precisa de tabela no banco. Depende do que o endpoint
(endereço da API que lista modelos) entrega.

### Em execução existem só dois casos

```text
endpoint bom      → sem linha no banco, lê do endpoint (cache RAM)
qualquer outro    → lê do banco
```

Só isso. A pergunta que decide é uma: **o endpoint basta sozinho?**

```text
tem endpoint?  não  ──────────────────────> banco
               sim ──> é bom?  não ───────> banco
                               sim ───────> endpoint, sem banco
```

### "Híbrido" não é um terceiro modo

É uma **marca** que diz de onde o crawler tira informação. Em execução, provider
híbrido se comporta igual a estático: a Hana lê do banco.

| Marca | Endpoint | Em execução lê | O crawler usa |
| --- | --- | --- | --- |
| **Full endpoint** | bom | endpoint | — (não precisa de crawler) |
| **Híbrido** | existe, não basta | **banco** | endpoint + documentação + web |
| **Estático** | não existe | banco | documentação + web |

O erro fácil de cometer: achar que híbrido consulta o endpoint durante uma
conversa. Não consulta. O endpoint só entra quando **você** manda o crawler
rodar.

```text
em execução:   Hana ──> banco

quando você manda:   crawler ──> endpoint / doc / web
                              ──> propõe JSON
                              ──> você aprova
                              ──> banco
```

---

## 2. Classificação por provider

Medido em 2026-08-01 chamando os endpoints reais com as chaves locais.

| Provider | Endpoint lista? | Endpoint descreve? | Padrão | Estado |
| --- | --- | --- | --- | --- |
| **OpenRouter** | sim | **sim** (preço, contexto, modalidades, parâmetros) | full endpoint | já é assim |
| **Maritaca** | sim (6 modelos) | parcial (só `context_length`) | **full endpoint** | mudar: sai do banco |
| **Qwen** | sim (89 modelos) | não (`id`, `created`, `object`, `owned_by`) | **híbrido** | migrar |
| **Groq** | sim (já usa) | não (falta `supportsTools` etc.) | híbrido | **parado** |
| **DeepSeek** | não (2 modelos fixos) | não | estático | já é assim |

**OpenRouter é o único endpoint que realmente presta.** Os outros listam nome e
nada mais.

**Maritaca vai para full endpoint** para não sujar o banco com 6 linhas que a
API já entrega. Se der problema, volta para híbrido e o crawler assume.

**Groq está parado de propósito.** O acesso dele muda por plano (free /
developer / enterprise), e a conta hoje é free. Isso torna a lista instável de
um jeito que ainda não foi decidido como tratar. Não migrar até resolver.

---

## 3. O crawler

O crawler é uma LLM com prompt específico, não um robô de varredura.

### As fontes dele

Ele tem ferramentas e escolhe conforme o provider:

| Situação | De onde ele tira |
| --- | --- |
| provider tem endpoint | puxa do endpoint |
| endpoint não diz tudo | endpoint **+** documentação **+** busca na web |
| provider sem endpoint | documentação e busca na web |
| documentação difícil | você baixa a página e ele analisa |

A busca usa Tavily ou outra ferramenta de pesquisa. É por isso que o crawler é
uma LLM e não um script: ele precisa **ler** documentação e entender, não só
baixar JSON.

Exemplo: um provider como a OpenAI não tem endpoint que descreva capacidades,
mas tem documentação boa. O crawler lê a doc e monta o registro.

**Ele nunca age sozinho.**

```text
1. você inicia (botão ou pedido)
2. ele pesquisa (endpoint do provider, documentação, OpenRouter como referência)
3. devolve saída estruturada em JSON
4. pergunta: adicionar? alterar? remover?
5. só depois da sua confirmação ele grava
```

Regras:

- Sincronização nunca acontece durante uma conversa.
- Remover é sempre pergunta, nunca ação automática.
- "Remover" tem alternativa: **marcar como descontinuado**. O modelo continua no
  banco e continua aparecendo no front, com aviso. Se você usar mesmo assim, é
  por sua conta.
- Você pode pedir um modelo específico: *"busca esse modelo nesse provider e
  adiciona"*.
- Você pode pedir para investigar um provider que ainda nem tem código, só para
  ver o que existe lá.
- O crawler **não precisa saber de plano ou região**. Ele lista o que achar.
  Descobrir que um modelo não está liberado para você é problema de execução,
  não do catálogo.

Cadastro manual continua valendo, por três caminhos: pelo crawler, pelo Swagger
(JSON) ou por função Python.

---

## 4. Endpoint responde sobre acesso, não sobre o mundo

Descoberta desta sessão, com dois casos reais:

- Groq: o modelo `qwen/qwen3.6-27b` aparecia no plano developer e sumiu no free.
- Qwen: `qwen3.7-flash` não funcionava na região da conta e semanas depois passou
  a funcionar, sem nada mudar do lado da Hana.

```text
endpoint responde:  "o que a minha chave alcança hoje"
banco responde:     "o que eu registrei que existe"
```

São perguntas diferentes. A decisão é aceitar isso: a Hana é local, de um
usuário só, e só interessa o que ela consegue chamar. Não vamos pedir ao crawler
que descubra modelos fora do plano.

Consequência aceita: num provider full endpoint, um modelo de plano superior
simplesmente não aparece, sem aviso.

---

## 5. Modelo que some do endpoint

Dois casos reais no banco hoje: `qwen3.6-max-preview` e `qwen3.6-plus` estão
gravados e **não voltam** no endpoint do Qwen.

No híbrido, quando o crawler encontra essa situação, ele pergunta. Opções:

```text
manter sem aviso
marcar como indisponível
marcar como descontinuado
remover
```

Sumir do endpoint **não prova** que o modelo morreu — pode ser só perda de
acesso. Por isso a pergunta padrão não é "remover?".

Em full endpoint não existe essa pergunta: sumiu do endpoint, sumiu da lista.

---

## 6. Modelo escolhido que fica indisponível

Se `settings` aponta para um modelo que não responde mais:

- a Hana **não** troca sozinha;
- **não** volta para o modelo anterior;
- **não** volta para um padrão;
- a chamada falha (404), o erro aparece no console e a Hana responde com a
  mensagem de falha dela;
- a configuração continua salva como está.

Você troca o modelo no frontend quando quiser. Enquanto não trocar, não funciona.

Motivo: uma atualização automática de catálogo nunca deve mudar em silêncio qual
modelo está conversando com você.

---

## 7. Identidade do modelo

`model_id` é o texto que **aquele provider** aceita na chamada. Sempre relativo
ao provider.

O mesmo modelo aparece quantas vezes for necessário, uma linha por provider:

```text
deepseek-v4-flash                    provider = deepseek
deepseek/deepseek-v4-flash           provider = openrouter
deepseek-v4-flash-0731               provider = qwen   (Alibaba hospeda DeepSeek)
```

Isso não é duplicação. Modelo aberto muda de provider para provider:
quantização diferente, trava de segurança diferente, comportamento diferente.
Mesmo peso não é mesmo produto.

**Não haverá** entidade "modelo" separada, nem campo `family`, nem `base_model`.
A chave continua `(provider, model_id)`.

### Sufixo de versão

O sufixo faz parte da identidade — **dentro do provider que o expõe**:

```text
DeepSeek direto:  deepseek-v4-flash        (a API rejeita o -0731)
Alibaba/Qwen:     deepseek-v4-flash-0731   (aqui o -0731 É o id)
OpenRouter:       tem os dois como modelos separados, com preços diferentes
```

Regra prática: **`model_id` é o que o endpoint aceita.** Documentação de
divulgação do provider não é fonte confiável disso — a doc da DeepSeek chama
`DeepSeek-V4-Flash-0731` de "MODEL VERSION", e esse texto não funciona na
chamada.

---

## 8. Raciocínio

Um booleano não basta. Estrutura decidida:

```text
sem raciocínio:
    supports_reasoning = false

com raciocínio, sem níveis:
    supports_reasoning = true
    reasoning_modes    = null        → front mostra só ligado/desligado

com níveis:
    supports_reasoning = true
    reasoning_modes    = ["low", "medium", "high"]
```

- Os nomes dos níveis são os **do provider**, guardados como estão. O provider
  sabe traduzir na hora da chamada.
- Se a documentação não informa níveis, **não inventar níveis**. Fica
  ligado/desligado.
- O padrão ao selecionar um modelo no front é **desligado**. Você liga se quiser.

Exemplo real: o Qwen só liga e desliga; não se sabe se tem níveis, então não tem.

---

## 9. Saída estruturada

```text
supports_structured_output = true   → usa o formato nativo da API
supports_structured_output = false  → fallback por prompt ("responda só em JSON")
```

Quem mais precisa disso é o crawler, que devolve JSON. Nativo é mais garantido
que pedir no prompt, por isso é a preferência quando existir.

---

## 10. Catálogo e configuração são coisas diferentes

```text
catálogo:  "este modelo suporta raciocínio alto?"      → fato observado
settings:  "o usuário escolheu raciocínio alto"        → escolha
```

`settings` guarda e restaura ao reiniciar: provider, modelo, raciocínio
ligado/desligado, nível, provider de TTS, voz, velocidade. Reiniciar a Hana não
pode exigir reconfigurar tudo.

O catálogo nunca guarda preferência. `settings` nunca guarda capacidade.

---

## 11. Capacidade pertence ao modelo, não ao arquivo do provider

Hoje `provider_selector/qwen/provider.py` decide capacidades **por provider**,
com valores escritos à mão:

```python
"supports_audio": False,      # vale para todo modelo Qwen
"supports_video": False,      # vale para todo modelo Qwen
"supports_streaming": True,   # vale para todo modelo Qwen
```

Isso já está errado: o `qwen3.6-flash` aceita imagem **e vídeo** na entrada.

Destino: essas respostas saem do arquivo e passam a vir do banco, por modelo.
O `ProviderSelector` lê; o provider só executa.

Isso importa além da estética. As modalidades de **entrada** mudam a regra de
execução — se o modelo aceita áudio, a Hana manda o áudio direto; se não aceita,
ela transcreve antes. Com a capacidade chutada no arquivo, ela transcreve à toa
ou manda o que o modelo não entende.

---

## 12. Escopo: só LLM agora

STT, TTS, imagem e embeddings terão tabelas próprias **depois**, cada uma com as
perguntas que fazem sentido para ela (voz e idioma para TTS, dimensões para
embeddings). Não criar essas tabelas agora.

Duas decisões já tomadas para quando chegar a hora:

- TTS e STT vão para o banco **mesmo tendo endpoint**. São poucos modelos e a
  complexidade do full endpoint não se paga. Vale inclusive para o Edge, que é
  local: entra como registro manual.
- Busca na web nativa do modelo **não será usada**. Dá muito trabalho de
  configurar por provider. Quem quiser busca usa MCP (Tavily como módulo).

---

## 13. Correções ao documento anterior

`DECISOES_ARQUITETURA_CATALOGO.md` precisa de dois ajustes:

**a) Princípio 1 ("uma fonte da verdade").** Continua valendo para quem está no
banco, mas não é mais universal. Provider full endpoint não tem linha no banco —
e isso é o desejado, não uma exceção temporária. A frase precisa dizer "para os
providers que usam catálogo local".

**b) O exemplo do sufixo.** O texto usa `deepseek-v4-flash` vs
`deepseek-v4-flash-0731` como exemplo de "registros diferentes". A regra está
certa, o exemplo estava sem escopo: no DeepSeek direto o `-0731` é rejeitado; no
Qwen e no OpenRouter ele é um id válido. Ver a seção 7.

---

## 14. Como o trabalho é feito

A ordem é esta, e não se pula etapa:

```text
1. decidir as regras
2. documentar as regras
3. planejar as etapas do código
4. executar uma etapa
5. validar essa etapa
6. voltar ao 4
```

O código só começa depois que a regra está escrita. Cada etapa é pequena e
validada antes da próxima. Motivo: numa migração grande de uma vez, quando
quebra, não dá para saber onde quebrou.

Hoje estamos entre 1 e 2. Quase nada de código foi alterado.

---

## 15. Pontas soltas

### Resolvidas

**`-br-sp` da Maritaca** — é modelo **e** região: um modelo que existe naquela
região. Entra como registro próprio, não como rota.

**Groq com plano variável** — não é problema do catálogo. O Groq é híbrido; se a
lista muda com o plano, o crawler traz o que achar e você descobre testando. Não
vamos modelar plano nem região no schema.

**Código de TTS/STT** — sai de `modules/voice/` e vai para `providers/`, junto
com os providers de LLM. Um provider pode oferecer só TTS (ElevenLabs), só STT,
ou vários. Isso é trabalho de uma etapa futura, não agora.

### Adiadas de propósito

- `model_overrides` por domínio — decidir quando existir o segundo domínio.
- Limite de "poucos modelos" que justifica banco em vez de endpoint.
- Ordem de migração e rollback — a ordem antiga (Qwen → Groq → Maritaca) foi
  feita antes de saber quais providers têm endpoint, então precisa ser refeita.

Nenhuma delas bloqueia começar o código.

---

## 16. Dono único da escrita

Toda escrita em `llm_models` passa obrigatoriamente pelo `LlmModelRepository`.
Nenhum outro módulo executa `INSERT`, `UPDATE` ou `DELETE` direto nessa tabela.

Essa regra foi aplicada na fase 4, em 2026-08-22. `HanaMemory` não possui mais
métodos de modelo, e `catalog_payload` lê a fonte única local uma vez.

**Fluxo atual:**

```text
backend/api/routers/modelos.py       → LlmModelRepository
backend/api/services/catalog.py      → LlmModelRepository
backend/providers/...                → LlmModelRepository para capacidades locais
backend/bd/llm.py                    → migração explícita do legado
```

O OpenRouter não entra nessa escrita automática: seu catálogo continua vindo
do endpoint dinâmico. Apenas um modelo manual criado pelo usuário pode existir
localmente com provider `openrouter`.

---

## 17. Achados de código nesta sessão

Não corrigidos, só registrados.

| Onde | O quê |
| --- | --- |
| `openrouter/catalog.py:120` e `:135` | usa `logger` sem importar. Quando a busca falha, o `except` estoura `NameError` e o erro real some, virando `openrouter_models_error: name 'logger' is not defined` |
| `qwen/provider.py:41-63` | capacidades fixas por provider; `supports_video: False` está errado para `qwen3.6-flash` |
| catálogo histórico | Maritaca tinha 3 linhas e o endpoint devolvia 6 (faltavam os `-br-sp`) |
| catálogo histórico | `qwen3.6-max-preview` e `qwen3.6-plus` não voltavam no endpoint do Qwen |
