"""GlobalScore: adecuación mecánica del candidato, sin dominio del usuario.

Convención de signo sobre la traza (documentada, no implícita):
  PRO         -> +1 * delta
  CONTRA      -> -1 * delta
  CONDITIONAL -> 0   (no mueve el score; solo aparece como condición/riesgo
                       textual y como señal para la confianza). Un efecto
                       "puede ser cierto según circunstancia" no debe
                       inflar ni desinflar el número si esa circunstancia
                       no está confirmada.
"""

from __future__ import annotations

from collections import defaultdict

from lol_reasoner.domain.enums import Factor, Polarity
from lol_reasoner.reasoning.trace import ReasoningTrace
from lol_reasoner.scoring.weights import Weights

_SIGN = {Polarity.PRO: 1.0, Polarity.CONTRA: -1.0, Polarity.CONDITIONAL: 0.0}


def factor_breakdown(trace: ReasoningTrace, weights: Weights, *, subject_id: str) -> dict[Factor, float]:
    """Contribución ponderada (fase * factor) de cada factor.

    Usa `trace.deduped_for_scoring(subject_id)`, no `trace.entries`
    crudo: cuando dos entradas (de la misma o de distinta regla, en la
    misma o distinta fase) comparten `causal_key`, cuentan una sola vez
    (ver ReasoningTrace.deduped_for_scoring) — evita que una única
    capacidad mecánica (p. ej. un escudo citado por dos reglas, o un
    mismo hecho repetido idéntico en cuatro fases) infle el score varias
    veces por la misma causa.
    """

    breakdown: dict[Factor, float] = defaultdict(float)
    for entry in trace.deduped_for_scoring(subject_id):
        sign = _SIGN[entry.polarity]
        if sign == 0.0:
            continue
        w = weights.phase_weights[entry.phase] * weights.factor_weights[entry.factor]
        breakdown[entry.factor] += sign * entry.delta * w
    return dict(breakdown)


def global_score(trace: ReasoningTrace, weights: Weights, *, subject_id: str) -> tuple[float, dict[Factor, float]]:
    breakdown = factor_breakdown(trace, weights, subject_id=subject_id)
    total = sum(breakdown.values())
    score = 50.0 + weights.global_scale * total
    return max(0.0, min(100.0, score)), breakdown
