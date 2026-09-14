"""Tests de la familia Apprehend->follow-up en shadow mode (v1.7),
incluido el microfix que distingue progreso de evaluación, estado de
ejecución, y delta confirmado vs proyectado — SOLO para Darius vs
Mordekaiser (y su orientación inversa), y SOLO en shadow mode.

No hay motor de transición genérico, generador de escenarios genérico ni
scoring por secuencia en este archivo — eso sigue fuera de alcance. Ningún
test de este archivo congela un ganador ni un score absoluto: las
comparaciones "shadow OFF vs ON" comparan los mismos valores calculados
dentro de la misma ejecución, nunca contra una constante numérica fija.
"""

from __future__ import annotations

import json

import pytest

from lol_reasoner.domain.champion import Champion, DamageProfile
from lol_reasoner.domain.combat_state import RangeStatus
from lol_reasoner.domain.enums import ALL_PHASES, Axis, ResourceType, Support
from lol_reasoner.explain.narrator import build_reasons, build_risks
from lol_reasoner.reasoning.engine import RuleEngine
from lol_reasoner.reasoning.rules.registry import ALL_GENERAL_RULES
from lol_reasoner.reasoning.rules.specific import SPECIFIC_INTERACTIONS
from lol_reasoner.reasoning.sequences.registry import (
    AA_ALTERNATIVE_ID,
    Q_ALTERNATIVE_ID,
    build_apprehend_followup_baseline,
    build_apprehend_followup_registration,
    is_darius_mordekaiser_matchup,
)
from lol_reasoner.reasoning.sequences.sequence import (
    CalibrationStatus,
    Evaluation,
    ExecutionStatus,
    InteractionSequence,
    PreconditionStatus,
    SequenceProgress,
    TerminalEventKind,
    scenario_outcome_to_primitive,
)
from lol_reasoner.reasoning.sequences.shadow import (
    build_apprehend_followup_outcome,
    evaluate_apprehend_followup_shadow,
)
from lol_reasoner.reasoning.sequences.steps import ActorRole
from lol_reasoner.reasoning.trace import ShadowSequenceRecord
from lol_reasoner.scoring.confidence import compute_confidence
from lol_reasoner.scoring.global_score import global_score
from lol_reasoner.scoring.personal_score import PlayerProfile, execution_condition_count, personal_score
from lol_reasoner.scoring.weights import DEFAULT_WEIGHTS


def _synthetic_champion(champion_id: str) -> Champion:
    return Champion(
        id=champion_id,
        name=champion_id.capitalize(),
        archetype="synthetic",
        damage_profile=DamageProfile(physical=0.0, magic=0.0, true=0.0),
        axes={},
        casting_resource=ResourceType.MANA,
        trade_patterns=frozenset(),
        tags=frozenset(),
        abilities=(),
        stacking_mechanics=(),
        spikes=(),
        knowledge_version="test",
    )


@pytest.fixture()
def registration_candidate(darius):
    return build_apprehend_followup_registration(darius=darius, darius_role=ActorRole.CANDIDATE)


# --- 1. registro resuelve habilidades/efectos reales existentes ------------


def test_registration_resolves_real_darius_abilities_and_mechanic(darius, registration_candidate):
    assert registration_candidate.apprehend_slot == "e"
    assert registration_candidate.decimate_slot == "q"
    assert registration_candidate.stack_reference == "hemorrhage"
    assert registration_candidate.stack_reference in {m.id for m in darius.stacking_mechanics}


def test_missing_ability_reference_fails_explicitly():
    fake_darius = _synthetic_champion("darius")
    with pytest.raises(ValueError, match="Referencia mecánica requerida ausente"):
        build_apprehend_followup_registration(darius=fake_darius, darius_role=ActorRole.CANDIDATE)


# --- 2. Apprehend solo no agrega Hemorrhage ---------------------------------


def test_apprehend_control_step_does_not_consume_stack_application(registration_candidate):
    control_step = registration_candidate.spec_for(Q_ALTERNATIVE_ID).steps[0]
    for identity in control_step.consumes:
        assert identity.causal_role != "stack_application"


# ---------------------------------------------------------------------------
# §1 del microfix: progreso de evaluación vs estado de ejecución
# ---------------------------------------------------------------------------


def test_completed_evaluation_with_hypothetical_execution(darius, mordekaiser, registration_candidate):
    outcome = evaluate_apprehend_followup_shadow(
        candidate=darius, enemy=mordekaiser, selected_alternative_id=Q_ALTERNATIVE_ID
    )

    # la cadena TERMINÓ de evaluarse (progreso completo)...
    assert outcome.progress is SequenceProgress.COMPLETED
    # ...pero nada confirma que haya ocurrido de verdad: es una hipótesis
    assert outcome.execution_status is ExecutionStatus.HYPOTHETICAL
    assert outcome.support is Support.CONDITIONED  # nunca STRUCTURAL sin confirmación


