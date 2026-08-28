"""Preparação da primeira instalação pública da Hana.

Esta pasta apenas coordena tarefas de instalação. Ela pode chamar os donos dos
schemas em ``bd/`` e importar os padrões públicos em ``catalog/``, mas não
participa do uso diário da Hana.

Contrato:

- os JSONs em ``defaults/`` são moldes de fábrica, não fontes de verdade;
- a Hana em execução lê somente o banco;
- uma instalação existente nunca é alterada automaticamente;
- restauração de catálogo exige confirmação explícita.
"""

