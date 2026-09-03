"""Excepciones específicas entre pares de habilidades.

El brief permite excepciones puntuales "cuando exista una interacción
real que no pueda inferirse mediante tags generales", pero prohíbe
resolver el sistema con una tabla de resultados hardcodeados. Por eso
cada entrada acá:

  1. Referencia habilidades concretas de dos campeones concretos (no
     "quién le gana a quién": el efecto sigue siendo un delta parcial
     en un factor, con condición).
  2. Trae una `justification` no vacía explicando por qué el cruce
     genérico de tags (AbilityCounterRule) no alcanza para capturarla.
  3. Trae una `condition` no vacía.

`tests/test_no_hardcoded_pairs.py` obliga a que este archivo tenga
como máximo `MAX_SPECIFIC_INTERACTIONS` entradas y que ninguna tenga
campos vacíos.
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
        cand_ability = next((a for a in ctx.candidate.abilities if a.slot == self.candidate_ability_slot), None)
        enemy_ability = next((a for a in ctx.enemy.abilities if a.slot == self.enemy_ability_slot), None)
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


SPECIFIC_INTERACTIONS: tuple[SpecificInteraction, ...] = (
    SpecificInteraction(
        id="S01",
        candidate_champion="darius",
        candidate_ability_slot="R",
        enemy_champion="mordekaiser",
        enemy_ability_slot="W",
        factor=Factor.MECHANICAL_INTERACTION,
        polarity=Polarity.PRO,
        delta=0.2,
        text=(
            "Noxian Guillotine (R) de Darius es daño verdadero, que por definición ignora escudos: "
            "Indestructible (W) de Mordekaiser no lo mitiga aunque su tag general de postura defensiva "
            "sugeriría que sí lo hace."
        ),
        condition="solo aplica si Darius conserva el golpe de gracia disponible y Mordekaiser está por debajo del umbral de ejecución",
        justification=(
            "AbilityCounterRule cruza `counters` de Indestructible contra tags de Darius y lo marcaría como "
            "contador general de daño sostenido/auto-ataques; eso es correcto para el resto del kit de Darius "
            "pero es específicamente falso para el componente de daño verdadero del R, porque el daño "
            "verdadero no es mitigable por escudos por definición del tipo de daño. Esta excepción "
            "reintroduce esa porción de valor que el cruce genérico le restaría."
        ),
        phases=frozenset({Phase.LEVEL_6, Phase.FIRST_ITEM, Phase.SIDE_LANE_LATE}),
    ),
    SpecificInteraction(
        id="S02",
        candidate_champion="darius",
        candidate_ability_slot="P",
        enemy_champion="mordekaiser",
        enemy_ability_slot="W",
        factor=Factor.RELIABILITY,
        polarity=Polarity.CONTRA,
        delta=0.15,
        text=(
            "Indestructible (W) de Mordekaiser no solo bloquea el daño sostenido: convierte ese daño en curación, "
            "lo que revierte parte del progreso de las cargas de Hemorrhage (pasiva) de Darius durante el intercambio."
        ),
        condition="solo mientras Mordekaiser mantenga Indestructible activo durante el intercambio prolongado",
        justification=(
            "AbilityCounterRule ya registra que Indestructible niega el patrón de daño sostenido de Darius "
            "(CONTRA genérico), pero no distingue entre 'bloquear' y 'convertir en curación propia'. Ese "
            "matiz —que además resta valor a la mecánica de acumulación de Darius, no solo al daño del turno— "
            "es específico de este par de habilidades y no se deriva de los tags generales."
        ),
        phases=frozenset({Phase.EARLY_LANE, Phase.FIRST_ITEM}),
    ),
)

assert len(SPECIFIC_INTERACTIONS) <= MAX_SPECIFIC_INTERACTIONS
