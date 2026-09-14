"""Tests del trade bidireccional mínimo Darius-Mordekaiser en shadow mode
(v1.7): Apprehend habilita contacto -> AA/Q aplica Hemorrhage -> Obliterate
de Mordekaiser responde y alimenta su propia Darkness Rise.

No hay simulación de tiempo, coordenadas, pathfinding, DPS, runas/objetos/
summoners, búsqueda cartesiana ni ganador obligatorio en este archivo —
eso sigue fuera de alcance. Ningún test congela un ganador ni un score
absoluto.
"""

from __future__ import annotations

import json

import pytest

from lol_reasoner.domain.combat_state import InvalidatorStatus, RangeStatus
from lol_reasoner.domain.enums import ALL_PHASES, Axis
from lol_reasoner.explain.narrator import build_reasons, build_risks
from lol_reasoner.reasoning.engine import RuleEngine
from lol_reasoner.reasoning.sequences.registry import (
    APPREHEND_INTERRUPT_INVALIDATOR_KEY,
    Q_ALTERNATIVE_ID,
    build_bidirectional_trade_baseline,
    build_bidirectional_trade_registration,
)
from lol_reasoner.reasoning.sequences.sequence import (
    Evaluation,
    ExecutionStatus,
    PreconditionStatus,
    SequenceProgress,
    TerminalEventKind,
    scenario_outcome_to_primitive,
)
from lol_reasoner.reasoning.sequences.shadow import (
    build_bidirectional_trade_outcome,
    evaluate_bidirectional_trade_shadow,
)
from lol_reasoner.reasoning.sequences.steps import ActorRole
from lol_reasoner.scoring.confidence import compute_confidence
from lol_reasoner.scoring.global_score import global_score
from lol_reasoner.scoring.personal_score import PlayerProfile, execution_condition_count, personal_score
from lol_reasoner.scoring.weights import DEFAULT_WEIGHTS


@pytest.fixture()
def registration_candidate(darius, mordekaiser):
    return build_bidirectional_trade_registration(darius=darius, mordekaiser=mordekaiser, darius_role=ActorRole.CANDIDATE)


@pytest.fixture()
def registration_enemy(darius, mordekaiser):
    return build_bidirectional_trade_registration(darius=darius, mordekaiser=mordekaiser, darius_role=ActorRole.ENEMY)


# --- Justificación de la respuesta elegida (Obliterate, no W/AA) -----------


def test_response_resolves_to_obliterate_and_darkness_rise(registration_candidate):
    assert registration_candidate.mordekaiser_response_slot == "q"
    assert registration_candidate.mordekaiser_stack_reference == "darkness_rise"
    assert registration_candidate.mordekaiser_stack_threshold == 3


def test_missing_mordekaiser_response_reference_fails_explicitly(darius):
    from lol_reasoner.domain.champion import Champion, DamageProfile
    from lol_reasoner.domain.enums import ResourceType

    fake_mordekaiser = Champion(
        id="mordekaiser",
        name="Mordekaiser",
        archetype="synthetic",
        damage_profile=DamageProfile(physical=0.0, magic=0.0, true=0.0),
        axes={},
        casting_resource=ResourceType.RESOURCELESS,
        trade_patterns=frozenset(),
        tags=frozenset(),
        abilities=(),  # sin Q: referencia requerida ausente
        stacking_mechanics=(),
        spikes=(),
        knowledge_version="test",
    )
    with pytest.raises(ValueError, match="Referencia mecánica requerida ausente"):
        build_bidirectional_trade_registration(darius=darius, mordekaiser=fake_mordekaiser, darius_role=ActorRole.CANDIDATE)


# --- 1. pasos de ambos actores en una secuencia; orden causal preservado --


def test_trade_sequence_contains_steps_from_both_actors(registration_candidate):
    spec = registration_candidate.spec_for(Q_ALTERNATIVE_ID)
    actors = [step.actor for step in spec.steps]
    assert actors == [ActorRole.CANDIDATE, ActorRole.CANDIDATE, ActorRole.ENEMY]
    step_ids = [step.step_id for step in spec.steps]
    assert step_ids == ["control_apprehend", "followup_decimate", "response_obliterate"]


def test_causal_order_is_preserved_in_step_results(registration_candidate):
    outcome = build_bidirectional_trade_outcome(registration_candidate, selected_alternative_id=Q_ALTERNATIVE_ID)
    assert [r.step_id for r in outcome.step_results] == [
        "control_apprehend",
        "followup_decimate",
        "response_obliterate",
    ]


# --- estado/proyección de AMBOS actores ------------------------------------


