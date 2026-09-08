"""Registro central de reglas generales — un solo lugar que combina
`general.py` y `stacking.py`, y de donde sale el universo completo de
categorías que alimenta el denominador de cobertura de confianza
(`scoring/confidence.py`).

Guardrails de complejidad (v1.6.1). El hito 1.6 tenía un `assert` duro de
"máximo 15 clases de regla". Ese número no medía complejidad real: con 11
reglas no apretaba nada, pero fue el argumento que justificó fusionar la
regla de mitigación dentro de la de daño — y esa fusión produjo una clase
de 226 líneas con cinco categorías donde se escondieron tres escaneos
unidireccionales durante todo un hito.

Lo que se verifica ahora:

  * `MAX_GENERAL_RULES` es BLANDO: un tope holgado, verificado en tests
    con un mensaje que invita a revisar, no un `assert` en import time que
    empuje a fusionar conceptos distintos para no romperlo.
  * `MAX_CATEGORIES_PER_RULE` es DURO y es el que de verdad detecta una
    regla monolítica: una regla que declara muchas categorías está
    respondiendo muchas preguntas. Con este control, la ex-G03 habría
    fallado el día que se fusionó.
  * Toda entrada que pueda puntuar debe traer `causal_key`
    (tests/test_causal_dedup.py), para que ninguna causa se cuente dos
    veces por reaparecer en varias fases.
"""

from __future__ import annotations

from lol_reasoner.reasoning.rules.base import Rule
from lol_reasoner.reasoning.rules.general import GENERAL_RULES
from lol_reasoner.reasoning.rules.stacking import STACKING_RULES

# Guardrail BLANDO: se verifica en tests, no en import time.
MAX_GENERAL_RULES = 20

# Guardrail DURO de monolitos: una regla que responde más de tres
# preguntas distintas debe partirse (ver docstring).
MAX_CATEGORIES_PER_RULE = 3

ALL_GENERAL_RULES: tuple[Rule, ...] = GENERAL_RULES + STACKING_RULES

# Universo completo de categorías que CUALQUIER regla general puede
# producir (incluyendo las que solo aparecen vía RuleEffect.category
# override) — declarado explícitamente por cada Rule.categories, no
# inferido de una corrida puntual. Es el denominador de cobertura.
ALL_CATEGORIES: frozenset[str] = frozenset().union(*(r.categories for r in ALL_GENERAL_RULES))
