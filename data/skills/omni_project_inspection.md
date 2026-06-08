# Skill: Omni Project Inspection

Use esta skill quando Nakamura pedir para o Omni inspecionar um projeto local sem editar nada.

## Padrao de Chamada

- `mode="inspect"`.
- `task` deve incluir o caminho absoluto do projeto.
- `task` deve dizer claramente: "sem editar arquivos e sem executar acoes destrutivas".
- `acceptance` deve pedir riscos, evidencias, caminhos e proximos passos como texto simples.

## Modelo de Tarefa

```text
Inspecione o projeto <CAMINHO> sem editar nada. Traga os principais riscos tecnicos, arquivos ou areas observadas, evidencias concretas e proximos passos recomendados. Nao toque em .env, nao apague arquivos, nao rode comandos destrutivos e nao faca commit.
```

## Modelo de Acceptance

```text
relatar riscos com evidencias; citar caminhos ou comandos inspecionados; nao editar arquivos; indicar proximos passos
```

## Resposta da Hana

- Se o Omni entregar riscos reais, resuma os pontos principais para Nakamura.
- Se o Omni nao conseguir acessar o projeto, mostre o erro real.
- Se o Omni pedir revisao, explique o que faltou antes de considerar a inspecao concluida.