def test_state_delta_reflects_both_actors(registration_candidate):
    outcome = build_bidirectional_trade_outcome(registration_candidate, selected_alternative_id=Q_ALTERNATIVE_ID)
    after = outcome.trade_outcome.state_delta.after

    # Darius (candidate): E y Q usados -> cooldown
    assert after.candidate.abilities["e"].availability.value == "on_cooldown"
    assert after.candidate.abilities["q"].availability.value == "on_cooldown"
    # Mordekaiser (enemy): recibe Hemorrhage Y, si conecta su respuesta,
    # acumula su PROPIA Darkness Rise
    assert after.enemy.stacks["hemorrhage"].count == 1
    assert after.enemy.stacks["darkness_rise"].count == 1
    assert after.enemy.abilities["q"].availability.value == "on_cooldown"


# --- respuesta enemiga: bloqueada, condicionada, satisfecha ----------------


def test_mordekaiser_response_is_hypothetical_by_default(registration_candidate):
    outcome = build_bidirectional_trade_outcome(registration_candidate, selected_alternative_id=Q_ALTERNATIVE_ID)
    response_result = next(r for r in outcome.step_results if r.step_id == "response_obliterate")
    assert response_result.execution_status is ExecutionStatus.HYPOTHETICAL
    assert PreconditionStatus.UNKNOWN in [r.status for r in response_result.precondition_results]


def test_mordekaiser_response_blocked_when_apprehend_interrupt_present(registration_candidate):
    blocked_baseline = build_bidirectional_trade_baseline(
        registration_candidate,
        response_invalidators={APPREHEND_INTERRUPT_INVALIDATOR_KEY: InvalidatorStatus.PRESENT},
    )
    outcome = build_bidirectional_trade_outcome(
        registration_candidate, selected_alternative_id=Q_ALTERNATIVE_ID, baseline=blocked_baseline
    )

    assert outcome.progress is SequenceProgress.BLOCKED
    response_result = outcome.step_results[-1]
    assert response_result.step_id == "response_obliterate"
    assert response_result.effective_support is None
    # Mordekaiser nunca acumuló Darkness Rise: la respuesta no ocurrió
    assert outcome.trade_outcome.state_delta.after.enemy.stacks["darkness_rise"].count == 0


def test_mordekaiser_response_satisfied_when_everything_confirmed(registration_candidate):
    confirmed_baseline = build_bidirectional_trade_baseline(
        registration_candidate,
        range_statuses={
            registration_candidate.apprehend_followup.apprehend_action_ref: RangeStatus.IN_RANGE,
            registration_candidate.apprehend_followup.decimate_outer_zone_action_ref: RangeStatus.IN_RANGE,
            registration_candidate.mordekaiser_response_action_ref: RangeStatus.IN_RANGE,
        },
        response_invalidators={APPREHEND_INTERRUPT_INVALIDATOR_KEY: InvalidatorStatus.ABSENT},
    )
    outcome = build_bidirectional_trade_outcome(
        registration_candidate, selected_alternative_id=Q_ALTERNATIVE_ID, baseline=confirmed_baseline
    )

    assert outcome.execution_status is ExecutionStatus.CONFIRMED
    assert outcome.support.value == "structural"
    response_result = outcome.step_results[-1]
    assert response_result.execution_status is ExecutionStatus.CONFIRMED


# --- desplazamiento sin garantía automática de Q exterior ------------------


def test_apprehend_confirmed_does_not_guarantee_q_outer_zone(registration_candidate):
    baseline = build_bidirectional_trade_baseline(
        registration_candidate,
        range_statuses={registration_candidate.apprehend_followup.apprehend_action_ref: RangeStatus.IN_RANGE},
    )
    outcome = build_bidirectional_trade_outcome(
        registration_candidate, selected_alternative_id=Q_ALTERNATIVE_ID, baseline=baseline
    )
    followup_result = next(r for r in outcome.step_results if r.step_id == "followup_decimate")
    assert PreconditionStatus.UNKNOWN in [r.status for r in followup_result.precondition_results]
    assert outcome.execution_status is not ExecutionStatus.CONFIRMED


def test_apprehend_confirmed_does_not_guarantee_response_connects(registration_candidate):
    baseline = build_bidirectional_trade_baseline(
        registration_candidate,
        range_statuses={registration_candidate.apprehend_followup.apprehend_action_ref: RangeStatus.IN_RANGE},
    )
    outcome = build_bidirectional_trade_outcome(
        registration_candidate, selected_alternative_id=Q_ALTERNATIVE_ID, baseline=baseline
    )
    response_result = outcome.step_results[-1]
    assert PreconditionStatus.UNKNOWN in [r.status for r in response_result.precondition_results]


