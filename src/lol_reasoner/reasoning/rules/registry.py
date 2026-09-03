"""Registro central de reglas generales — un solo lugar que combina
`general.py` y `stacking.py`, y de donde sale el universo completo de
categorías que alimenta el denominador de cobertura de confianza
(`scoring/confidence.py`).

Guardrail temporal de esta V0 (documentado en general.py, revisable al
incorporar los otros ocho campeones): máximo 15 clases de regla general.
"""

from __future__ import annotations

from lol_reasoner.reasoning.rules.base import Rule
from lol_reasoner.reasoning.rules.general import GENERAL_RULES
from lol_reasoner.reasoning.rules.stacking import STACKING_RULES

MAX_GENERAL_RULES = 15

ALL_GENERAL_RULES: tuple[Rule, ...] = GENERAL_RULES + STACKING_RULES

assert len(ALL_GENERAL_RULES) <= MAX_GENERAL_RULES, (
    f"Guardrail temporal de la V0: {len(ALL_GENERAL_RULES)} reglas generales > {MAX_GENERAL_RULES}. "
    "Antes de sumar una más, considerá si una regla existente puede extenderse."
)

# Universo completo de categorías que CUALQUIER regla general puede
# producir (incluyendo las que solo aparecen vía RuleEffect.category
# override) — declarado explícitamente por cada Rule.categories, no
# inferido de una corrida puntual. Es el denominador de cobertura.
ALL_CATEGORIES: frozenset[str] = frozenset().union(*(r.categories for r in ALL_GENERAL_RULES))
