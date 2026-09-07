"""Cálculo de confianza — hito 1.6.

Separa dos preguntas que el hito 1.5 mezclaba en un solo número:

  - **Confianza epistémica**: cuánto sabe el motor. Sube con cobertura de
    categorías mecánicas distintas (dentro del universo aplicable a ESTE
    matchup, no el registro global de reglas — así incorporar campeones
    nuevos no hace caer la confianza de matchups ya evaluados). Baja con
    información faltante (`invalidated_if` distintos). Una traza vacía
    SIEMPRE da epistemia 0 / BAJA: no hay piso aditivo.
  - **Volatilidad/condicionalidad**: cuánto depende el resultado de
    timing, decisiones o circunstancia. Sube con contradicciones
    PRO/CONTRA dentro de un mismo (fase, factor) — evidencia en ambos
    sentidos no es ignorancia, es un matchup genuinamente condicional —
    y con condiciones `STRATEGIC` distintas. Es independiente de la
    epistemia: un matchup puede estar bien comprendido (epistemia alta)
    y seguir siendo muy condicional (volatilidad alta).

`ConditionKind.EXECUTION` no participa acá en absoluto: alimenta
`required_skill` en PersonalScore (scoring/personal_score.py), nunca
Confidence.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from lol_reasoner.domain.enums import ConditionKind, ConfidenceLevel, Factor, Phase, Polarity
from lol_reasoner.reasoning.rules.registry import ALL_CATEGORIES
from lol_reasoner.reasoning.trace import ReasoningTrace

# Umbral de "magnitud comparable": si el lado menor es al menos esta
# fracción del lado mayor, se considera contradicción real y no ruido.
_CONTRADICTION_RATIO_THRESHOLD = 0.4


@dataclass(frozen=True, slots=True)
class ConfidenceResult:
    level: ConfidenceLevel  # epistémico
    score: float  # epistémico, 0..1, heurístico — no es una probabilidad
    coverage_ratio: float
    categories_hit: frozenset[str]
    applicable_categories_count: int
    missing_info_count: int
    volatility_level: ConfidenceLevel
    volatility_score: float  # 0..1
    contradiction_count: int
    strategic_condition_count: int
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


def _level_from_score(score: float) -> ConfidenceLevel:
    if score >= 0.62:
        return ConfidenceLevel.ALTA
    if score >= 0.35:
        return ConfidenceLevel.MEDIA
    return ConfidenceLevel.BAJA


def compute_confidence(trace: ReasoningTrace, mirror_trace: ReasoningTrace) -> ConfidenceResult:
    """`mirror_trace`: la traza de la MISMA consulta con candidato/enemigo
    invertidos, usada ÚNICAMENTE para determinar qué categorías son
    aplicables a este matchup concreto (denominador de cobertura). No se
    expone ni se mezcla con el resultado del candidato de ninguna otra
    forma."""

    applicable_categories = ALL_CATEGORIES & (trace.categories() | mirror_trace.categories())
    total_categories = len(applicable_categories)
    categories_hit = trace.categories() & applicable_categories
    coverage_ratio = (len(categories_hit) / total_categories) if total_categories else 0.0

    missing_info_count = len({e.invalidated_if for e in trace.entries if e.invalidated_if})

    # --- Epistemia: SOLO cobertura + información faltante. Traza vacía => 0. ---
    epistemic_score = max(0.0, min(1.0, coverage_ratio - 0.35 * min(1.0, missing_info_count / 5)))
    level = _level_from_score(epistemic_score)

    # --- Volatilidad: contradicción + condiciones STRATEGIC. Evidencia
    # PRO y CONTRA no es ignorancia: es justamente lo que hace a un
    # matchup condicional, así que alimenta volatilidad, no epistemia. ---
    contradiction_count = 0
    for pos_sum, neg_sum in _contradictions_per_phase_factor(trace).values():
        if pos_sum <= 0 or neg_sum <= 0:
            continue
        ratio = min(pos_sum, neg_sum) / max(pos_sum, neg_sum)
        if ratio >= _CONTRADICTION_RATIO_THRESHOLD:
            contradiction_count += 1

    strategic_condition_count = len({
        e.condition
        for e in trace.entries
        if e.polarity == Polarity.CONDITIONAL and e.condition and e.condition_kind == ConditionKind.STRATEGIC
    })

    volatility_score = max(
        0.0,
        min(1.0, 0.5 * min(1.0, contradiction_count / 3) + 0.5 * min(1.0, strategic_condition_count / 6)),
    )
    volatility_level = _level_from_score(volatility_score)

    explanation = (
        f"Cobertura de categorías mecánicas aplicables a este matchup: {len(categories_hit)}/{total_categories}.",
        f"Información faltante distinta señalada por el motor: {missing_info_count}.",
        f"Contradicciones entre evidencia PRO y CONTRA en un mismo (fase, factor): {contradiction_count} (alimenta volatilidad, no confianza).",
        f"Condiciones estratégicas distintas de las que depende el resultado: {strategic_condition_count} (alimenta volatilidad).",
    )

    return ConfidenceResult(
        level=level,
        score=round(epistemic_score, 3),
        coverage_ratio=round(coverage_ratio, 3),
        categories_hit=frozenset(categories_hit),
        applicable_categories_count=total_categories,
        missing_info_count=missing_info_count,
        volatility_level=volatility_level,
        volatility_score=round(volatility_score, 3),
        contradiction_count=contradiction_count,
        strategic_condition_count=strategic_condition_count,
        explanation=explanation,
    )
