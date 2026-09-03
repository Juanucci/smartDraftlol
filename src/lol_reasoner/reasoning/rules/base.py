"""Contrato base de una regla.

Una regla NO escribe en la traza directamente: devuelve una lista de
`RuleEffect` (posiblemente vacía) y es el `RuleEngine` quien las
convierte en `TraceEntry` con id, rule_id y fase ya resueltos. Esto
mantiene a las reglas simples de testear en aislamiento.

Restricción de diseño que se hace cumplir con un test
(`test_no_hardcoded_pairs.py`): una regla *general* no puede mencionar
un `champion.id` ni un `champion.name` literal. Solo puede leer
`axes`, `tags`, `trade_pattern`, `damage_profile` y `abilities[].kind`
/ `.counters` / `.countered_by` / `.cooldown_class`. Las excepciones
específicas entre kits viven aparte, en `specific.py`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from lol_reasoner.domain.enums import Factor, Phase, Polarity
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


class Rule(ABC):
    id: str
    summary: str
    category: str
    phases: frozenset[Phase] = frozenset(Phase)  # por defecto, aplica en todas las fases

    @abstractmethod
    def evaluate(self, ctx: ReasoningContext) -> list[RuleEffect]:
        """Devuelve 0..n efectos para `ctx.candidate` en `ctx.phase`."""
        raise NotImplementedError

    def applies_to_phase(self, phase: Phase) -> bool:
        return phase in self.phases
