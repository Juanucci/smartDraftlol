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


def factor_breakdown(trace: ReasoningTrace, weights: Weights) -> dict[Factor, float]:
    """Contribución ponderada (fase * factor) de cada factor, sumada sobre toda la traza."""

    breakdown: dict[Factor, float] = defaultdict(float)
    for entry in trace.entries:
        sign = _SIGN[entry.polarity]
        if sign == 0.0:
            continue
        w = weights.phase_weights[entry.phase] * weights.factor_weights[entry.factor]
        breakdown[entry.factor] += sign * entry.delta * w
    return dict(breakdown)


def global_score(trace: ReasoningTrace, weights: Weights) -> tuple[float, dict[Factor, float]]:
    breakdown = factor_breakdown(trace, weights)
    total = sum(breakdown.values())
    score = 50.0 + weights.global_scale * total
    return max(0.0, min(100.0, score)), breakdown
