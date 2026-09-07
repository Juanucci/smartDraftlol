"""Orquestación: `MatchupQuery` -> `RecommendationSet`.

Es la única capa que conoce a todos los módulos (knowledge, reasoning,
scoring, explain) al mismo tiempo. Todo lo que hace es: construir una
traza por candidato, leerla para puntuar/explicar, y armar el ranking.
No calcula nada por su cuenta que no venga de la traza.

Hito 1.6: además construye una traza espejo (candidato/enemigo
invertidos) SOLO para que `compute_confidence` determine qué categorías
son aplicables a este matchup — no se expone en `Recommendation` ni se
mezcla con el resultado del candidato de ninguna otra forma.
"""

from __future__ import annotations

from lol_reasoner.domain.champion import Champion
from lol_reasoner.domain.enums import ALL_PHASES, Axis
from lol_reasoner.domain.query import MatchupQuery
from lol_reasoner.domain.result import Confidence, PersonalScoreBreakdown, PhaseNote, Recommendation, RecommendationSet
from lol_reasoner.explain.narrator import build_conditions, build_missing_info, build_phase_notes, build_reasons, build_risks
from lol_reasoner.reasoning.engine import RuleEngine
from lol_reasoner.reasoning.trace import ReasoningTrace, TraceEntry
from lol_reasoner.scoring.confidence import compute_confidence
from lol_reasoner.scoring.global_score import global_score
from lol_reasoner.scoring.personal_score import PlayerProfile, execution_condition_count, personal_score
from lol_reasoner.scoring.weights import DEFAULT_WEIGHTS, Weights


def _entry_to_dict(e: TraceEntry) -> dict:
    return {
        "id": e.id,
        "rule_id": e.rule_id,
        "rule_summary": e.rule_summary,
        "category": e.category,
        "phase": e.phase.value,
        "factor": e.factor.value,
        "polarity": e.polarity.value,
        "delta": e.delta,
        "premises": [{"path": p.path, "value": p.value} for p in e.premises],
        "subject": e.subject,
        "text": e.text,
        "condition": e.condition,
        "invalidated_if": e.invalidated_if,
        "causal_key": e.causal_key,
        "condition_kind": e.condition_kind.value if e.condition_kind else None,
    }


def evaluate_candidate(
    candidate: Champion,
    enemy: Champion,
    phases: tuple,
    mastery: int | None,
    weights: Weights,
    engine: RuleEngine,
) -> tuple[Recommendation, ReasoningTrace]:
    trace = engine.build_trace(candidate, enemy, phases)
    # Traza espejo: SOLO para el denominador de cobertura de Confidence.
    mirror_trace = engine.build_trace(enemy, candidate, phases)

    score, breakdown = global_score(trace, weights, subject_id=candidate.id)
    exec_cond_count = execution_condition_count(trace)
    profile = PlayerProfile(mastery=mastery)
    p_score, p_breakdown = personal_score(
        score,
        profile=profile,
        execution_demand=candidate.axis(Axis.EXECUTION_DEMAND),
        execution_condition_count=exec_cond_count,
        weights=weights,
    )
    confidence_result = compute_confidence(trace, mirror_trace)

    confidence = Confidence(
        level=confidence_result.level.value,
        score=confidence_result.score,
        coverage_ratio=confidence_result.coverage_ratio,
        missing_info_count=confidence_result.missing_info_count,
        volatility_level=confidence_result.volatility_level.value,
        volatility_score=confidence_result.volatility_score,
        contradiction_count=confidence_result.contradiction_count,
        strategic_condition_count=confidence_result.strategic_condition_count,
        explanation=confidence_result.explanation,
    )

    personal_breakdown = (
        PersonalScoreBreakdown(
            mastery=p_breakdown.mastery,
            required_skill=p_breakdown.required_skill,
            execution_condition_count=p_breakdown.execution_condition_count,
            gap=p_breakdown.gap,
            adjustment=p_breakdown.adjustment,
        )
        if p_breakdown is not None
        else None
    )

    recommendation = Recommendation(
        candidate_id=candidate.id,
        candidate_name=candidate.name,
        global_score=round(score, 2),
        personal_score=round(p_score, 2),
        mastery=mastery,
        personal_breakdown=personal_breakdown,
        factor_breakdown={f.value: round(v, 4) for f, v in breakdown.items()},
        confidence=confidence,
        reasons=build_reasons(trace, subject_id=candidate.id),
        risks=build_risks(trace, subject_id=candidate.id),
        conditions=build_conditions(trace),
        missing_info=build_missing_info(trace),
        phase_notes=build_phase_notes(trace),
        trace_entries=tuple(_entry_to_dict(e) for e in trace.entries),
    )
    return recommendation, trace


def recommend(
    query: MatchupQuery,
    champions: dict[str, Champion],
    weights: Weights = DEFAULT_WEIGHTS,
) -> RecommendationSet:
    if query.enemy_id not in champions:
        raise KeyError(f"Campeón enemigo desconocido: '{query.enemy_id}'. Cargados: {sorted(champions)}")
    enemy = champions[query.enemy_id]

    if query.candidate_ids is not None:
        candidate_ids = query.candidate_ids
        unknown = [c for c in candidate_ids if c not in champions]
        if unknown:
            raise KeyError(f"Candidatos desconocidos: {unknown}. Cargados: {sorted(champions)}")
    else:
        candidate_ids = tuple(cid for cid in champions if cid != enemy.id)

    phases = query.phases if query.phases is not None else ALL_PHASES

    engine = RuleEngine()
    recommendations: dict[str, Recommendation] = {}
    for cid in candidate_ids:
        if cid == enemy.id:
            continue
        candidate = champions[cid]
        rec, _trace = evaluate_candidate(candidate, enemy, phases, query.mastery.get(cid), weights, engine)
        recommendations[cid] = rec

    if not recommendations:
        raise ValueError("No hay candidatos para evaluar (candidate_ids vacío o solo contenía al enemigo).")

    ranking_global = tuple(sorted(recommendations, key=lambda c: recommendations[c].global_score, reverse=True))
    ranking_personal = tuple(sorted(recommendations, key=lambda c: recommendations[c].personal_score, reverse=True))

    return RecommendationSet(
        enemy_id=enemy.id,
        enemy_name=enemy.name,
        candidate_ids=tuple(recommendations.keys()),
        knowledge_version=enemy.knowledge_version,
        ranking_global=ranking_global,
        ranking_personal=ranking_personal,
        best_global=ranking_global[0],
        best_personal=ranking_personal[0],
        recommendations=recommendations,
    )
