"""Excepciones específicas entre pares de habilidades.

El brief permite excepciones puntuales "cuando exista una interacción
real que no pueda inferirse mediante tags generales", pero prohíbe
resolver el sistema con una tabla de resultados hardcodeados. Cada
entrada acá debería:

  1. Referenciar habilidades concretas de dos campeones concretos.
  2. Traer una `justification` no vacía explicando por qué el modelo
     estructural genérico (`effects`, `tactical_uses`, `StackingMechanic`)
     no alcanza para capturarla.
  3. Traer una `condition` no vacía.

Estado en el hito 1.5: **vacío**. Las dos excepciones del hito 1 (S01:
"el daño verdadero ignora escudos", S02: "Indestructible revierte cargas
de Hemorrhage") resultaron ser afirmaciones falsas — no interacciones
reales que las reglas generales no pudieran capturar. Al modelar
`Effect.damage_type`, `EffectType.SHIELD_FROM_STORED` y
`EffectType.CONVERT_SHIELD_TO_HEAL` estructuralmente
(`reasoning/rules/general.py`: `DamageTypeAndShieldRule`), ambas
quedaron cubiertas correctamente por reglas generales, sin necesitar
ninguna excepción. Que este módulo pueda quedar vacío es, en sí, la
validación del principio "primero las reglas generales, la excepción es
el último recurso".

Sigue vacío en el hito 1.6. La regla `MitigationAndDisruptionRule`
mencionada en versiones anteriores de este docstring fue eliminada:
inferría "INTERRUPT niega STACK_APPLICATION" de forma general y falsa
(un pull o un CC breve no cancela por definición un ataque básico, un
efecto on-hit ni una pasiva). Su eliminación no dejó ninguna interacción
real huérfana que este módulo debiera cubrir como excepción puntual —
ver docs/decisiones-tecnicas.md, hito 1.6.

`tests/test_no_hardcoded_pairs.py` obliga a que este archivo tenga como
máximo `MAX_SPECIFIC_INTERACTIONS` entradas y que ninguna tenga campos
vacíos.
"""

from __future__ import annotations

from dataclasses import dataclass

from lol_reasoner.domain.enums import Factor, Phase, Polarity
from lol_reasoner.reasoning.context import ReasoningContext
from lol_reasoner.reasoning.rules.base import RuleEffect
from lol_reasoner.reasoning.trace import FactRef

MAX_SPECIFIC_INTERACTIONS = 10


@dataclass(frozen=True, slots=True)
class SpecificInteraction:
    id: str
    candidate_champion: str
    candidate_ability_slot: str
    enemy_champion: str
    enemy_ability_slot: str
    factor: Factor
    polarity: Polarity
    delta: float
    text: str
    condition: str
    justification: str
    phases: frozenset[Phase]
    category: str = "specific_kit_exception"

    def evaluate(self, ctx: ReasoningContext) -> list[RuleEffect]:
        if ctx.candidate.id != self.candidate_champion or ctx.enemy.id != self.enemy_champion:
            return []
        if ctx.phase not in self.phases:
            return []
        cand_ability = next((a for a in ctx.candidate_abilities() if a.slot == self.candidate_ability_slot), None)
        enemy_ability = next((a for a in ctx.enemy_abilities() if a.slot == self.enemy_ability_slot), None)
        if cand_ability is None or enemy_ability is None:
            return []
        return [
            RuleEffect(
                factor=self.factor,
                polarity=self.polarity,
                delta=self.delta,
                text=self.text,
                premises=(
                    FactRef(f"{ctx.candidate.id}.abilities.{cand_ability.slot}.name", cand_ability.name),
                    FactRef(f"{ctx.enemy.id}.abilities.{enemy_ability.slot}.name", enemy_ability.name),
                ),
                condition=self.condition,
                category=self.category,
            )
        ]


SPECIFIC_INTERACTIONS: tuple[SpecificInteraction, ...] = ()

assert len(SPECIFIC_INTERACTIONS) <= MAX_SPECIFIC_INTERACTIONS