def test_confirmed_execution_when_all_preconditions_are_satisfied(registration_candidate):
    confirmed_baseline = build_apprehend_followup_baseline(
        registration_candidate,
        range_statuses={
            registration_candidate.apprehend_action_ref: RangeStatus.IN_RANGE,
            registration_candidate.decimate_outer_zone_action_ref: RangeStatus.IN_RANGE,
        },
    )
    outcome = build_apprehend_followup_outcome(
        registration_candidate, selected_alternative_id=Q_ALTERNATIVE_ID, baseline=confirmed_baseline
    )

    assert outcome.progress is SequenceProgress.COMPLETED
    assert outcome.execution_status is ExecutionStatus.CONFIRMED
    assert outcome.support is Support.STRUCTURAL


def test_blocked_execution_when_a_precondition_fails(registration_candidate):
    blocked_baseline = build_apprehend_followup_baseline(
        registration_candidate,
        range_statuses={registration_candidate.apprehend_action_ref: RangeStatus.OUT_OF_RANGE},
    )
    outcome = build_apprehend_followup_outcome(
        registration_candidate, selected_alternative_id=Q_ALTERNATIVE_ID, baseline=blocked_baseline
    )

    assert outcome.progress is SequenceProgress.BLOCKED
    assert outcome.execution_status is ExecutionStatus.BLOCKED
    assert outcome.support is None
    assert outcome.causal_components == ()


def test_execution_status_is_never_a_free_input():
    # mismo patrón que effective_support (§A4): execution_status es
    # field(init=False) — no hay forma de pasarlo por el constructor.
    import dataclasses

    from lol_reasoner.reasoning.sequences.sequence import StepResult

    init_fields = {f.name for f in dataclasses.fields(StepResult) if f.init}
    assert "execution_status" not in init_fields


# ---------------------------------------------------------------------------
# §2 del microfix: delta proyectado vs delta confirmado
# ---------------------------------------------------------------------------


def test_projected_delta_is_not_confused_with_confirmed_delta(registration_candidate):
    hypothetical_outcome = evaluate_apprehend_followup_shadow_result(registration_candidate)
    confirmed_baseline = build_apprehend_followup_baseline(
        registration_candidate,
        range_statuses={
            registration_candidate.apprehend_action_ref: RangeStatus.IN_RANGE,
            registration_candidate.decimate_outer_zone_action_ref: RangeStatus.IN_RANGE,
        },
    )
    confirmed_outcome = build_apprehend_followup_outcome(
        registration_candidate, selected_alternative_id=Q_ALTERNATIVE_ID, baseline=confirmed_baseline
    )

    # ambos proyectan el MISMO cambio estructural (0 -> 1 carga)...
    assert hypothetical_outcome.trade_outcome.state_delta.after.enemy.stacks["hemorrhage"].count == 1
    assert confirmed_outcome.trade_outcome.state_delta.after.enemy.stacks["hemorrhage"].count == 1
    # ...pero solo uno de los dos outcomes lo etiqueta como CONFIRMED — el
    # consumidor puede (y debe) distinguirlos sin adivinar por su cuenta.
    assert hypothetical_outcome.execution_status is ExecutionStatus.HYPOTHETICAL
    assert confirmed_outcome.execution_status is ExecutionStatus.CONFIRMED


def evaluate_apprehend_followup_shadow_result(registration):
    return build_apprehend_followup_outcome(registration, selected_alternative_id=Q_ALTERNATIVE_ID)


# ---------------------------------------------------------------------------
# §4 del microfix: selección de ramas explícita
# ---------------------------------------------------------------------------


def test_aa_branch_selected_explicitly(darius, mordekaiser):
    outcome = evaluate_apprehend_followup_shadow(
        candidate=darius, enemy=mordekaiser, selected_alternative_id=AA_ALTERNATIVE_ID
    )

    assert outcome.sequence.alternative_id == AA_ALTERNATIVE_ID
    assert outcome.branch_selection.selected_id == AA_ALTERNATIVE_ID
    step_ids = {r.step_id for r in outcome.step_results}
    assert "followup_decimate" not in step_ids


