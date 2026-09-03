"""Contexto que se le pasa a cada regla al evaluarla."""

from __future__ import annotations

from dataclasses import dataclass

from lol_reasoner.domain.champion import Ability, Champion
from lol_reasoner.domain.enums import Phase, is_available_in


def _abilities_available_in(champion: Champion, phase: Phase) -> tuple[Ability, ...]:
    return tuple(a for a in champion.abilities if is_available_in(a.available_from, phase))


@dataclass(frozen=True, slots=True)
class ReasoningContext:
    """Todo lo que una regla puede leer para un candidato en una fase.

    `candidate` es el campeón que se está evaluando como pick (el
    "sujeto" del análisis); `enemy` es el rival fijo de la consulta.
    Evaluar (Darius→Mordekaiser) y (Mordekaiser→Darius) son dos
    contextos distintos con candidate/enemy invertidos: por eso las
    reglas nunca deben asumir simetría.

    Las reglas NUNCA deben leer `champion.abilities` directamente
    (verificado por tests/test_phase_availability.py con un escaneo de
    AST): deben pasar por `candidate_abilities()` / `enemy_abilities()`,
    que ya filtran por `available_from <= phase`. Así `available_from`
    se cumple estructuralmente y no depende de que cada regla se acuerde
    de chequearlo.
    """

    candidate: Champion
    enemy: Champion
    phase: Phase

    def candidate_abilities(self) -> tuple[Ability, ...]:
        return _abilities_available_in(self.candidate, self.phase)

    def enemy_abilities(self) -> tuple[Ability, ...]:
        return _abilities_available_in(self.enemy, self.phase)
