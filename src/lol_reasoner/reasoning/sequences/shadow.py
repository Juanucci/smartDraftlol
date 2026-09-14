"""Punto mínimo de orquestación para evaluar la primera secuencia real en
shadow mode (v1.7).

Nunca toca `RuleEngine`, `scoring/*`, reglas atómicas, ni ningún resultado
público: construye un `ScenarioOutcome` puramente interno y, si se le pasa
una `ReasoningTrace`, lo adjunta a `trace.shadow_sequence_outcomes` —
NUNCA a `trace.entries`. Quien quiera comparar "shadow OFF" vs "shadow ON"
simplemente decide si llama o no a `evaluate_apprehend_followup_shadow`
después de construir la traza con el motor real, sin cambiar una sola
línea de cómo se construye esa traza.
"""

from __future__ import annotations

from lol_reasoner.domain.champion import Champion
from lol_reasoner.reasoning.scenario_builder import build_apprehend_followup_baseline
from lol_reasoner.reasoning.sequences.evaluator import evaluate_sequence_prefix
from lol_reasoner.reasoning.sequences.registry import (
    DARIUS_ID,
    ApprehendFollowupRegistration,
    build_apprehend_followup_registration,
    is_darius_mordekaiser_matchup,
)
from lol_reasoner.reasoning.sequences.sequence import (
    AlternativeGroup,
    Evaluation,
    ScenarioOutcome,
    StateDelta,
    TradeOutcome,
)
from lol_reasoner.reasoning.sequences.steps import ActorRole
from lol_reasoner.reasoning.trace import ReasoningTrace, ShadowSequenceRecord

_PERFORMER_LEVEL = 3  # nivel mínimo declarado: E y Q ya disponibles (available_from=EARLY_LANE)


def _resolve_darius_role(candidate: Champion, enemy: Champion) -> ActorRole:
    return ActorRole.CANDIDATE if candidate.id == DARIUS_ID else ActorRole.ENEMY


def build_apprehend_followup_outcome(
    registration: ApprehendFollowupRegistration, *, selected_alternative_id: str
) -> ScenarioOutcome:
    """Evalúa la alternativa `selected_alternative_id` de `registration`
    contra su propio escenario baseline (construido acá, solo con lo que
    esta secuencia necesita) y devuelve el `ScenarioOutcome` resultante.

    Nunca evalúa "la primera alternativa por defecto": el caller decide
    explícitamente cuál. `causal_components` queda siempre vacío — shadow
    mode no reclama ninguna causa puntuable (§B7)."""

    selected = registration.spec_for(selected_alternative_id)

    baseline = build_apprehend_followup_baseline(
        performer_role=registration.darius_role,
        performer_level=_PERFORMER_LEVEL,
        control_action_ref=registration.apprehend_action_ref,
        control_ability_slot=registration.apprehend_slot,
        followup_action_refs=(registration.basic_attack_action_ref, registration.decimate_action_ref),
        followup_ability_slots=(None, registration.decimate_slot),
        stack_reference=registration.stack_reference,
    )

    step_results, final_state = evaluate_sequence_prefix(selected.step_specs, baseline)

    group = selected.sequence.alternative_group
    assert group is not None  # toda alternativa de esta familia pertenece a un grupo
    branch_selection = AlternativeGroup(
        group_id=group.group_id, alternative_ids=group.alternative_ids, selected_id=selected_alternative_id
    )

    trade_outcome = TradeOutcome(
        state_delta=StateDelta(before=baseline, after=final_state),
        # El acierto del follow-up no está garantizado en este baseline
        # (range_status queda UNKNOWN a propósito, §B6) — nunca se fuerza
        # un ganador sin esa evidencia: CONDITIONAL es la lectura honesta.
        evaluation=Evaluation.CONDITIONAL,
    )

    return ScenarioOutcome(
        sequence=selected.sequence,
        step_results=step_results,
        trade_outcome=trade_outcome,
        branch_selection=branch_selection,
        causal_components=(),  # shadow mode: nunca componentes puntuables
    )


def evaluate_apprehend_followup_shadow(
    *,
    candidate: Champion,
    enemy: Champion,
    selected_alternative_id: str = "q",
    trace: ReasoningTrace | None = None,
) -> ScenarioOutcome | None:
    """Evalúa en shadow mode la secuencia Apprehend->follow-up para el
    matchup Darius-Mordekaiser, en la orientación que corresponda según
    quién sea `candidate`/`enemy`. Devuelve `None` (no construye nada)
    para cualquier otro matchup.

    Si se pasa `trace`, adjunta el resultado a
    `trace.shadow_sequence_outcomes` — nunca a `trace.entries` ni a
    ningún otro campo que scoring/narrador lean."""

    if not is_darius_mordekaiser_matchup(candidate, enemy):
        return None

    darius = candidate if candidate.id == DARIUS_ID else enemy
    darius_role = _resolve_darius_role(candidate, enemy)

    registration = build_apprehend_followup_registration(darius=darius, darius_role=darius_role)
    outcome = build_apprehend_followup_outcome(registration, selected_alternative_id=selected_alternative_id)

    if trace is not None:
        record = ShadowSequenceRecord(
            matchup_id=f"{DARIUS_ID}_vs_mordekaiser",
            sequence_id=outcome.sequence.sequence_id,
            outcome=outcome,
        )
        trace.add_shadow_sequence_outcome(record)

    return outcome