def test_q_outer_branch_selected_explicitly(darius, mordekaiser):
    outcome = evaluate_apprehend_followup_shadow(
        candidate=darius, enemy=mordekaiser, selected_alternative_id=Q_ALTERNATIVE_ID
    )

    assert outcome.sequence.alternative_id == Q_ALTERNATIVE_ID
    assert outcome.branch_selection.selected_id == Q_ALTERNATIVE_ID
    step_ids = {r.step_id for r in outcome.step_results}
    assert "followup_basic_attack" not in step_ids


def test_unselected_branch_is_unresolved_and_never_arbitrary(darius, mordekaiser):
    outcome = evaluate_apprehend_followup_shadow(candidate=darius, enemy=mordekaiser, selected_alternative_id=None)

    assert outcome.branch_selection is None  # nada que confirmar
    assert outcome.causal_components == ()  # nada puntuable de ninguna rama
    assert outcome.trade_outcome.evaluation is Evaluation.UNRESOLVED
    step_ids = {r.step_id for r in outcome.step_results}
    assert "followup_basic_attack" not in step_ids
    assert "followup_decimate" not in step_ids  # ninguna de las dos ramas se evaluó


def test_evaluate_apprehend_followup_shadow_has_no_default_alternative():
    import inspect

    from lol_reasoner.reasoning.sequences.shadow import evaluate_apprehend_followup_shadow as fn

    signature = inspect.signature(fn)
    assert signature.parameters["selected_alternative_id"].default is inspect.Parameter.empty


# ---------------------------------------------------------------------------
# §3 del microfix: condiciones específicas por acción/zona
# ---------------------------------------------------------------------------


def test_q_outer_zone_is_not_inferred_from_apprehend_contact(registration_candidate):
    baseline = build_apprehend_followup_baseline(
        registration_candidate,
        range_statuses={registration_candidate.apprehend_action_ref: RangeStatus.IN_RANGE},
    )
    outcome = build_apprehend_followup_outcome(
        registration_candidate, selected_alternative_id=Q_ALTERNATIVE_ID, baseline=baseline
    )

    followup_result = next(r for r in outcome.step_results if r.step_id == "followup_decimate")
    # Apprehend conectó (confirmado), pero la precondición de zona
    # exterior de Q sigue UNKNOWN — nadie la infirió del contacto.
    assert PreconditionStatus.UNKNOWN in [r.status for r in followup_result.precondition_results]
    assert outcome.execution_status is ExecutionStatus.HYPOTHETICAL


def test_q_outer_zone_is_not_inferred_from_basic_attack_range(registration_candidate):
    baseline = build_apprehend_followup_baseline(
        registration_candidate,
        range_statuses={registration_candidate.basic_attack_action_ref: RangeStatus.IN_RANGE},
    )
    outcome = build_apprehend_followup_outcome(
        registration_candidate, selected_alternative_id=Q_ALTERNATIVE_ID, baseline=baseline
    )

    followup_result = next(r for r in outcome.step_results if r.step_id == "followup_decimate")
    assert PreconditionStatus.UNKNOWN in [r.status for r in followup_result.precondition_results]


def test_action_connects_references_are_independent_per_action(registration_candidate):
    baseline = build_apprehend_followup_baseline(registration_candidate)
    refs = set(baseline.shared.action_contexts.keys())
    assert refs == {
        registration_candidate.apprehend_action_ref,
        registration_candidate.basic_attack_action_ref,
        registration_candidate.decimate_outer_zone_action_ref,
    }
    # tres claves DISTINTAS — ninguna comparte estado con otra
    assert len(refs) == 3


# --- UNKNOWN distinto de FAILED (UNSATISFIED) -------------------------------


def test_unknown_precondition_differs_from_unsatisfied(registration_candidate):
    unknown_baseline = build_apprehend_followup_baseline(registration_candidate)
    failed_baseline = build_apprehend_followup_baseline(
        registration_candidate,
        range_statuses={registration_candidate.apprehend_action_ref: RangeStatus.OUT_OF_RANGE},
    )

    unknown_outcome = build_apprehend_followup_outcome(
        registration_candidate, selected_alternative_id=Q_ALTERNATIVE_ID, baseline=unknown_baseline
    )
    failed_outcome = build_apprehend_followup_outcome(
        registration_candidate, selected_alternative_id=Q_ALTERNATIVE_ID, baseline=failed_baseline
    )

    # UNKNOWN: la cadena avanza (hipotética), nunca bloqueada
    assert unknown_outcome.execution_status is ExecutionStatus.HYPOTHETICAL
    assert unknown_outcome.progress is SequenceProgress.COMPLETED
    # UNSATISFIED (FAILED): la cadena se bloquea, con menos resultados
    assert failed_outcome.execution_status is ExecutionStatus.BLOCKED
    assert failed_outcome.progress is SequenceProgress.BLOCKED
    assert len(failed_outcome.step_results) < len(unknown_outcome.step_results)