# --- acumulaciones por actor; pasiva no activada antes del umbral ----------


def test_stacks_accumulate_independently_per_actor(registration_candidate):
    outcome = build_bidirectional_trade_outcome(registration_candidate, selected_alternative_id=Q_ALTERNATIVE_ID)
    after = outcome.trade_outcome.state_delta.after
    # Hemorrhage (recibido por Mordekaiser) y Darkness Rise (propio de
    # Mordekaiser) son mecánicas DISTINTAS que no se mezclan entre sí.
    assert after.enemy.stacks["hemorrhage"].count == 1
    assert after.enemy.stacks["darkness_rise"].count == 1
    assert "darkness_rise" not in after.candidate.stacks


def test_passive_not_activated_below_threshold(registration_candidate):
    baseline = build_bidirectional_trade_baseline(registration_candidate, mordekaiser_initial_darkness_rise_count=0)
    outcome = build_bidirectional_trade_outcome(
        registration_candidate, selected_alternative_id=Q_ALTERNATIVE_ID, baseline=baseline
    )
    darkness_rise = outcome.trade_outcome.state_delta.after.enemy.stacks["darkness_rise"]
    assert darkness_rise.count == 1  # 0 + 1 aplicación
    assert darkness_rise.reward_state.value == "inactive"  # 1 < 3: hecho conocido, no activo


def test_passive_activates_exactly_at_threshold(registration_candidate):
    # Mordekaiser ya tiene 2 cargas conocidas de Darkness Rise (umbral 3,
    # dato real de la KB) — esta ÚNICA aplicación de Obliterate lo cruza.
    baseline = build_bidirectional_trade_baseline(registration_candidate, mordekaiser_initial_darkness_rise_count=2)
    outcome = build_bidirectional_trade_outcome(
        registration_candidate, selected_alternative_id=Q_ALTERNATIVE_ID, baseline=baseline
    )
    darkness_rise = outcome.trade_outcome.state_delta.after.enemy.stacks["darkness_rise"]
    assert darkness_rise.count == 3
    assert darkness_rise.reward_state.value == "active"


def test_passive_state_preserved_when_initial_count_is_unknown(registration_candidate):
    baseline = build_bidirectional_trade_baseline(registration_candidate, mordekaiser_initial_darkness_rise_count=None)
    outcome = build_bidirectional_trade_outcome(
        registration_candidate, selected_alternative_id=Q_ALTERNATIVE_ID, baseline=baseline
    )
    darkness_rise = outcome.trade_outcome.state_delta.after.enemy.stacks["darkness_rise"]
    assert darkness_rise.count is None  # no se inventa un conteo exacto
    assert darkness_rise.reward_state.value == "unknown"  # tampoco si cruzó el umbral


# --- trade no letal; outcome condicional o irresuelto ----------------------


def test_trade_is_not_necessarily_lethal(registration_candidate):
    outcome = build_bidirectional_trade_outcome(registration_candidate, selected_alternative_id=Q_ALTERNATIVE_ID)
    assert outcome.trade_outcome.terminal_event.kind is TerminalEventKind.UNKNOWN
    assert outcome.trade_outcome.terminal_event.killed_actors == ()


def test_trade_outcome_is_conditional_not_forced(registration_candidate):
    outcome = build_bidirectional_trade_outcome(registration_candidate, selected_alternative_id=Q_ALTERNATIVE_ID)
    assert outcome.trade_outcome.evaluation is Evaluation.CONDITIONAL
    assert outcome.trade_outcome.evaluation not in (Evaluation.CANDIDATE_FAVORED, Evaluation.ENEMY_FAVORED)
    assert outcome.causal_components == ()


def test_trade_without_selected_branch_is_unresolved(darius, mordekaiser):
    outcome = evaluate_bidirectional_trade_shadow(candidate=darius, enemy=mordekaiser, selected_alternative_id=None)
    assert outcome.branch_selection is None
    assert outcome.trade_outcome.evaluation is Evaluation.UNRESOLVED
    step_ids = {r.step_id for r in outcome.step_results}
    assert "response_obliterate" not in step_ids  # sin rama elegida, la respuesta ni se evalúa


# --- ambas orientaciones ----------------------------------------------------


def test_darius_candidate_orientation(darius, mordekaiser):
    outcome = evaluate_bidirectional_trade_shadow(
        candidate=darius, enemy=mordekaiser, selected_alternative_id=Q_ALTERNATIVE_ID
    )
    assert outcome.sequence.sequence_id.startswith("darius_apprehend_followup:candidate:")
    assert outcome.trade_outcome.state_delta.after.enemy.stacks["darkness_rise"].count == 1


