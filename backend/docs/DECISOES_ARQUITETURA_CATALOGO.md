# Decisões de Arquitetura — Catálogo de Modelos

Status: decisões aprovadas; implementação em migração incremental.

Este documento é o contrato de arquitetura do catálogo de LLMs (modelos de
conversa) da Hana. Ele registra regras e motivos para que pessoas e agentes
novos não precisem adivinhar decisões já tomadas.

## Objetivo

O catálogo deve diminuir a carga de entendimento do backend, manter uma fonte
confiável de conhecimento sobre modelos e tornar providers fáceis de adicionar,
remover e testar. Não é uma refatoração apenas estética.

## Escopo atual

Esta etapa trata somente LLMs. Imagem, áudio e embeddings terão catálogos
próprios quando forem necessários, pois respondem perguntas diferentes e não
devem gerar uma tabela cheia de campos vazios.

```text
backend/catalog/
├── llm/
│   ├── repository.py
│   ├── synchronizer.py
│   ├── normalizer.py
│   └── resolver.py
├── image/
├── audio/
└── embedding/
```

## Princípios inegociáveis

1. **Uma fonte da verdade.** O SQLite local é a fonte usada pela Hana em tempo
   de execução. Listas hardcoded são apenas fallback (caminho provisório) de
   migração e serão removidas depois da validação.
2. **Uma responsabilidade por componente.** Cada módulo tem uma tarefa clara;
   não misturar internet, regras e SQLite no mesmo arquivo.
3. **Conhecimento observado, não verdade absoluta.** Dados do catálogo vieram
   de uma fonte em uma data; guardar origem e momento da observação permite
   auditar e corrigir informações.
4. **Sincronização não é execução.** Atualizar catálogo nunca acontece durante
   uma conversa. APIs externas não podem aumentar a latência da resposta.
5. **Cache não é fonte da verdade.** A RAM acelera leituras; o SQLite preserva
   os dados ao reiniciar a Hana.
6. **Refatoração incremental.** Criar, testar, migrar um provider e somente
   então remover o caminho antigo. Nunca migrar todos de uma vez.
7. **Começar pequeno.** Não criar suporte a múltiplos usuários, imagem, áudio
   ou bibliotecas externas antes de existir uma necessidade real.

## Palavras importantes

- **Provider (provedor):** serviço/API que recebe a chamada, como DeepSeek ou
  OpenRouter.
- **Model ID (identificador):** nome exato que aquele provider aceita, como
  `google/gemma-4-31b-it` no OpenRouter.
- **Streaming (transmissão gradual):** resposta chega em partes, em vez de só
  no fim.
- **Repository (repositório):** única camada que lê e grava dados do catálogo
  no SQLite.
- **Cache:** cópia temporária em RAM para evitar consultas repetidas.
- **Fallback legado:** lista antiga usada temporariamente se o SQLite ainda não
  tiver o modelo durante a migração.

## Separação de responsabilidades

```text
Frontend/API pede atualização
        ↓
Synchronizer coordena
        ↓
Adapter busca dados brutos da fonte
        ↓
Normalizer converte para o formato interno
        ↓
Resolver aplica regras de origem e correções
        ↓
ModelRepository lê/grava SQLite
```

- `ModelRepository` não chama APIs externas; ele persiste e consulta modelos.
- `Adapter` conversa com uma fonte externa, mas nunca acessa SQLite.
- `Normalizer` apenas traduz formatos; não acessa internet ou banco.
- `Synchronizer` coordena uma atualização manual, mas não define qual dado
  vence em caso de conflito.
- `Resolver` aplica regras puras, como preservar uma correção manual de um
  campo.
- Providers usam o catálogo para conhecer o modelo e apenas conversam com a
  API escolhida.

## O que pertence a cada lugar

| Lugar | Guarda | Exemplo |
| --- | --- | --- |
| Catálogo | fatos observados sobre modelos | contexto, streaming, tools, preço |
| `settings` | preferências do único usuário local | temperatura padrão, provider favorito |
| Execução | escolha válida só nesta chamada | `tool_choice`, temperatura sobrescrita |
| Estado | situação temporária do sistema | cache RAM, último erro de sincronização |

O catálogo nunca guarda preferências. A Hana tem um usuário local hoje, então
não haverá tabela de usuários ou preferências por usuário nesta etapa.

## Modelo, origem e correções manuais

`llm_models` guarda o conhecimento observado. Um modelo pode ter dados de
fontes como `official_api`, `openrouter`, `legacy` ou `manual`, sempre com data
de observação.

Uma correção manual de um campo não substitui nem apaga o dado observado. Ela
fica em `model_overrides`, identificada por provider, modelo e campo. Ao ler um
modelo, a Hana calcula:

```text
dados observados + correções manuais = dados efetivos usados pela Hana
```

Assim, uma correção manual de contexto não impede que o preço seja atualizado
pela API oficial. A interface deve permitir remover uma correção e voltar ao
valor automático. Um modelo totalmente manual, sem fonte externa, pode ser
removido inteiro somente após confirmação clara.

Capacidades que entram nesta etapa: `supports_streaming`, suporte a tools no
streaming e `supports_reasoning`, além dos campos já existentes, como visão,
contexto e modalidades.

## Sincronização, falhas e ciclo de vida

O usuário inicia a sincronização por botão global ou por provider. Ela coleta
fontes, atualiza o SQLite e invalida o cache do provider atualizado. Durante
uma conversa, a Hana usa a informação local em RAM; nunca consulta banco ou
API a cada token.