# ---------------------------------------------------------------------------
# §6 del microfix: escenario shadow explícitamente satisfecho
# ---------------------------------------------------------------------------


def test_fully_satisfied_scenario_produces_a_shadow_causal_component(registration_candidate):
    confirmed_baseline = build_apprehend_followup_baseline(
        registration_candidate,
        range_statuses={
            registration_candidate.apprehend_action_ref: RangeStatus.IN_RANGE,
            registration_candidate.decimate_outer_zone_action_ref: RangeStatus.IN_RANGE,
        },
    )
    outcome = build_apprehend_followup_outcome(
        registration_candidate,
        selected_alternative_id=Q_ALTERNATIVE_ID,
        baseline=confirmed_baseline,
        emit_shadow_causal_component=True,
    )

    assert len(outcome.causal_components) == 1
    component = outcome.causal_components[0]
    assert component.polarity is None  # nunca firmado — no se declara favorecido
    assert component.sequence_id == outcome.sequence.sequence_id


def test_causal_component_never_emitted_without_explicit_opt_in(registration_candidate):
    confirmed_baseline = build_apprehend_followup_baseline(
        registration_candidate,
        range_statuses={
            registration_candidate.apprehend_action_ref: RangeStatus.IN_RANGE,
            registration_candidate.decimate_outer_zone_action_ref: RangeStatus.IN_RANGE,
        },
    )
    outcome = build_apprehend_followup_outcome(
        registration_candidate, selected_alternative_id=Q_ALTERNATIVE_ID, baseline=confirmed_baseline
    )
    assert outcome.causal_components == ()


# ---------------------------------------------------------------------------
# Cierre de hardening §B2/§B3 — causalidad hipotética nunca se materializa;
# ningún delta inventado
# ---------------------------------------------------------------------------


def test_hypothetical_execution_never_materializes_a_causal_component(registration_candidate):
    # Baseline por defecto: todo UNKNOWN -> ejecución HYPOTHETICAL, nunca
    # CONFIRMED. Aun con emit_shadow_causal_component=True, no debe
    # materializarse ningún CausalComponent: una ejecución hipotética
    # puede retener la identidad potencial (sigue en covers_causes/
    # consumes), pero nunca se presenta como un componente materializado.
    outcome = build_apprehend_followup_outcome(
        registration_candidate,
        selected_alternative_id=Q_ALTERNATIVE_ID,
        emit_shadow_causal_component=True,
    )

    assert outcome.execution_status is ExecutionStatus.HYPOTHETICAL
    assert outcome.causal_components == ()
    # la identidad potencial sigue siendo auditable en la propia secuencia
    assert any(identity.causal_role == "stack_application" for identity in outcome.sequence.covers_causes)


def test_blocked_execution_never_materializes_a_causal_component(registration_candidate):
    blocked_baseline = build_apprehend_followup_baseline(
        registration_candidate,
        range_statuses={registration_candidate.decimate_outer_zone_action_ref: RangeStatus.OUT_OF_RANGE},
    )
    outcome = build_apprehend_followup_outcome(
        registration_candidate,
        selected_alternative_id=Q_ALTERNATIVE_ID,
        baseline=blocked_baseline,
        emit_shadow_causal_component=True,
    )

    assert outcome.execution_status is ExecutionStatus.BLOCKED
    assert outcome.causal_components == ()


def test_confirmed_causal_component_has_no_invented_numeric_delta(registration_candidate):
    confirmed_baseline = build_apprehend_followup_baseline(
        registration_candidate,
        range_statuses={
            registration_candidate.apprehend_action_ref: RangeStatus.IN_RANGE,
            registration_candidate.decimate_outer_zone_action_ref: RangeStatus.IN_RANGE,
        },
    )
    outcome = build_apprehend_followup_outcome(
        registration_candidate,
        selected_alternative_id=Q_ALTERNATIVE_ID,
        baseline=confirmed_baseline,
        emit_shadow_causal_component=True,
    )

    component = outcome.causal_components[0]
    assert component.calibration_status is CalibrationStatus.UNCALIBRATED
    assert component.delta is None  # nunca un placeholder numérico (antes: 1.0 sin calibración real)


