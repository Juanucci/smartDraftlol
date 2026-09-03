"""PersonalScore: ajusta el GlobalScore por el dominio (mastery) del usuario.

No es un promedio de mastery y score: el mastery se compara contra una
"exigencia de ejecución requerida" derivada del propio candidato (su eje
`execution_demand` y cuántas condiciones/reliability issues trae su
plan). Un pick sencillo con poco mastery cae poco; un pick de ejecución
alta con mastery 0 cae fuerte en lo personal — pero el GlobalScore, al
no leer `mastery` en ningún punto de este módulo ni del anterior, queda
intacto.
"""

from __future__ import annotations

from lol_reasoner.domain.enums import Polarity
from lol_reasoner.reasoning.trace import ReasoningTrace
from lol_reasoner.scoring.weights import Weights


def required_skill(execution_demand: int, conditional_count: int, weights: Weights) -> float:
    p = weights.personal
    rs = p.base_required_skill + p.execution_demand_weight * execution_demand + p.reliability_penalty_weight * conditional_count
    return max(0.0, min(100.0, rs))


def personal_score(
    global_score_value: float,
    *,
    mastery: int | None,
    execution_demand: int,
    conditional_count: int,
    weights: Weights,
) -> tuple[float, float | None]:
    """Devuelve (personal_score, required_skill_usado). required_skill es None si no hay mastery."""

    if mastery is None:
        return global_score_value, None
    rs = required_skill(execution_demand, conditional_count, weights)
    gap = mastery - rs
    adjusted = global_score_value + weights.personal.execution_sensitivity * (gap / 100.0)
    return max(0.0, min(100.0, adjusted)), rs


def conditional_entry_count(trace: ReasoningTrace) -> int:
    """Cantidad de CONDICIONES DISTINTAS (no de entradas) de las que
    depende el plan del candidato. Varias entradas CONDITIONAL que
    repiten la misma condición en distintas fases (p. ej. un hecho
    estructural del kit que no cambia fase a fase) no deben penalizar
    `required_skill` una vez por fase — la generación de varias copias
    de la misma condición es un detalle de implementación de la traza,
    no una condición nueva."""

    return len({e.condition for e in trace.entries if e.polarity == Polarity.CONDITIONAL and e.condition})
