"""Cálculo de confianza.

Principio explícito del brief: varias reglas redundantes no son
evidencia independiente. Por eso la cobertura se mide en **categorías
mecánicas distintas** que dispararon (`TraceEntry.category`), no en
cantidad de entradas — y solo cuenta categorías que pertenecen al
universo reconocido (`registry.ALL_CATEGORIES`): categorías fuera de ese
universo (como `missing_item_data`, un aviso de alcance, no una
categoría de razonamiento mecánico) no inflan el numerador ni forman
parte del denominador.

Los otros tres insumos, corregidos en el hito 1.5:
  - **Información faltante deduplicada**: la misma observación
    (`invalidated_if`) repetida en varias fases cuenta una sola vez, no
    una por fase.
  - **Contradicción por (fase, factor)**, no agregada sobre toda la
    traza: una ventaja de early y una desventaja de late en el mismo
    factor no deben cancelarse como si fueran simultáneas.
  - **Densidad de condiciones distintas**: se cuentan condiciones
    (`condition`) distintas, no entradas — la misma condición repetida
    en varias fases no debe penalizar varias veces.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from lol_reasoner.domain.enums import ConfidenceLevel, Factor, Phase, Polarity
from lol_reasoner.reasoning.rules.registry import ALL_CATEGORIES
from lol_reasoner.reasoning.trace import ReasoningTrace

# Umbral de "magnitud comparable": si el lado menor es al menos esta
# fracción del lado mayor, se considera contradicción real y no ruido.
_CONTRADICTION_RATIO_THRESHOLD = 0.4

TOTAL_KNOWN_CATEGORIES = len(ALL_CATEGORIES)


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


def _contradictions_per_phase_factor(trace: ReasoningTrace) -> dict[tuple[Phase, Factor], tuple[float, float]]:
    """Para cada (fase, factor), (suma de deltas PRO, suma de deltas CONTRA)
    sin ponderar por peso — agrupado por fase para no mezclar una ventaja
    de early con una desventaja de late como si fueran simultáneas."""

    pos: dict[tuple[Phase, Factor], float] = defaultdict(float)
    neg: dict[tuple[Phase, Factor], float] = defaultdict(float)
    for e in trace.entries:
        key = (e.phase, e.factor)
        if e.polarity == Polarity.PRO:
            pos[key] += e.delta
        elif e.polarity == Polarity.CONTRA:
            neg[key] += e.delta
    keys = set(pos) | set(neg)
    return {k: (pos.get(k, 0.0), neg.get(k, 0.0)) for k in keys}


def compute_confidence(trace: ReasoningTrace, *, total_categories: int = TOTAL_KNOWN_CATEGORIES) -> ConfidenceResult:
    categories_hit = trace.categories() & ALL_CATEGORIES
    coverage_ratio = min(1.0, len(categories_hit) / total_categories) if total_categories else 0.0

    contradiction_count = 0
    for pos_sum, neg_sum in _contradictions_per_phase_factor(trace).values():
        if pos_sum <= 0 or neg_sum <= 0:
            continue
        ratio = min(pos_sum, neg_sum) / max(pos_sum, neg_sum)
        if ratio >= _CONTRADICTION_RATIO_THRESHOLD:
            contradiction_count += 1

    missing_info_count = len({e.invalidated_if for e in trace.entries if e.invalidated_if})
    conditional_count = len({e.condition for e in trace.entries if e.polarity == Polarity.CONDITIONAL and e.condition})

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
        f"Contradicciones entre evidencia PRO y CONTRA en un mismo (fase, factor): {contradiction_count}.",
        f"Información faltante distinta señalada por el motor: {missing_info_count}.",
        f"Condiciones distintas de las que depende la conclusión: {conditional_count}.",
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