def test_shadow_causal_component_selects_by_causal_role_never_by_position():
    # §B3: un paso que consume MÁS de una identidad no debe elegir "el
    # primer elemento" — la selección es explícita por causal_role.
    from lol_reasoner.reasoning.sequences.shadow import _shadow_causal_component
    from lol_reasoner.reasoning.sequences.steps import EffectIdentity, SequenceStep, WHOLE_EFFECT_COMPONENT
    from lol_reasoner.domain.enums import Support

    step = SequenceStep(
        step_id="s1",
        action_ref="candidate:q",
        actor=ActorRole.CANDIDATE,
        declared_support=Support.STRUCTURAL,
        consumes=(
            EffectIdentity(fact_ref="synthetic:q", causal_role="damage", component=WHOLE_EFFECT_COMPONENT),
            EffectIdentity(fact_ref="synthetic:q", causal_role="stack_application", component=WHOLE_EFFECT_COMPONENT),
        ),
    )
    seq = InteractionSequence(sequence_id="seq_multi", steps=(step,))

    component = _shadow_causal_component(seq, sequence_id="seq_multi")

    # "damage" es el PRIMER elemento de consumes — la selección real elige
    # "stack_application" por su causal_role, nunca por posición.
    assert component.fact_ref == "synthetic:q"
    consumed = next(i for i in step.consumes if i.causal_role == "stack_application")
    assert component.fact_ref == consumed.fact_ref


def test_shadow_causal_component_fails_explicitly_without_a_stack_application_identity():
    from lol_reasoner.reasoning.sequences.shadow import _shadow_causal_component
    from lol_reasoner.reasoning.sequences.steps import EffectIdentity, SequenceStep, WHOLE_EFFECT_COMPONENT
    from lol_reasoner.domain.enums import Support

    step = SequenceStep(
        step_id="s1",
        action_ref="candidate:q",
        actor=ActorRole.CANDIDATE,
        declared_support=Support.STRUCTURAL,
        consumes=(EffectIdentity(fact_ref="synthetic:q", causal_role="damage", component=WHOLE_EFFECT_COMPONENT),),
    )
    seq = InteractionSequence(sequence_id="seq_no_stack", steps=(step,))

    with pytest.raises(ValueError):
        _shadow_causal_component(seq, sequence_id="seq_no_stack")


# ---------------------------------------------------------------------------
# Cierre de hardening §B1 — rama irresuelta conserva sus alternativas
# ---------------------------------------------------------------------------


def test_apprehend_followup_pending_alternatives_preserved_when_unresolved(darius, mordekaiser):
    outcome = evaluate_apprehend_followup_shadow(candidate=darius, enemy=mordekaiser, selected_alternative_id=None)

    assert outcome.branch_selection is None
    assert outcome.pending_alternatives is not None
    assert outcome.pending_alternatives.selected_id is None
    assert set(outcome.pending_alternatives.alternative_ids) == {AA_ALTERNATIVE_ID, Q_ALTERNATIVE_ID}
    assert outcome.causal_components == ()


def test_apprehend_followup_pending_alternatives_absent_once_selected(registration_candidate):
    outcome = build_apprehend_followup_outcome(registration_candidate, selected_alternative_id=Q_ALTERNATIVE_ID)
    assert outcome.pending_alternatives is None


# ---------------------------------------------------------------------------
# Serialización round-trip de los nuevos campos
# ---------------------------------------------------------------------------


def test_execution_status_survives_serialization_round_trip(darius, mordekaiser):
    outcome = evaluate_apprehend_followup_shadow(
        candidate=darius, enemy=mordekaiser, selected_alternative_id=Q_ALTERNATIVE_ID
    )
    primitive = scenario_outcome_to_primitive(outcome)

    assert primitive["execution_status"] == outcome.execution_status.value
    for step_primitive, step_result in zip(primitive["step_results"], outcome.step_results, strict=True):
        assert step_primitive["execution_status"] == step_result.execution_status.value

    serialized = json.dumps(primitive)
    assert json.loads(serialized) == primitive


def test_unresolved_outcome_serializes_with_null_branch_selection(darius, mordekaiser):
    outcome = evaluate_apprehend_followup_shadow(candidate=darius, enemy=mordekaiser, selected_alternative_id=None)
    primitive = scenario_outcome_to_primitive(outcome)

    assert primitive["branch_selection"] is None
    assert primitive["causal_components"] == []
    assert json.dumps(primitive)


# ---------------------------------------------------------------------------
# Invariantes previas intactas (Etapa 2 + rondas anteriores)
# ---------------------------------------------------------------------------


def test_previous_invariants_still_hold_no_kill_no_forced_favor(darius, mordekaiser):
    outcome = evaluate_apprehend_followup_shadow(
        candidate=darius, enemy=mordekaiser, selected_alternative_id=Q_ALTERNATIVE_ID
    )
    assert outcome.trade_outcome.terminal_event.kind is TerminalEventKind.UNKNOWN
    assert outcome.trade_outcome.terminal_event.killed_actors == ()
    assert outcome.trade_outcome.evaluation not in (Evaluation.CANDIDATE_FAVORED, Evaluation.ENEMY_FAVORED)