def test_darius_enemy_orientation_mirror(darius, mordekaiser):
    outcome = evaluate_bidirectional_trade_shadow(
        candidate=mordekaiser, enemy=darius, selected_alternative_id=Q_ALTERNATIVE_ID
    )
    assert outcome.sequence.sequence_id.startswith("darius_apprehend_followup:enemy:")
    # Mordekaiser ahora es candidate: su propia Darkness Rise vive en candidate.stacks
    assert outcome.trade_outcome.state_delta.after.candidate.stacks["darkness_rise"].count == 1
    assert outcome.trade_outcome.state_delta.after.candidate.stacks["hemorrhage"].count == 1


def test_other_matchups_do_not_run_the_trade(darius):
    from tests.test_shadow_sequences import _synthetic_champion

    fake = _synthetic_champion("some_other_champion")
    assert evaluate_bidirectional_trade_shadow(candidate=darius, enemy=fake, selected_alternative_id=Q_ALTERNATIVE_ID) is None


# --- serialización round-trip; determinismo --------------------------------


def test_trade_outcome_serializes_fully_to_json(darius, mordekaiser):
    outcome = evaluate_bidirectional_trade_shadow(
        candidate=darius, enemy=mordekaiser, selected_alternative_id=Q_ALTERNATIVE_ID
    )
    primitive = scenario_outcome_to_primitive(outcome)
    serialized = json.dumps(primitive)
    assert json.loads(serialized) == primitive
    assert len(primitive["step_results"]) == 3
    assert primitive["step_results"][-1]["step_id"] == "response_obliterate"


def test_trade_outcome_is_deterministic(darius, mordekaiser):
    outcome_1 = evaluate_bidirectional_trade_shadow(
        candidate=darius, enemy=mordekaiser, selected_alternative_id=Q_ALTERNATIVE_ID
    )
    outcome_2 = evaluate_bidirectional_trade_shadow(
        candidate=darius, enemy=mordekaiser, selected_alternative_id=Q_ALTERNATIVE_ID
    )
    assert scenario_outcome_to_primitive(outcome_1) == scenario_outcome_to_primitive(outcome_2)


# --- shadow OFF vs ON: sin diferencias públicas -----------------------------


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


@pytest.mark.parametrize(
    "candidate_role",
    ["darius_candidate", "mordekaiser_candidate"],
)
def test_trade_shadow_off_and_on_are_identical_both_orientations(darius, mordekaiser, engine, candidate_role):
    candidate, enemy = (darius, mordekaiser) if candidate_role == "darius_candidate" else (mordekaiser, darius)

    trace = engine.build_trace(candidate, enemy, ALL_PHASES)
    mirror_trace = engine.build_trace(enemy, candidate, ALL_PHASES)

    off = _evaluate_public(trace, mirror_trace, candidate)

    record = evaluate_bidirectional_trade_shadow(
        candidate=candidate, enemy=enemy, selected_alternative_id=Q_ALTERNATIVE_ID, trace=trace
    )
    assert record is not None
    assert len(trace.shadow_sequence_outcomes) == 1

    on = _evaluate_public(trace, mirror_trace, candidate)

    assert off["score"] == on["score"]
    assert off["breakdown"] == on["breakdown"]
    assert off["entries"] == on["entries"]
    assert off["deduped"] == on["deduped"]
    assert off["p_score"] == on["p_score"]
    assert off["confidence"] == on["confidence"]
    assert off["reasons"] == on["reasons"]
    assert off["risks"] == on["risks"]


def test_trade_shadow_off_and_on_produce_the_same_winner(darius, mordekaiser, engine):
    def _score_for(candidate, enemy, attach_shadow):
        trace = engine.build_trace(candidate, enemy, ALL_PHASES)
        if attach_shadow:
            evaluate_bidirectional_trade_shadow(
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


# --- ninguna regla atómica modificada; ningún score absoluto congelado ----


def test_no_rule_effect_or_scoring_types_constructed_by_trade_modules():
    import inspect

    from lol_reasoner.reasoning.sequences import registry, shadow

    for module in (registry, shadow):
        source = inspect.getsource(module)
        assert "RuleEffect(" not in source
        assert "MatchupScore" not in source


def test_this_file_never_asserts_a_hardcoded_absolute_score():
    import re
    from pathlib import Path

    source = Path(__file__).read_text(encoding="utf-8")
    assert not re.search(r"assert\s+\w*score\w*\s*==\s*-?\d", source, re.IGNORECASE)
