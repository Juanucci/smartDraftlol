"""Contexto que se le pasa a cada regla al evaluarla."""

from __future__ import annotations

from dataclasses import dataclass

from lol_reasoner.domain.champion import Champion
from lol_reasoner.domain.enums import Phase


@dataclass(frozen=True, slots=True)
class ReasoningContext:
    """Todo lo que una regla puede leer para un candidato en una fase.

    `candidate` es el campeón que se está evaluando como pick (el
    "sujeto" del análisis); `enemy` es el rival fijo de la consulta.
    Evaluar (Darius→Mordekaiser) y (Mordekaiser→Darius) son dos
    contextos distintos con candidate/enemy invertidos: por eso las
    reglas nunca deben asumir simetría.
    """

    candidate: Champion
    enemy: Champion
    phase: Phase