> Ausência de resposta não é evidência de ausência de dados.

- Falha ou timeout da fonte: manter modelos existentes, registrar erro e não
  mudar seu estado.
- Sincronização bem-sucedida sem um modelo antes conhecido: marcar
  `nao_observado`, sem apagar.
- Duas sincronizações bem-sucedidas seguidas sem observar o modelo: marcar
  `descontinuado`, ainda sem apagar automaticamente.
- Um modelo manual não é alterado por sincronização externa.
- Modelo descontinuado continua utilizável com aviso; a interface o mostra no
  fim da lista e não o oferece como escolha nova padrão.

Origem e ciclo de vida são conceitos separados. Por exemplo, um modelo pode ser
`manual` na origem e `ativo` no estado; não são opções excludentes.

## Streaming e OpenRouter

A decisão de streaming pertence ao modelo, não apenas ao provider. Antes de
começar a resposta, a Hana consulta ou recupera do cache as capacidades do
modelo e mantém essa cópia durante tools e streaming. Se ele não suportar
streaming, a Hana responde sem streaming e mostra um aviso de que a primeira
resposta pode demorar mais.

Toda decisão sobre capacidades acontece em um único ponto antes da chamada ao
provider. Esse ponto escolhe a estratégia de execução: streaming normal,
streaming com tools, resposta normal ou tools sem streaming. Depois que a
execução começa, o provider apenas aplica a estratégia recebida.

```text
sem tools                         -> streaming, se o modelo suportar
tools + tools no streaming        -> streaming com tools
tools sem tools no streaming      -> tools sem streaming neste turno
```

No OpenRouter, o catálogo guarda o ID aceito pelo OpenRouter. Uma rota como
`cerebras` ou `auto` é uma escolha de execução, não muda o modelo nem cria um
ID interno na Hana. O OpenRouter faz essa tradução.

O identificador completo do modelo é parte da identidade, inclusive sufixos de
versão, data ou fine-tuning. Por exemplo, `deepseek-v4-flash` e
`deepseek-v4-flash-0731` são registros diferentes. A Hana não pode remover,
encurtar ou “embelezar” esse sufixo durante normalização, sincronização ou
exibição. O label pode ser amigável, mas o `model_id` deve permanecer exato.

## Fontes e compatibilidade temporária

Cada provider direto usa sua fonte oficial quando ela existir. O OpenRouter
sincroniza seus próprios modelos; a lista dele não prova que um modelo está
disponível diretamente em outro provider. Onde ainda não houver API oficial,
usar o catálogo legado temporariamente, identificado como tal e com aviso.

Enquanto um provider ainda estiver em migração, o `ProviderSelector` pode
completar temporariamente um registro legado com capacidades padrão do
provider, como streaming. Esse caminho é marcado como fallback legado e
existe somente para preservar o comportamento anterior; a decisão continua
passando pela `ExecutionPolicy`, e desaparece quando o catálogo do provider
passar a informar capacidades por modelo.

Não instalar LiteLLM, models.dev, llm-registry ou bibliotecas semelhantes agora.
Após a arquitetura básica estar validada, elas podem ser avaliadas como fontes
auxiliares, sem substituir a confirmação local e sem tomar o controle dos
providers.

## Estado atual da migração e testes

Desde a fase 4, modelos locais e manuais usam somente `llm_models`.
`custom_models` em `settings` e os métodos de modelo de `HanaMemory` foram
migrados e removidos sem apagar linhas válidas.

Testes de lógica usam SQLite temporário. Testes de integração usam banco de
teste isolado. Nunca usar o banco pessoal de runtime da Hana em testes. Cada
provider só perde o fallback legado depois de leitura no repositório,
sincronização e geração terem testes aprovados.

## Schema (estrutura do banco)

O banco do catálogo é criado no caminho central definido em `backend/paths.py`:
`runtime/hana_memory.sqlite3`. `paths.py` apenas define caminhos; o
As funções em `backend/bd/` criam e atualizam as tabelas.

Toda alteração estrutural precisa existir em uma migração Python versionada.
Não basta executar SQL manualmente no computador de desenvolvimento. Na
na inicialização, a migração verifica a existência das estruturas antigas,
copia os dados válidos e só então remove o legado. Repetir é neutro.

O Alembic não faz parte desta etapa. A solução local deve continuar pequena,
testável e verificável no DBeaver. Uma instalação nova deve criar o banco e o
schema; uma instalação antiga deve atualizar o schema sem apagar memória.

## Critério de sucesso da migração de um provider

Cada provider deve ser migrado sozinho. A migração do DeepSeek só será
considerada transparente se continuar funcionando:

- conversa normal;
- streaming;
- tools;
- seleção de modelo;
- fallback temporário para `deepseek/catalog.py`;
- frontend sem alteração de contrato.

Durante a transição, o fallback deve gerar um log explícito, por exemplo:

```text
ModelRepository não encontrou 'modelo-exemplo' para 'deepseek'; usando catálogo legado.
```

Um provider só será considerado oficialmente migrado quando:

1. o caminho normal não consultar mais seu `catalog.py`;
2. os testes específicos e a suíte completa passarem;
3. o fallback não for acionado nos modelos válidos do banco;
4. o comportamento observado continuar equivalente ao anterior.

Somente depois desses quatro critérios o catálogo legado daquele provider pode
ser removido.
