"""PersonalScore: ajusta el GlobalScore por el dominio (mastery) del usuario.

No es un promedio de mastery y score: el mastery se compara contra una
"exigencia de ejecución requerida" derivada del propio candidato (su eje
`execution_demand` y cuántas condiciones EXECUTION distintas trae su
plan). Un pick sencillo con poco mastery cae poco; un pick de ejecución
alta con mastery 0 cae fuerte en lo personal — pero el GlobalScore, al
no leer `mastery` en ningún punto de este módulo ni del anterior, queda
intacto.

Hito 1.6 — dos correcciones:
  1. `PlayerProfile` reemplaza el parámetro suelto `mastery`: es una
     interfaz mínima pero extensible (aislada de GlobalScore y de las
     reglas mecánicas) para que señales futuras (partidas jugadas,
     winrate personal con muestra, recencia, experiencia en el rol,
     frecuencia de uso) se agreguen como campos nuevos sin tocar la
     firma de `personal_score()` ni ninguna regla. Hoy solo existe
     `mastery`; no se inventan datos para los demás campos.
  2. `execution_condition_count` reemplaza a `conditional_entry_count`:
     ANTES, cualquier entrada CONDITIONAL (información faltante,
     incertidumbre estratégica, lo que fuera) subía `required_skill`.
     AHORA, solo cuentan las condiciones marcadas `ConditionKind.EXECUTION`
     — lo único que de verdad depende de la habilidad del jugador para
     ejecutar algo. Una condición STRATEGIC (p. ej. "depende de que la
     partida se extienda") o un KNOWLEDGE_GAP (p. ej. `ITEMGAP`) no
     hacen que el candidato sea más difícil de EJECUTAR.
"""

from __future__ import annotations

from dataclasses import dataclass

from lol_reasoner.domain.enums import ConditionKind
from lol_reasoner.reasoning.trace import ReasoningTrace
from lol_reasoner.scoring.weights import Weights


@dataclass(frozen=True, slots=True)
class PlayerProfile:
    """Perfil del jugador para PersonalScore. Implementación provisional
    del hito 1.6: hoy solo `mastery` (0..100 o None). El contrato futuro
    (partidas jugadas, winrate personal con tamaño de muestra, desempeño
    reciente, recencia, experiencia en el rol, frecuencia de uso) agrega
    campos acá, no cambia la firma de `personal_score()`."""

    mastery: int | None = None


@dataclass(frozen=True, slots=True)
class PersonalScoreBreakdown:
    """Explica de dónde sale PersonalScore sin inventar TraceEntry falsos."""

    mastery: int | None
    required_skill: float
    execution_condition_count: int
    gap: float
    adjustment: float


def required_skill(execution_demand: int, execution_condition_count: int, weights: Weights) -> float:
    p = weights.personal
    rs = p.base_required_skill + p.execution_demand_weight * execution_demand + p.reliability_penalty_weight * execution_condition_count
    return max(0.0, min(100.0, rs))


def personal_score(
    global_score_value: float,
    *,
    profile: PlayerProfile,
    execution_demand: int,
    execution_condition_count: int,
    weights: Weights,
) -> tuple[float, PersonalScoreBreakdown | None]:
    """Devuelve (personal_score, breakdown). breakdown es None si el
    perfil no trae `mastery` (sin dato de dominio, PersonalScore == GlobalScore)."""

    if profile.mastery is None:
        return global_score_value, None
    rs = required_skill(execution_demand, execution_condition_count, weights)
    gap = profile.mastery - rs
    adjustment = weights.personal.execution_sensitivity * (gap / 100.0)
    adjusted = max(0.0, min(100.0, global_score_value + adjustment))
    breakdown = PersonalScoreBreakdown(
        mastery=profile.mastery,
        required_skill=round(rs, 2),
        execution_condition_count=execution_condition_count,
        gap=round(gap, 2),
        adjustment=round(adjustment, 2),
    )
    return adjusted, breakdown


def execution_condition_count(trace: ReasoningTrace) -> int:
    """Cantidad de condiciones EXECUTION DISTINTAS (no de entradas) de las
    que depende ejecutar el plan del candidato. Ni información faltante
    (KNOWLEDGE_GAP) ni incertidumbre estratégica (STRATEGIC) cuentan acá
    — ver docstring del módulo.

    v1.6.1, dos ajustes: se cuenta sobre la vista causal deduplicada (una
    misma exigencia repetida en cuatro fases es una sola exigencia), y ya
    NO se exige que la entrada sea `CONDITIONAL`. Desde que una ventaja
    puede afirmarse como PRO/CONTRA condicionada (ver domain.enums.Support),
    la exigencia de ejecución suele viajar justamente en esas entradas:
    filtrar por polaridad las descartaba en silencio.
    """

    return len({
        e.condition
        for e in trace.deduped_for_scoring(trace.candidate_id)
        if e.condition and e.condition_kind == ConditionKind.EXECUTION
    })
