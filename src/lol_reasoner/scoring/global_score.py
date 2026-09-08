"""GlobalScore: adecuación mecánica del candidato, sin dominio del usuario.

Convención de signo sobre la traza (documentada, no implícita):
  PRO         -> +1 * delta
  CONTRA      -> -1 * delta
  CONDITIONAL -> 0   (no mueve el score; solo aparece como condición/riesgo
                       textual y como señal para la volatilidad).

Sobre ese signo, v1.6.1 aplica dos multiplicadores configurables
(`config/weights.yaml`), ambos visibles entrada por entrada en la traza:

  * `support` (domain.enums.Support): cuánta certeza respalda la
    inclinación. Una ventaja CONDITIONED inclina amortiguada — puede
    mover el score sin volverse certeza —; una AMBIGUOUS aporta cero.
  * `provenance` (domain.enums.Provenance): si el hecho se derivó del kit
    o si es un prior editorial escrito a mano en un eje 0..4. El prior
    entra con peso reducido y etiquetado, nunca como conclusión derivada.

Contribución de una entrada:

    signo * delta * phase_w * factor_w * support_w * provenance_w
"""

from __future__ import annotations

from collections import defaultdict

from lol_reasoner.domain.enums import Factor, Polarity
from lol_reasoner.reasoning.trace import ReasoningTrace, TraceEntry
from lol_reasoner.scoring.weights import Weights

_SIGN = {Polarity.PRO: 1.0, Polarity.CONTRA: -1.0, Polarity.CONDITIONAL: 0.0}


def effective_delta(entry: TraceEntry, weights: Weights) -> float:
    """Delta ya amortiguado por certeza y procedencia, SIN signo ni pesos
    de fase/factor. Es la magnitud "de verdad afirmada" por una entrada:
    lo que el narrador debe usar para ordenar razones y riesgos, en vez
    del delta crudo (que no distingue una certeza estructural de una
    ventaja condicionada ni de un prior editorial)."""

    return entry.delta * weights.support_weights[entry.support] * weights.provenance_weights[entry.provenance]


def signed_contribution(entry: TraceEntry, weights: Weights) -> float:
    """Aporte con signo y ya ponderado por fase y factor: exactamente lo
    que esta entrada suma al GlobalScore."""

    sign = _SIGN[entry.polarity]
    if sign == 0.0:
        return 0.0
    w = weights.phase_weights[entry.phase] * weights.factor_weights[entry.factor]
    return sign * effective_delta(entry, weights) * w


def factor_breakdown(trace: ReasoningTrace, weights: Weights, *, subject_id: str) -> dict[Factor, float]:
    """Contribución ponderada (fase * factor * certeza * procedencia) de
    cada factor, sobre la VISTA CAUSAL (`trace.deduped_for_scoring`), no
    sobre la traza cruda: cuando dos entradas comparten `causal_key`
    (misma fuente mecánica citada por dos reglas, o el mismo hecho
    repetido en cuatro fases) cuentan una sola vez. La traza cruda se
    conserva íntegra para auditoría."""

    breakdown: dict[Factor, float] = defaultdict(float)
    for entry in trace.deduped_for_scoring(subject_id):
        contribution = signed_contribution(entry, weights)
        if contribution:
            breakdown[entry.factor] += contribution
    return dict(breakdown)


def global_score(trace: ReasoningTrace, weights: Weights, *, subject_id: str) -> tuple[float, dict[Factor, float]]:
    breakdown = factor_breakdown(trace, weights, subject_id=subject_id)
    total = sum(breakdown.values())
    score = 50.0 + weights.global_scale * total
    return max(0.0, min(100.0, score)), breakdown
