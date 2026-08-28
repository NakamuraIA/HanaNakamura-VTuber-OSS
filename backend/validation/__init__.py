"""Validações internas e temporárias para acompanhar as migrações.

Esta pasta não implementa regras da Hana. Ela apenas executa verificações
seguras que Nakamura pode acionar pelo Swagger durante a refatoração.

Contrato:

- leitura do banco principal sempre em modo somente leitura;
- qualquer teste que grave usa um banco temporário descartável;
- respostas não exibem textos pessoais;
- este pacote será removido antes da publicação do repositório.
"""

from __future__ import annotations

from typing import Any


def validation_result(
    *,
    test: str,
    database: str,
    approved: bool,
    evidence: dict[str, Any],
    failure_next_step: str,
) -> dict[str, Any]:
    """Mantém o mesmo formato de resposta em todas as validações do Swagger."""

    return {
        "teste": test,
        "banco_usado": database,
        "resultado": "aprovado" if approved else "falhou",
        "evidencia_resumida": evidence,
        "proximo_passo_em_caso_de_falha": "Nenhum." if approved else failure_next_step,
    }