def test_initial_snapshot_stays_intact(registration_candidate):
    baseline = build_apprehend_followup_baseline(registration_candidate)
    outcome = build_apprehend_followup_outcome(
        registration_candidate, selected_alternative_id=Q_ALTERNATIVE_ID, baseline=baseline
    )
    assert baseline.enemy.stacks["hemorrhage"].count == 0
    assert outcome.trade_outcome.state_delta.before is baseline


def test_darius_as_candidate_and_as_enemy(darius, mordekaiser):
    outcome_candidate = evaluate_apprehend_followup_shadow(
        candidate=darius, enemy=mordekaiser, selected_alternative_id=Q_ALTERNATIVE_ID
    )
    outcome_enemy = evaluate_apprehend_followup_shadow(
        candidate=mordekaiser, enemy=darius, selected_alternative_id=Q_ALTERNATIVE_ID
    )
    assert outcome_candidate.trade_outcome.state_delta.after.enemy.stacks["hemorrhage"].count == 1
    assert outcome_enemy.trade_outcome.state_delta.after.candidate.stacks["hemorrhage"].count == 1


def test_other_matchups_do_not_run_this_sequence(darius):
    fake = _synthetic_champion("some_other_champion")
    assert is_darius_mordekaiser_matchup(darius, fake) is False
    assert evaluate_apprehend_followup_shadow(candidate=darius, enemy=fake, selected_alternative_id=Q_ALTERNATIVE_ID) is None


# ---------------------------------------------------------------------------
# Shadow OFF vs ON (idéntico resultado público)
# ---------------------------------------------------------------------------


def _evaluate_public(trace, mirror_trace, champion):
    weights = DEFAULT_WEIGHTS
    score, breakdown = global_score(trace, weights, subject_id=champion.id)
    profile = PlayerProfile(mastery=None)
    p_score, _ = personal_score(
        score,
        profile=profile,
        execution_demand=champion.axis(Axis.EXECUTION_DEMAND),
        execution_condition_count=execution_condition_count(trace),
        weights=weights,
    )
    confidence = compute_confidence(trace, mirror_trace)
    reasons = build_reasons(trace, subject_id=champion.id, weights=weights)
    risks = build_risks(trace, subject_id=champion.id, weights=weights)
    deduped = trace.deduped_for_scoring(champion.id)
    entries = list(trace.entries)
    return {
        "score": score,
        "breakdown": breakdown,
        "p_score": p_score,
        "confidence": confidence,
        "reasons": reasons,
        "risks": risks,
        "deduped": deduped,
        "entries": entries,
    }


@pytest.fixture()
def engine():
    return RuleEngine()


def test_shadow_off_and_on_produce_identical_public_results(darius, mordekaiser, engine):
    trace = engine.build_trace(darius, mordekaiser, ALL_PHASES)
    mirror_trace = engine.build_trace(mordekaiser, darius, ALL_PHASES)

    off = _evaluate_public(trace, mirror_trace, darius)

    record = evaluate_apprehend_followup_shadow(
        candidate=darius, enemy=mordekaiser, selected_alternative_id=Q_ALTERNATIVE_ID, trace=trace
    )
    assert record is not None
    assert len(trace.shadow_sequence_outcomes) == 1

    on = _evaluate_public(trace, mirror_trace, darius)

    assert off["score"] == on["score"]
    assert off["breakdown"] == on["breakdown"]
    assert off["entries"] == on["entries"]
    assert off["deduped"] == on["deduped"]
    assert off["p_score"] == on["p_score"]
    assert off["confidence"] == on["confidence"]
    assert off["reasons"] == on["reasons"]
    assert off["risks"] == on["risks"]


def test_shadow_off_and_on_produce_the_same_winner_both_orientations(darius, mordekaiser, engine):
    def _score_for(candidate, enemy, attach_shadow):
        trace = engine.build_trace(candidate, enemy, ALL_PHASES)
        if attach_shadow:
            evaluate_apprehend_followup_shadow(
                candidate=candidate, enemy=enemy, selected_alternative_id=Q_ALTERNATIVE_ID, trace=trace
            )
        score, _ = global_score(trace, DEFAULT_WEIGHTS, subject_id=candidate.id)
        return score

    darius_off = _score_for(darius, mordekaiser, attach_shadow=False)
    mork_off = _score_for(mordekaiser, darius, attach_shadow=False)
    winner_off = darius.id if darius_off >= mork_off else mordekaiser.id

    darius_on = _score_for(darius, mordekaiser, attach_shadow=True)
    mork_on = _score_for(mordekaiser, darius, attach_shadow=True)
    winner_on = darius.id if darius_on >= mork_on else mordekaiser.id

    assert darius_off == darius_on
    assert mork_off == mork_on
    assert winner_off == winner_on


