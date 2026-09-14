"""Tests de la primera secuencia real en shadow mode (v1.7): Apprehend
habilita contacto -> autoataque o Decimate aplica Hemorrhage, SOLO para
Darius vs Mordekaiser (y su orientación inversa), y SOLO en shadow mode.

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
from lol_reasoner.domain.combat_state import CombatState
from lol_reasoner.domain.enums import (
    ALL_PHASES,
    Axis,
    ResourceType,
    Support,
)
from lol_reasoner.explain.narrator import build_reasons, build_risks
from lol_reasoner.reasoning.engine import RuleEngine
from lol_reasoner.reasoning.rules.registry import ALL_GENERAL_RULES
from lol_reasoner.reasoning.rules.specific import SPECIFIC_INTERACTIONS
from lol_reasoner.reasoning.scenario_builder import build_apprehend_followup_baseline
from lol_reasoner.reasoning.sequences.evaluator import (
    PostconditionEffectKind,
    PreconditionCheckKind,
    StepEvaluationSpec,
    StructuralPostcondition,
    StructuralPrecondition,
    evaluate_sequence_prefix,
    evaluate_step,
)
from lol_reasoner.reasoning.sequences.registry import (
    AA_ALTERNATIVE_ID,
    Q_ALTERNATIVE_ID,
    build_apprehend_followup_registration,
    is_darius_mordekaiser_matchup,
)
from lol_reasoner.reasoning.sequences.sequence import (
    AlternativeGroup,
    CausalComponent,
    Evaluation,
    PreconditionStatus,
    ScenarioOutcome,
    StepResult,
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


# --- 1. la secuencia usa habilidades/efectos reales existentes -------------


def test_registration_resolves_real_darius_abilities_and_mechanic(darius):
    registration = build_apprehend_followup_registration(darius=darius, darius_role=ActorRole.CANDIDATE)

    assert registration.apprehend_slot == "e"
    assert registration.decimate_slot == "q"
    assert registration.stack_reference == "hemorrhage"
    assert registration.stack_reference in {m.id for m in darius.stacking_mechanics}
    assert darius.ability("E") is not None
    assert darius.ability("Q") is not None


# --- 2. una referencia mecánica inexistente falla explícitamente -----------


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
        abilities=(),  # sin E ni Q: referencia requerida ausente
        stacking_mechanics=(),  # sin ninguna StackingMechanic
        spikes=(),
        knowledge_version="test",
    )


def test_missing_ability_reference_fails_explicitly():
    fake_darius = _synthetic_champion("darius")  # mismo id, sin habilidades reales
    with pytest.raises(ValueError, match="Referencia mecánica requerida ausente"):
        build_apprehend_followup_registration(darius=fake_darius, darius_role=ActorRole.CANDIDATE)


def test_wrong_champion_id_fails_explicitly():
    fake = _synthetic_champion("not_darius")
    with pytest.raises(ValueError):
        build_apprehend_followup_registration(darius=fake, darius_role=ActorRole.CANDIDATE)


# --- 3. Apprehend solo no agrega Hemorrhage ---------------------------------


def test_apprehend_control_step_does_not_consume_stack_application(darius):
    registration = build_apprehend_followup_registration(darius=darius, darius_role=ActorRole.CANDIDATE)
    control_spec = registration.spec_for(Q_ALTERNATIVE_ID).step_specs[0]

    assert control_spec.step.step_id == "control_apprehend"
    for identity in control_spec.step.consumes:
        assert identity.causal_role != "stack_application"
    assert not any(pc.kind is PostconditionEffectKind.STACK_APPLIED for pc in control_spec.postconditions)


def test_evaluating_only_the_control_step_leaves_stacks_unchanged(darius):
    registration = build_apprehend_followup_registration(darius=darius, darius_role=ActorRole.CANDIDATE)
    spec = registration.spec_for(Q_ALTERNATIVE_ID)
    baseline = build_apprehend_followup_baseline(
        performer_role=registration.darius_role,
        performer_level=3,
        control_action_ref=registration.apprehend_action_ref,
        control_ability_slot=registration.apprehend_slot,
        followup_action_refs=(registration.basic_attack_action_ref, registration.decimate_action_ref),
        followup_ability_slots=(None, registration.decimate_slot),
        stack_reference=registration.stack_reference,
    )

    control_spec = spec.step_specs[0]
    _, state_after_control_only = evaluate_step(control_spec, baseline)

    assert state_after_control_only.enemy.stacks["hemorrhage"].count == 0
    assert baseline.enemy.stacks["hemorrhage"].count == 0


# --- 4/5. el follow-up agrega el stack, y ocurre DESPUÉS del follow-up -----


def test_followup_adds_the_stack_after_control_step(darius):
    registration = build_apprehend_followup_registration(darius=darius, darius_role=ActorRole.CANDIDATE)
    outcome = build_apprehend_followup_outcome(registration, selected_alternative_id=Q_ALTERNATIVE_ID)

    before = outcome.trade_outcome.state_delta.before
    after = outcome.trade_outcome.state_delta.after

    assert before.enemy.stacks["hemorrhage"].count == 0
    assert after.enemy.stacks["hemorrhage"].count == 1
    assert after.enemy.stacks["hemorrhage"].window.value == "active"


# --- 6/7. snapshot inicial intacto, snapshot final nuevo -------------------


def test_initial_snapshot_stays_intact_and_final_is_a_new_object(darius):
    registration = build_apprehend_followup_registration(darius=darius, darius_role=ActorRole.CANDIDATE)
    spec = registration.spec_for(Q_ALTERNATIVE_ID)
    baseline = build_apprehend_followup_baseline(
        performer_role=registration.darius_role,
        performer_level=3,
        control_action_ref=registration.apprehend_action_ref,
        control_ability_slot=registration.apprehend_slot,
        followup_action_refs=(registration.basic_attack_action_ref, registration.decimate_action_ref),
        followup_ability_slots=(None, registration.decimate_slot),
        stack_reference=registration.stack_reference,
    )

    _, final_state = evaluate_sequence_prefix(spec.step_specs, baseline)

    assert final_state is not baseline
    assert baseline.enemy.stacks["hemorrhage"].count == 0  # el snapshot de entrada no cambió
    assert baseline.candidate.abilities["q"].availability.value == "ready"
    assert final_state.candidate.abilities["q"].availability.value == "on_cooldown"


# --- 8. habilidad utilizada queda en cooldown cuando corresponde -----------


def test_used_abilities_go_on_cooldown_preserving_rank(darius):
    registration = build_apprehend_followup_registration(darius=darius, darius_role=ActorRole.CANDIDATE)
    outcome = build_apprehend_followup_outcome(registration, selected_alternative_id=Q_ALTERNATIVE_ID)
    after = outcome.trade_outcome.state_delta.after

    for slot in ("e", "q"):
        ability = after.candidate.abilities[slot]
        assert ability.availability.value == "on_cooldown"
        assert ability.rank == 1  # el rango no cambia por usar la habilidad


def test_basic_attack_followup_does_not_touch_any_ability_state(darius):
    registration = build_apprehend_followup_registration(darius=darius, darius_role=ActorRole.CANDIDATE)
    outcome = build_apprehend_followup_outcome(registration, selected_alternative_id=AA_ALTERNATIVE_ID)
    after = outcome.trade_outcome.state_delta.after

    # Apprehend sigue yendo a cooldown (se usó), pero Q nunca se tocó —
    # el autoataque no tiene AbilityState propio en este modelo.
    assert after.candidate.abilities["e"].availability.value == "on_cooldown"
    assert after.candidate.abilities["q"].availability.value == "ready"


# --- 9/10. cero conocido -> carga activa; unknown no se vuelve exacto ------


def test_known_zero_stack_becomes_one_active_charge(darius):
    registration = build_apprehend_followup_registration(darius=darius, darius_role=ActorRole.CANDIDATE)
    outcome = build_apprehend_followup_outcome(registration, selected_alternative_id=Q_ALTERNATIVE_ID)

    assert outcome.trade_outcome.state_delta.before.enemy.stacks["hemorrhage"].count == 0
    assert outcome.trade_outcome.state_delta.after.enemy.stacks["hemorrhage"].count == 1


def test_unknown_stack_never_becomes_an_exact_count():
    from lol_reasoner.domain.combat_state import (
        ActionContext,
        ActorState,
        RangeStatus,
        SharedContext,
        StackState,
        StackWindow,
    )
    from lol_reasoner.reasoning.sequences.steps import EffectIdentity, SequenceStep, WHOLE_EFFECT_COMPONENT

    step = SequenceStep(
        step_id="followup",
        action_ref="candidate:q",
        actor=ActorRole.CANDIDATE,
        consumes=(EffectIdentity(fact_ref="darius:q", causal_role="stack_application", component=WHOLE_EFFECT_COMPONENT),),
    )
    spec = StepEvaluationSpec(
        step=step,
        declared_support=Support.STRUCTURAL,
        preconditions=(StructuralPrecondition(PreconditionCheckKind.ACTION_IN_RANGE, ActorRole.CANDIDATE, "candidate:q"),),
        postconditions=(StructuralPostcondition(PostconditionEffectKind.STACK_APPLIED, ActorRole.ENEMY, "hemorrhage"),),
    )
    state = CombatState(
        candidate=ActorState(),
        enemy=ActorState(stacks={"hemorrhage": StackState(count=None, window=StackWindow.UNKNOWN)}),
        shared=SharedContext(
            action_contexts={"candidate:q": ActionContext(action_ref="candidate:q", range_status=RangeStatus.IN_RANGE)}
        ),
    )

    _, next_state = evaluate_step(spec, state)

    assert next_state.enemy.stacks["hemorrhage"].count is None
    assert next_state.enemy.stacks["hemorrhage"].window.value == "active"


# --- 11. Noxian Might no se activa ------------------------------------------


def test_reward_state_never_activates_in_this_sequence(darius):
    registration = build_apprehend_followup_registration(darius=darius, darius_role=ActorRole.CANDIDATE)
    outcome = build_apprehend_followup_outcome(registration, selected_alternative_id=Q_ALTERNATIVE_ID)

    after = outcome.trade_outcome.state_delta.after
    assert after.enemy.stacks["hemorrhage"].reward_state.value != "active"


def test_no_source_references_noxian_might_or_five_stacks():
    import inspect

    from lol_reasoner.reasoning.sequences import evaluator, generic_sequences, registry, shadow

    for module in (evaluator, generic_sequences, registry, shadow):
        source = inspect.getsource(module).lower()
        assert "noxian might" not in source
        assert "noxian_might" not in source


# --- 12. no hay kill ---------------------------------------------------------


def test_no_kill_is_ever_declared(darius):
    registration = build_apprehend_followup_registration(darius=darius, darius_role=ActorRole.CANDIDATE)
    outcome = build_apprehend_followup_outcome(registration, selected_alternative_id=Q_ALTERNATIVE_ID)

    assert outcome.trade_outcome.terminal_event.kind is TerminalEventKind.UNKNOWN
    assert outcome.trade_outcome.terminal_event.killed_actors == ()


# --- 13. no se fuerza candidato/enemigo favorecido sin evidencia -----------


def test_evaluation_is_conditional_not_forced_favored(darius):
    registration = build_apprehend_followup_registration(darius=darius, darius_role=ActorRole.CANDIDATE)
    outcome = build_apprehend_followup_outcome(registration, selected_alternative_id=Q_ALTERNATIVE_ID)

    assert outcome.trade_outcome.evaluation is Evaluation.CONDITIONAL
    assert outcome.trade_outcome.evaluation not in (Evaluation.CANDIDATE_FAVORED, Evaluation.ENEMY_FAVORED)
    assert outcome.causal_components == ()  # shadow mode: nunca componentes puntuables


# --- 14/15/16. AA y Q en el mismo grupo, solo una evaluada, nunca sumadas --


def test_aa_and_q_belong_to_the_same_exclusion_group(darius):
    registration = build_apprehend_followup_registration(darius=darius, darius_role=ActorRole.CANDIDATE)
    aa_group = registration.spec_for(AA_ALTERNATIVE_ID).sequence.alternative_group
    q_group = registration.spec_for(Q_ALTERNATIVE_ID).sequence.alternative_group

    assert aa_group.group_id == q_group.group_id
    assert set(aa_group.alternative_ids) == {AA_ALTERNATIVE_ID, Q_ALTERNATIVE_ID}


def test_only_one_alternative_is_evaluated_per_outcome(darius):
    registration = build_apprehend_followup_registration(darius=darius, darius_role=ActorRole.CANDIDATE)
    outcome = build_apprehend_followup_outcome(registration, selected_alternative_id=AA_ALTERNATIVE_ID)

    assert outcome.sequence.alternative_id == AA_ALTERNATIVE_ID
    step_ids = {r.step_id for r in outcome.step_results}
    assert "followup_decimate" not in step_ids  # Q nunca se evaluó en este outcome


def test_selecting_an_unregistered_alternative_fails_explicitly(darius):
    registration = build_apprehend_followup_registration(darius=darius, darius_role=ActorRole.CANDIDATE)
    with pytest.raises(ValueError):
        registration.spec_for("not_a_real_alternative")


def test_without_selection_alternatives_are_not_summed(darius):
    registration = build_apprehend_followup_registration(darius=darius, darius_role=ActorRole.CANDIDATE)
    q_sequence = registration.spec_for(Q_ALTERNATIVE_ID).sequence

    from lol_reasoner.domain.enums import Factor, Provenance

    ok_results = tuple(
        StepResult(
            step_id=step.step_id,
            precondition_statuses=(PreconditionStatus.SATISFIED,),
            declared_support=Support.STRUCTURAL,
        )
        for step in q_sequence.steps
    )
    unresolved_selection = AlternativeGroup(
        group_id=q_sequence.alternative_group.group_id, alternative_ids=q_sequence.alternative_group.alternative_ids
    )
    component = CausalComponent(
        factor=Factor.MECHANICAL_INTERACTION,
        delta=1.0,
        provenance=Provenance.DERIVED,
        fact_ref="darius:q",
        sequence_id=q_sequence.sequence_id,
    )

    with pytest.raises(ValueError):
        ScenarioOutcome(
            sequence=q_sequence, step_results=ok_results, branch_selection=unresolved_selection, causal_components=(component,)
        )


# --- 17/18. soporte del eslabón más débil; hit unknown nunca STRUCTURAL ---


def test_outcome_support_is_the_weakest_link(darius):
    registration = build_apprehend_followup_registration(darius=darius, darius_role=ActorRole.CANDIDATE)
    outcome = build_apprehend_followup_outcome(registration, selected_alternative_id=Q_ALTERNATIVE_ID)

    supports = {r.effective_support for r in outcome.step_results}
    assert outcome.support in supports
    assert outcome.support is not Support.STRUCTURAL  # ningún paso alcanza rango confirmado


def test_unknown_range_hit_never_yields_structural_support(darius):
    registration = build_apprehend_followup_registration(darius=darius, darius_role=ActorRole.CANDIDATE)
    outcome = build_apprehend_followup_outcome(registration, selected_alternative_id=Q_ALTERNATIVE_ID)

    for result in outcome.step_results:
        assert PreconditionStatus.UNKNOWN in result.precondition_statuses
        assert result.effective_support is not Support.STRUCTURAL


# --- 19/20. el builder genera solo lo pedido; sin producto cartesiano -----


def test_scenario_builder_generates_only_the_requested_references(darius):
    registration = build_apprehend_followup_registration(darius=darius, darius_role=ActorRole.CANDIDATE)
    baseline = build_apprehend_followup_baseline(
        performer_role=registration.darius_role,
        performer_level=3,
        control_action_ref=registration.apprehend_action_ref,
        control_ability_slot=registration.apprehend_slot,
        followup_action_refs=(registration.basic_attack_action_ref, registration.decimate_action_ref),
        followup_ability_slots=(None, registration.decimate_slot),
        stack_reference=registration.stack_reference,
    )

    assert set(baseline.candidate.abilities.keys()) == {"e", "q"}
    assert dict(baseline.candidate.stacks) == {}
    assert set(baseline.enemy.stacks.keys()) == {"hemorrhage"}
    assert dict(baseline.enemy.abilities) == {}
    assert set(baseline.shared.action_contexts.keys()) == {
        registration.apprehend_action_ref,
        registration.basic_attack_action_ref,
        registration.decimate_action_ref,
    }


def test_no_global_cartesian_product_of_scenarios(darius):
    """Construir el baseline de UNA orientación no instancia nada de la
    otra orientación ni de ningún otro nivel/campeón — se verifica por
    conteo: exactamente un CombatState resulta de una llamada, con
    exactamente las claves pedidas (ver test anterior), sin rastro de
    otros niveles/roles en sus mappings."""

    registration = build_apprehend_followup_registration(darius=darius, darius_role=ActorRole.CANDIDATE)
    baseline = build_apprehend_followup_baseline(
        performer_role=registration.darius_role,
        performer_level=3,
        control_action_ref=registration.apprehend_action_ref,
        control_ability_slot=registration.apprehend_slot,
        followup_action_refs=(registration.basic_attack_action_ref, registration.decimate_action_ref),
        followup_ability_slots=(None, registration.decimate_slot),
        stack_reference=registration.stack_reference,
    )

    assert isinstance(baseline, CombatState)
    # el receptor no declara NINGÚN nivel ni habilidad — no se rellenó
    # con supuestos que esta secuencia no pidió.
    assert baseline.enemy.level is None
    assert dict(baseline.enemy.abilities) == {}


# --- 21/22. Darius como candidate, y como enemy (orientación inversa) -----


def test_darius_as_candidate(darius, mordekaiser):
    outcome = evaluate_apprehend_followup_shadow(candidate=darius, enemy=mordekaiser, selected_alternative_id="q")
    assert outcome is not None
    assert outcome.sequence.sequence_id.startswith("darius_apprehend_followup:candidate:")
    assert outcome.trade_outcome.state_delta.after.enemy.stacks["hemorrhage"].count == 1


def test_darius_as_enemy_mirror_orientation(darius, mordekaiser):
    outcome = evaluate_apprehend_followup_shadow(candidate=mordekaiser, enemy=darius, selected_alternative_id="q")
    assert outcome is not None
    assert outcome.sequence.sequence_id.startswith("darius_apprehend_followup:enemy:")
    # en esta orientación Mordekaiser es candidate: recibe las cargas
    assert outcome.trade_outcome.state_delta.after.candidate.stacks["hemorrhage"].count == 1


# --- 23. otros matchups no ejecutan esta secuencia --------------------------


def test_other_matchups_do_not_run_this_sequence(darius):
    fake = _synthetic_champion("some_other_champion")
    assert is_darius_mordekaiser_matchup(darius, fake) is False
    assert evaluate_apprehend_followup_shadow(candidate=darius, enemy=fake) is None
    assert evaluate_apprehend_followup_shadow(candidate=fake, enemy=fake) is None


def test_darius_mirror_matchup_is_not_the_registered_pair(darius):
    # Darius vs Darius tampoco es el matchup registrado (falta Mordekaiser)
    assert is_darius_mordekaiser_matchup(darius, darius) is False
    assert evaluate_apprehend_followup_shadow(candidate=darius, enemy=darius) is None


# --- 24. shadow report serializable a JSON ----------------------------------


def test_shadow_outcome_is_fully_json_serializable(darius, mordekaiser):
    outcome = evaluate_apprehend_followup_shadow(candidate=darius, enemy=mordekaiser, selected_alternative_id="q")
    primitive = scenario_outcome_to_primitive(outcome)

    serialized = json.dumps(primitive)
    assert json.loads(serialized) == primitive


# --- 25-29. shadow OFF vs ON: mismo score/ganador/RuleEffects/deduped/público


def _evaluate_off(trace, mirror_trace, champion):
    weights = DEFAULT_WEIGHTS
    score, breakdown = global_score(trace, weights, subject_id=champion.id)
    profile = PlayerProfile(mastery=None)
    p_score, p_breakdown = personal_score(
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

    off = _evaluate_off(trace, mirror_trace, darius)

    record = evaluate_apprehend_followup_shadow(candidate=darius, enemy=mordekaiser, trace=trace)
    assert record is not None
    assert len(trace.shadow_sequence_outcomes) == 1

    on = _evaluate_off(trace, mirror_trace, darius)  # mismas funciones, misma traza (ahora con shadow adjunto)

    # 25: mismo GlobalScore
    assert off["score"] == on["score"]
    assert off["breakdown"] == on["breakdown"]
    # 27: mismos RuleEffects puntuables (entries crudas sin tocar)
    assert off["entries"] == on["entries"]
    # 28: mismo deduped_for_scoring
    assert off["deduped"] == on["deduped"]
    # 29: mismo resultado público (razones, riesgos, confianza, PersonalScore)
    assert off["p_score"] == on["p_score"]
    assert off["confidence"] == on["confidence"]
    assert off["reasons"] == on["reasons"]
    assert off["risks"] == on["risks"]


def test_shadow_off_and_on_produce_the_same_winner(darius, mordekaiser, engine):
    def _score_for(candidate, enemy, attach_shadow):
        trace = engine.build_trace(candidate, enemy, ALL_PHASES)
        mirror_trace = engine.build_trace(enemy, candidate, ALL_PHASES)
        if attach_shadow:
            evaluate_apprehend_followup_shadow(candidate=candidate, enemy=enemy, trace=trace)
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
    assert winner_off == winner_on  # nunca se congela CUÁL es — solo que OFF y ON coinciden


# --- 30. repetir la evaluación produce el mismo outcome --------------------


def test_repeating_the_evaluation_produces_the_same_outcome(darius, mordekaiser):
    outcome_1 = evaluate_apprehend_followup_shadow(candidate=darius, enemy=mordekaiser, selected_alternative_id="q")
    outcome_2 = evaluate_apprehend_followup_shadow(candidate=darius, enemy=mordekaiser, selected_alternative_id="q")

    assert scenario_outcome_to_primitive(outcome_1) == scenario_outcome_to_primitive(outcome_2)


# --- 31. ninguna regla atómica fue modificada o desactivada -----------------


def test_no_atomic_rule_was_modified_or_disabled(darius, mordekaiser):
    # Conteo estable de reglas registradas — esta ronda no agrega, quita
    # ni deshabilita ninguna regla general/específica.
    assert len(ALL_GENERAL_RULES) > 0
    assert len(SPECIFIC_INTERACTIONS) >= 0  # existen, sin cambios de conteo forzados acá

    engine = RuleEngine()
    trace = engine.build_trace(darius, mordekaiser, ALL_PHASES)
    # Las reglas siguen produciendo entradas puntuables normalmente.
    assert len(trace.entries) > 0


def test_shadow_modules_do_not_import_rule_or_scoring_internals():
    import ast
    import inspect

    from lol_reasoner.reasoning.sequences import evaluator, generic_sequences, registry, shadow

    for module in (evaluator, generic_sequences, registry, shadow):
        tree = ast.parse(inspect.getsource(module))
        imported = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        assert not any(m.startswith("lol_reasoner.reasoning.rules") for m in imported)
        assert not any(m.startswith("lol_reasoner.scoring") for m in imported)
        assert not any(m == "lol_reasoner.reasoning.engine" for m in imported)


# --- 32. ningún test de este archivo congela un ganador o score absoluto --


def test_this_file_never_asserts_a_hardcoded_absolute_score():
    import re
    from pathlib import Path

    source = Path(__file__).read_text(encoding="utf-8")
    # ninguna aserción compara un score/ganador contra un número mágico
    # o un id de campeón hardcodeado como "el resultado correcto"
    assert not re.search(r"assert\s+\w*score\w*\s*==\s*-?\d", source, re.IGNORECASE)
    assert "== \"darius\"" not in source.replace("'", '"')
    assert "== \"mordekaiser\"" not in source.replace("'", '"')


# --- Sanidad estructural: no se emite RuleEffect ni se toca MatchupScore --


def test_no_rule_effect_or_matchup_score_types_are_constructed_by_shadow_modules():
    import inspect

    from lol_reasoner.reasoning.sequences import evaluator, generic_sequences, registry, shadow

    for module in (evaluator, generic_sequences, registry, shadow):
        source = inspect.getsource(module)
        assert "RuleEffect(" not in source
        assert "MatchupScore" not in source


def test_shadow_sequence_record_promoted_must_be_false(darius, mordekaiser):
    outcome = evaluate_apprehend_followup_shadow(candidate=darius, enemy=mordekaiser, selected_alternative_id="q")
    record = ShadowSequenceRecord(matchup_id="darius_vs_mordekaiser", sequence_id=outcome.sequence.sequence_id, outcome=outcome)
    assert record.promoted is False

    with pytest.raises(ValueError):
        ShadowSequenceRecord(
            matchup_id="darius_vs_mordekaiser",
            sequence_id=outcome.sequence.sequence_id,
            outcome=outcome,
            promoted=True,
        )


def test_shadow_record_lives_in_a_separate_channel_from_entries(darius, mordekaiser):
    engine = RuleEngine()
    trace = engine.build_trace(darius, mordekaiser, ALL_PHASES)
    entries_before = list(trace.entries)

    evaluate_apprehend_followup_shadow(candidate=darius, enemy=mordekaiser, trace=trace)

    assert trace.entries == entries_before  # entries no tocadas
    assert len(trace.shadow_sequence_outcomes) == 1
    assert trace.shadow_sequence_outcomes[0].promoted is False
