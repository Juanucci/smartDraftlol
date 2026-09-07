"""Contrato base de una regla.

Una regla NO escribe en la traza directamente: devuelve una lista de
`RuleEffect` (posiblemente vacía) y es el `RuleEngine` quien las
convierte en `TraceEntry` con id, rule_id y fase ya resueltos. Esto
mantiene a las reglas simples de testear en aislamiento.

Restricción de diseño que se hace cumplir con un test
(`test_no_hardcoded_pairs.py`): una regla *general* no puede comparar el
`.id` de un campeón contra un literal (tabla A-vs-B disfrazada); leer
`.name` para armar texto sí está permitido. Las reglas leen estructura
(`axes`, `tags`, `casting_resource`, `trade_patterns` como resumen no
autoritativo) y, sobre todo, `effects`/`tactical_uses` de las habilidades
disponibles en la fase actual — siempre a través de
`ctx.candidate_abilities()`/`ctx.enemy_abilities()`, nunca accediendo a
`champion.abilities` directo (verificado por
`test_phase_availability.py`, que es lo que hace cumplir `available_from`
estructuralmente). Las excepciones específicas entre kits viven aparte,
en `specific.py`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from lol_reasoner.domain.enums import ConditionKind, Factor, Phase, Polarity
from lol_reasoner.reasoning.context import ReasoningContext
from lol_reasoner.reasoning.trace import FactRef


@dataclass(frozen=True, slots=True)
class RuleEffect:
    factor: Factor
    polarity: Polarity
    delta: float
    text: str
    premises: tuple[FactRef, ...] = field(default_factory=tuple)
    condition: str | None = None
    invalidated_if: str | None = None
    category: str | None = None  # si es None, el engine usa Rule.category
    # Identifica la fuente mecánica exacta ("dueño:slot:effect_type") de
    # la que nace este efecto. Dos RuleEffect (de la MISMA o de distinta
    # regla) que citen el mismo causal_key para el mismo subject se
    # deduplican en el cálculo del score (ver
    # ReasoningTrace.deduped_for_scoring) — evita que una sola capacidad
    # mecánica (p. ej. el escudo de Indestructible) produzca ventajas
    # independientes solo porque dos reglas la explican con matices
    # distintos, o porque la misma regla la repite idéntica en varias
    # fases. None (por defecto) = nunca se deduplica: el comportamiento
    # de reglas basadas en ejes (sin una única fuente de efecto) no cambia.
    causal_key: str | None = None
    # Solo tiene sentido en entradas CONDITIONAL: de qué tipo de
    # incertidumbre se trata (ver domain.enums.ConditionKind). Determina
    # si esta condición puede subir required_skill (solo EXECUTION) o
    # alimentar volatilidad (STRATEGIC) — nunca ambas.
    condition_kind: ConditionKind | None = None


class Rule(ABC):
    id: str
    summary: str
    category: str  # categoría por defecto, usada cuando un RuleEffect no la sobrescribe
    # Universo COMPLETO de categorías que esta regla puede llegar a producir
    # (incluyendo las que solo aparecen vía RuleEffect.category override).
    # Es lo que alimenta el denominador de cobertura en scoring/confidence.py:
    # debe declararse explícitamente, no inferirse, para que el denominador
    # sea exacto y no dependa de qué categorías dispararon en un caso puntual.
    categories: frozenset[str]
    phases: frozenset[Phase] = frozenset(Phase)  # por defecto, aplica en todas las fases

    @abstractmethod
    def evaluate(self, ctx: ReasoningContext) -> list[RuleEffect]:
        """Devuelve 0..n efectos para `ctx.candidate` en `ctx.phase`."""
        raise NotImplementedError

    def applies_to_phase(self, phase: Phase) -> bool:
        return phase in self.phases