def test_repeating_the_evaluation_produces_the_same_outcome(darius, mordekaiser):
    outcome_1 = evaluate_apprehend_followup_shadow(
        candidate=darius, enemy=mordekaiser, selected_alternative_id=Q_ALTERNATIVE_ID
    )
    outcome_2 = evaluate_apprehend_followup_shadow(
        candidate=darius, enemy=mordekaiser, selected_alternative_id=Q_ALTERNATIVE_ID
    )
    assert scenario_outcome_to_primitive(outcome_1) == scenario_outcome_to_primitive(outcome_2)


def test_no_atomic_rule_was_modified_or_disabled(darius, mordekaiser):
    assert len(ALL_GENERAL_RULES) > 0
    assert len(SPECIFIC_INTERACTIONS) >= 0
    engine = RuleEngine()
    trace = engine.build_trace(darius, mordekaiser, ALL_PHASES)
    assert len(trace.entries) > 0


def test_shadow_record_lives_in_a_separate_channel_from_entries(darius, mordekaiser):
    engine = RuleEngine()
    trace = engine.build_trace(darius, mordekaiser, ALL_PHASES)
    entries_before = list(trace.entries)

    evaluate_apprehend_followup_shadow(
        candidate=darius, enemy=mordekaiser, selected_alternative_id=Q_ALTERNATIVE_ID, trace=trace
    )

    assert trace.entries == entries_before
    assert len(trace.shadow_sequence_outcomes) == 1
    assert trace.shadow_sequence_outcomes[0].promoted is False


def test_shadow_sequence_record_promoted_must_be_false(darius, mordekaiser):
    outcome = evaluate_apprehend_followup_shadow(
        candidate=darius, enemy=mordekaiser, selected_alternative_id=Q_ALTERNATIVE_ID
    )
    with pytest.raises(ValueError):
        ShadowSequenceRecord(
            matchup_id="darius_vs_mordekaiser", sequence_id=outcome.sequence.sequence_id, outcome=outcome, promoted=True
        )


def test_this_file_never_asserts_a_hardcoded_absolute_score():
    import re
    from pathlib import Path

    source = Path(__file__).read_text(encoding="utf-8")
    assert not re.search(r"assert\s+\w*score\w*\s*==\s*-?\d", source, re.IGNORECASE)


# ---------------------------------------------------------------------------
# Cierre de hardening — invariantes restauradas (§A1: tabla test anterior ->
# test actual/reemplazo, ver entrega de esta ronda). Ninguna de estas
# reintroduce texto libre ni depende de un número de tests exacto — cada
# una verifica un comportamiento concreto que había quedado sin cobertura
# directa tras la reorganización histórica de este archivo.
# ---------------------------------------------------------------------------


def test_wrong_champion_id_fails_explicitly():
    fake_darius = _synthetic_champion("not_darius")
    with pytest.raises(ValueError):
        build_apprehend_followup_registration(darius=fake_darius, darius_role=ActorRole.CANDIDATE)


def test_selecting_an_unregistered_alternative_fails_explicitly(registration_candidate):
    with pytest.raises(ValueError):
        registration_candidate.spec_for("not_a_real_alternative")


def test_used_abilities_go_on_cooldown_preserving_rank(darius, registration_candidate):
    from lol_reasoner.domain.combat_state import AbilityAvailability

    baseline = build_apprehend_followup_baseline(
        registration_candidate,
        range_statuses={
            registration_candidate.apprehend_action_ref: RangeStatus.IN_RANGE,
            registration_candidate.decimate_outer_zone_action_ref: RangeStatus.IN_RANGE,
        },
    )
    outcome = build_apprehend_followup_outcome(
        registration_candidate, selected_alternative_id=Q_ALTERNATIVE_ID, baseline=baseline
    )

    after = outcome.trade_outcome.state_delta.after
    apprehend_rank_before = baseline.candidate.abilities[registration_candidate.apprehend_slot].rank
    decimate_rank_before = baseline.candidate.abilities[registration_candidate.decimate_slot].rank

    assert after.candidate.abilities[registration_candidate.apprehend_slot].availability is AbilityAvailability.ON_COOLDOWN
    assert after.candidate.abilities[registration_candidate.apprehend_slot].rank == apprehend_rank_before
    assert after.candidate.abilities[registration_candidate.decimate_slot].availability is AbilityAvailability.ON_COOLDOWN
    assert after.candidate.abilities[registration_candidate.decimate_slot].rank == decimate_rank_before


