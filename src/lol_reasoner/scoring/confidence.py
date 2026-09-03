"""Cálculo de confianza.

Principio explícito del brief: varias reglas redundantes no son
evidencia independiente. Por eso la cobertura se mide en **categorías
mecánicas distintas** que dispararon (`TraceEntry.category`), no en
cantidad de entradas. Dos reglas de la misma categoría (p. ej. dos
`ability_interaction`) no suman cobertura extra.

Los otros tres insumos son: contradicción entre factores (evidencia PRO
y CONTRA de magnitud comparable en el mismo factor: eso es justamente
un matchup condicional, no una casualidad a promediar), cantidad de
información faltante señalada (`invalidated_if`), y cantidad de
entradas condicionales (dependen de una circunstancia que puede no
darse). Fórmula heurística, documentada en docs/decisiones-tecnicas.md.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from lol_reasoner.domain.enums import ConfidenceLevel, Factor, Polarity
from lol_reasoner.reasoning.rules.general import GENERAL_CATEGORIES
from lol_reasoner.reasoning.trace import ReasoningTrace

# Umbral de "magnitud comparable": si el lado menor es al menos esta
# fracción del lado mayor, se considera contradicción real y no ruido.
_CONTRADICTION_RATIO_THRESHOLD = 0.4

TOTAL_KNOWN_CATEGORIES = len(GENERAL_CATEGORIES)


@dataclass(frozen=True, slots=True)
class ConfidenceResult:
    level: ConfidenceLevel
    score: float
    coverage_ratio: float
    categories_hit: frozenset[str]
    contradiction_count: int
    missing_info_count: int
    conditional_count: int
    explanation: tuple[str, ...]


def _contradictions_per_factor(trace: ReasoningTrace) -> dict[Factor, tuple[float, float]]:
    """Para cada factor, (suma de deltas PRO, suma de deltas CONTRA) sin ponderar por fase/peso."""

    pos: dict[Factor, float] = defaultdict(float)
    neg: dict[Factor, float] = defaultdict(float)
    for e in trace.entries:
        if e.polarity == Polarity.PRO:
            pos[e.factor] += e.delta
        elif e.polarity == Polarity.CONTRA:
            neg[e.factor] += e.delta
    factors = set(pos) | set(neg)
    return {f: (pos.get(f, 0.0), neg.get(f, 0.0)) for f in factors}


def compute_confidence(trace: ReasoningTrace, *, total_categories: int = TOTAL_KNOWN_CATEGORIES) -> ConfidenceResult:
    categories_hit = trace.categories()
    coverage_ratio = min(1.0, len(categories_hit) / total_categories) if total_categories else 0.0

    contradiction_count = 0
    for pos_sum, neg_sum in _contradictions_per_factor(trace).values():
        if pos_sum <= 0 or neg_sum <= 0:
            continue
        ratio = min(pos_sum, neg_sum) / max(pos_sum, neg_sum)
        if ratio >= _CONTRADICTION_RATIO_THRESHOLD:
            contradiction_count += 1

    missing_info_count = sum(1 for e in trace.entries if e.invalidated_if)
    conditional_count = sum(1 for e in trace.entries if e.polarity == Polarity.CONDITIONAL)

    score = (
        0.55 * coverage_ratio
        - 0.20 * min(1.0, contradiction_count / 3)
        - 0.15 * min(1.0, missing_info_count / 5)
        - 0.15 * min(1.0, conditional_count / 6)
    )
    score = max(0.0, min(1.0, score + 0.45))  # piso: cobertura 0 y sin penalidades no debe dar exactamente 0

    if score >= 0.62:
        level = ConfidenceLevel.ALTA
    elif score >= 0.40:
        level = ConfidenceLevel.MEDIA
    else:
        level = ConfidenceLevel.BAJA

    explanation = (
        f"Cobertura de categorías mecánicas distintas: {len(categories_hit)}/{total_categories}.",
        f"Contradicciones entre evidencia PRO y CONTRA en un mismo factor: {contradiction_count}.",
        f"Información faltante señalada por el motor: {missing_info_count} entrada(s).",
        f"Entradas condicionales (dependen de una circunstancia particular): {conditional_count}.",
    )

    return ConfidenceResult(
        level=level,
        score=round(score, 3),
        coverage_ratio=round(coverage_ratio, 3),
        categories_hit=frozenset(categories_hit),
        contradiction_count=contradiction_count,
        missing_info_count=missing_info_count,
        conditional_count=conditional_count,
        explanation=explanation,
    )