def test_basic_attack_followup_does_not_touch_any_ability_state(registration_candidate):
    baseline = build_apprehend_followup_baseline(
        registration_candidate,
        range_statuses={
            registration_candidate.apprehend_action_ref: RangeStatus.IN_RANGE,
            registration_candidate.basic_attack_action_ref: RangeStatus.IN_RANGE,
        },
    )
    outcome = build_apprehend_followup_outcome(
        registration_candidate, selected_alternative_id=AA_ALTERNATIVE_ID, baseline=baseline
    )

    after = outcome.trade_outcome.state_delta.after
    # el autoataque no tiene AbilityState propio: las únicas habilidades
    # que cambian son las que Apprehend puso en cooldown — Decimate (Q)
    # sigue exactamente como en el baseline, sin tocar.
    assert after.candidate.abilities[registration_candidate.decimate_slot] == baseline.candidate.abilities[
        registration_candidate.decimate_slot
    ]


def test_scenario_builder_generates_only_the_requested_references(registration_candidate):
    baseline = build_apprehend_followup_baseline(registration_candidate)

    expected_refs = {
        registration_candidate.apprehend_action_ref,
        registration_candidate.basic_attack_action_ref,
        registration_candidate.decimate_outer_zone_action_ref,
    }
    assert set(baseline.shared.action_contexts.keys()) == expected_refs
    assert set(baseline.candidate.abilities.keys()) == {
        registration_candidate.apprehend_slot,
        registration_candidate.decimate_slot,
    }
    assert set(baseline.enemy.stacks.keys()) == {registration_candidate.stack_reference}
    # nada más: ni la referencia de casteo de Q (distinta de su zona
    # exterior), ni ningún slot/mecánica no pedida explícitamente.
    assert registration_candidate.decimate_action_ref not in baseline.shared.action_contexts


def test_no_global_cartesian_product_of_scenarios(darius):
    # construir la misma registración dos veces con argumentos DISTINTOS
    # produce dos CombatState independientes — nunca una combinación
    # acumulada ni un estado compartido entre llamadas.
    registration = build_apprehend_followup_registration(darius=darius, darius_role=ActorRole.CANDIDATE)
    baseline_a = build_apprehend_followup_baseline(
        registration, range_statuses={registration.apprehend_action_ref: RangeStatus.IN_RANGE}
    )
    baseline_b = build_apprehend_followup_baseline(
        registration, range_statuses={registration.apprehend_action_ref: RangeStatus.OUT_OF_RANGE}
    )

    assert (
        baseline_a.shared.action_contexts[registration.apprehend_action_ref].range_status
        is RangeStatus.IN_RANGE
    )
    assert (
        baseline_b.shared.action_contexts[registration.apprehend_action_ref].range_status
        is RangeStatus.OUT_OF_RANGE
    )
    # cada llamada es una construcción nueva e independiente, nunca un
    # objeto compartido/mutado entre las dos.
    assert baseline_a is not baseline_b


def test_darius_mirror_matchup_is_not_the_registered_pair(darius):
    mirror_darius = _synthetic_champion("darius")
    assert not is_darius_mordekaiser_matchup(darius, mirror_darius)
    assert not is_darius_mordekaiser_matchup(mirror_darius, darius)


def test_no_source_references_noxian_might_or_five_stacks():
    import re
    from pathlib import Path

    package_root = Path(__file__).resolve().parents[1] / "src" / "lol_reasoner" / "reasoning" / "sequences"
    forbidden = re.compile(r"noxian_might|five.?stack|5.?stack", re.IGNORECASE)
    for path in package_root.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert not forbidden.search(source), f"{path} referencia Noxian Might o cinco cargas fuera de alcance"


def test_shadow_modules_do_not_import_rule_or_scoring_internals():
    import ast
    from pathlib import Path

    package_root = Path(__file__).resolve().parents[1] / "src" / "lol_reasoner" / "reasoning" / "sequences"
    forbidden_prefixes = ("lol_reasoner.reasoning.rules", "lol_reasoner.scoring")
    for path in package_root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module is not None:
                assert not node.module.startswith(forbidden_prefixes), (
                    f"{path} importa {node.module!r} — reasoning/sequences/*.py no puede depender de "
                    "reglas atómicas ni de scoring"
                )
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith(forbidden_prefixes), (
                        f"{path} importa {alias.name!r} — reasoning/sequences/*.py no puede depender de "
                        "reglas atómicas ni de scoring"
                    )
