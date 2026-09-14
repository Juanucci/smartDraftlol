"""Tests de los tipos de secuencia y resultado (v1.7, Etapa 2 — endurecida).

Cubren únicamente `reasoning/sequences/{steps,sequence}.py`: identidad
mecánica estructural, el contrato declarativo de un paso, soporte de una
cadena (satisfecha/desconocida/no satisfecha, eslabón más débil, única
fuente de verdad declared/effective), prefijo ordenado de `step_results`,
coherencia secuencia↔selección de rama, grupos de exclusión mutua, el
contrato no binario de un trade (incluida muerte de 0/1/2 actores), el
resultado agregado de un escenario, y la frontera de serialización. Todo
con actores/habilidades/mecánicas SINTÉTICAS — nada de esto es Darius,
Mordekaiser, ni ningún campeón real. No hay motor de transición, generador
de escenarios, scoring ni integración con `RuleEngine`/`ReasoningTrace` en
este archivo — esa es una etapa distinta. Ningún test de este archivo
congela un ganador ni un score exacto.
"""

from __future__ import annotations

import dataclasses
import json
from enum import Enum

import pytest

from lol_reasoner.domain.combat_state import ActorState, CombatState
from lol_reasoner.domain.enums import Factor, Polarity, Provenance, Support
from lol_reasoner.reasoning.sequences import (
    WHOLE_EFFECT_COMPONENT,
    ActorRole,
    AlternativeGroup,
    CausalComponent,
    EffectIdentity,
    Evaluation,
    ExecutionStatus,
    InteractionSequence,
    PreconditionCheckKind,
    PreconditionResult,
    PreconditionStatus,
    ScenarioOutcome,
    SequenceProgress,
    SequenceStep,
    StateDelta,
    StepResult,
    StructuralPrecondition,
    TerminalEvent,
    TerminalEventKind,
    TradeOutcome,
    chain_execution_status,
    chain_support,
    require_sequence_progress,
    resolve_step_support,
    scenario_outcome_to_primitive,
    sequence_progress,
    sequence_to_primitive,
)

# --- fixtures sintéticas -----------------------------------------------------


def _identity(
    component: str = WHOLE_EFFECT_COMPONENT, causal_role: str = "damage", fact_ref: str = "synthetic:q"
) -> EffectIdentity:
    return EffectIdentity(fact_ref=fact_ref, causal_role=causal_role, component=component)


def _step(
    step_id: str = "s1", *, consumes: tuple[EffectIdentity, ...] = (), declared_support: Support = Support.STRUCTURAL
) -> SequenceStep:
    return SequenceStep(
        step_id=step_id,
        action_ref="candidate:q",
        actor=ActorRole.CANDIDATE,
        declared_support=declared_support,
        consumes=consumes,
    )


def _combat_state(level: int | None = None) -> CombatState:
    return CombatState(candidate=ActorState(level=level), enemy=ActorState())


def _synthetic_precondition(reference: str = "candidate:q") -> StructuralPrecondition:
    return StructuralPrecondition(PreconditionCheckKind.ACTION_CONNECTS, ActorRole.CANDIDATE, reference)


def _precondition_results(statuses: tuple[PreconditionStatus, ...]) -> tuple[PreconditionResult, ...]:
    return tuple(
        PreconditionResult(precondition=_synthetic_precondition(f"candidate:ref_{i}"), status=status)
        for i, status in enumerate(statuses)
    )


def _result(
    step_id: str = "s1",
    *,
    statuses: tuple[PreconditionStatus, ...] = (PreconditionStatus.SATISFIED,),
    declared: Support = Support.STRUCTURAL,
    inherited: ExecutionStatus = ExecutionStatus.CONFIRMED,
) -> StepResult:
    return StepResult(
        step_id=step_id,
        precondition_results=_precondition_results(statuses),
        declared_support=declared,
        inherited_execution_status=inherited,
    )


def _blocked_result(step_id: str = "s1") -> StepResult:
    return StepResult(
        step_id=step_id,
        precondition_results=_precondition_results((PreconditionStatus.UNSATISFIED,)),
        declared_support=Support.STRUCTURAL,
    )


def _causal_component(sequence_id: str = "seq", *, polarity: Polarity | None = None) -> CausalComponent:
    return CausalComponent(
        factor=Factor.MECHANICAL_INTERACTION,
        delta=1.0,
        provenance=Provenance.DERIVED,
        fact_ref="synthetic:q",
        sequence_id=sequence_id,
        polarity=polarity,
    )


# --- 1. EffectIdentity: estable, hashable, granular -------------------------


def test_effect_identity_is_stable_hashable_and_granular():
    a = _identity(component="blade")
    b = _identity(component="blade")
    assert a == b
    assert hash(a) == hash(b)

    c = _identity(component="handle")
    assert a != c
    assert hash(a) != hash(c)


# --- 2. dos componentes distintos de la misma habilidad no se deduplican ---


def test_two_distinct_components_of_the_same_ability_are_not_deduplicated():
    blade = _identity(fact_ref="synthetic:q", causal_role="damage", component="blade")
    handle = _identity(fact_ref="synthetic:q", causal_role="damage", component="handle")

    step = _step(consumes=(blade, handle))
    seq = InteractionSequence(sequence_id="seq", steps=(step,))

    assert blade in seq.covers_causes
    assert handle in seq.covers_causes
    assert len(seq.covers_causes) == 2


# --- 3. rechazo de IDs vacíos o mal tipados ----------------------------------


@pytest.mark.parametrize("bad_value", [123, None, True, ""])
def test_effect_identity_rejects_empty_or_wrong_typed_fields(bad_value):
    exc = ValueError if bad_value == "" else TypeError
    with pytest.raises(exc):
        EffectIdentity(fact_ref=bad_value, causal_role="damage", component=WHOLE_EFFECT_COMPONENT)


def test_sequence_step_rejects_empty_step_id():
    with pytest.raises(ValueError):
        SequenceStep(step_id="   ", action_ref="candidate:q", actor=ActorRole.CANDIDATE, declared_support=Support.STRUCTURAL)


def test_sequence_step_rejects_wrong_typed_actor():
    with pytest.raises(TypeError):
        SequenceStep(
            step_id="s1", action_ref="candidate:q", actor="candidate", declared_support=Support.STRUCTURAL
        )  # type: ignore[arg-type]


def test_interaction_sequence_rejects_empty_sequence_id():
    with pytest.raises(ValueError):
        InteractionSequence(sequence_id="   ", steps=(_step(),))


# --- WHOLE_EFFECT_COMPONENT: constante pública, no un string mágico repetido


def test_whole_effect_component_is_a_stable_public_constant():
    assert WHOLE_EFFECT_COMPONENT == "whole"
    identity = EffectIdentity(fact_ref="synthetic:q", causal_role="damage", component=WHOLE_EFFECT_COMPONENT)
    assert identity.component == WHOLE_EFFECT_COMPONENT


# --- 4. secuencia vacía rechazada -------------------------------------------


def test_interaction_sequence_rejects_empty_steps():
    with pytest.raises(ValueError):
        InteractionSequence(sequence_id="seq", steps=())


# --- 5. orden de pasos preservado --------------------------------------------


def test_interaction_sequence_preserves_step_order():
    step_a = _step("s1")
    step_b = _step("s2")
    step_c = _step("s3")

    seq = InteractionSequence(sequence_id="seq", steps=(step_a, step_b, step_c))

    assert [s.step_id for s in seq.steps] == ["s1", "s2", "s3"]


# --- 6. step_id duplicados rechazados ----------------------------------------


def test_interaction_sequence_rejects_duplicate_step_ids():
    with pytest.raises(ValueError):
        InteractionSequence(sequence_id="seq", steps=(_step("s1"), _step("s1")))


# --- 7. covers_causes derivado de los pasos ----------------------------------


def test_covers_causes_is_derived_from_steps_consumed_identities():
    id_a = _identity(component="a")
    id_b = _identity(component="b")
    seq = InteractionSequence(
        sequence_id="seq",
        steps=(_step("s1", consumes=(id_a,)), _step("s2", consumes=(id_b,))),
    )

    assert seq.covers_causes == frozenset({id_a, id_b})


def test_covers_causes_deterministic_for_equivalent_steps():
    id_a = _identity(component="a")
    seq_1 = InteractionSequence(sequence_id="seq1", steps=(_step("s1", consumes=(id_a,)),))
    seq_2 = InteractionSequence(sequence_id="seq2", steps=(_step("s1", consumes=(id_a,)),))

    assert seq_1.covers_causes == seq_2.covers_causes


def test_covers_causes_deduplicates_repeated_identities_across_steps_without_losing_distinct_ones():
    shared = _identity(component="shared")
    distinct = _identity(component="distinct")
    seq = InteractionSequence(
        sequence_id="seq",
        steps=(
            _step("s1", consumes=(shared,)),
            _step("s2", consumes=(shared, distinct)),
        ),
    )

    assert seq.covers_causes == frozenset({shared, distinct})


# --- 8. imposibilidad de declarar cobertura manual falsa ---------------------


def test_covers_causes_cannot_be_provided_manually():
    with pytest.raises(TypeError):
        InteractionSequence(
            sequence_id="seq",
            steps=(_step("s1"),),
            covers_causes=frozenset({_identity()}),  # type: ignore[call-arg]
        )


def test_sequence_step_rejects_duplicate_consumed_identities():
    identity = _identity()
    with pytest.raises(ValueError):
        SequenceStep(
            step_id="s1",
            action_ref="candidate:q",
            actor=ActorRole.CANDIDATE,
            declared_support=Support.STRUCTURAL,
            consumes=(identity, identity),
        )


# --- 9-11. precondición satisfecha / desconocida / no satisfecha -----------


def test_resolve_step_support_with_satisfied_precondition_keeps_declared_support():
    result = resolve_step_support(
        declared_support=Support.STRUCTURAL, precondition_statuses=(PreconditionStatus.SATISFIED,)
    )
    assert result is Support.STRUCTURAL


def test_resolve_step_support_with_unknown_precondition_caps_below_structural():
    result = resolve_step_support(
        declared_support=Support.STRUCTURAL, precondition_statuses=(PreconditionStatus.UNKNOWN,)
    )
    assert result is Support.CONDITIONED


def test_resolve_step_support_with_unsatisfied_precondition_blocks_the_step():
    result = resolve_step_support(
        declared_support=Support.STRUCTURAL, precondition_statuses=(PreconditionStatus.UNSATISFIED,)
    )
    assert result is None


# --- 12. unknown nunca produce STRUCTURAL ------------------------------------


@pytest.mark.parametrize("declared", list(Support))
def test_unknown_precondition_never_yields_structural_support(declared):
    result = resolve_step_support(declared_support=declared, precondition_statuses=(PreconditionStatus.UNKNOWN,))
    assert result is not Support.STRUCTURAL


def test_step_result_rejects_structural_effective_support_with_unknown_precondition():
    result = _result(statuses=(PreconditionStatus.UNKNOWN,), declared=Support.STRUCTURAL)
    assert result.effective_support is not Support.STRUCTURAL


# --- 13. cadena hereda el soporte más débil (eslabón, no promedio) ----------


def test_chain_support_is_the_weakest_link_not_an_average():
    strong = _result("s1", statuses=(PreconditionStatus.SATISFIED,), declared=Support.STRUCTURAL)
    weak = _result("s2", statuses=(PreconditionStatus.UNKNOWN,), declared=Support.CONDITIONED)

    assert chain_support((strong, weak)) is Support.CONDITIONED
    assert chain_support((weak, strong)) is Support.CONDITIONED  # el orden no cambia el resultado


def test_chain_support_is_blocked_if_any_step_is_blocked():
    ok = _result("s1")
    blocked = _blocked_result("s2")

    assert chain_support((ok, blocked)) is None


# --- §A4: única fuente de verdad para el soporte ----------------------------


def test_step_result_effective_support_is_derived_never_a_free_input():
    fields = {f.name for f in dataclasses.fields(StepResult)}
    assert "declared_support" in fields
    assert "effective_support" in fields
    init_fields = {f.name for f in dataclasses.fields(StepResult) if f.init}
    assert "effective_support" not in init_fields  # no es un parámetro del constructor


def test_step_result_cannot_elevate_effective_support_manually():
    with pytest.raises(TypeError):
        StepResult(
            step_id="s1",
            precondition_results=_precondition_results((PreconditionStatus.UNKNOWN,)),
            declared_support=Support.STRUCTURAL,
            effective_support=Support.STRUCTURAL,  # type: ignore[call-arg]
        )


def test_step_result_effective_support_matches_resolve_step_support():
    statuses = (PreconditionStatus.UNKNOWN,)
    result = _result(statuses=statuses, declared=Support.STRUCTURAL)

    assert result.effective_support == resolve_step_support(
        declared_support=Support.STRUCTURAL, precondition_statuses=statuses
    )


def test_step_result_rejects_wrong_typed_declared_support():
    with pytest.raises(TypeError):
        StepResult(
            step_id="s1",
            precondition_results=_precondition_results((PreconditionStatus.SATISFIED,)),
            declared_support="structural",
        )  # type: ignore[arg-type]


# --- 14-17. grupo de exclusión mutua -----------------------------------------


def test_alternative_group_with_unique_alternatives():
    group = AlternativeGroup(group_id="g1", alternative_ids=("alt_a", "alt_b", "alt_c"))
    assert group.alternative_ids == ("alt_a", "alt_b", "alt_c")


def test_alternative_group_rejects_duplicate_alternative_ids():
    with pytest.raises(ValueError):
        AlternativeGroup(group_id="g1", alternative_ids=("alt_a", "alt_a"))


def test_alternative_group_valid_selection():
    group = AlternativeGroup(group_id="g1", alternative_ids=("alt_a", "alt_b"), selected_id="alt_b")
    assert group.selected_id == "alt_b"


def test_alternative_group_rejects_selection_outside_the_group():
    with pytest.raises(ValueError):
        AlternativeGroup(group_id="g1", alternative_ids=("alt_a", "alt_b"), selected_id="alt_z")


def test_alternative_group_cannot_represent_two_selected_alternatives():
    # la estructura misma lo impide: selected_id es un único campo, nunca
    # una colección — no existe forma de construir "dos seleccionadas".
    fields = {f.name for f in dataclasses.fields(AlternativeGroup)}
    assert "selected_id" in fields
    assert not any(f.name.endswith("_ids_selected") or f.name == "selected_ids" for f in dataclasses.fields(AlternativeGroup))


# --- 18. rama sin selección: condicional/irresuelta --------------------------


def test_alternative_group_without_selection_represents_conditional_or_unresolved():
    group = AlternativeGroup(group_id="g1", alternative_ids=("alt_a", "alt_b"))
    assert group.selected_id is None


# --- InteractionSequence.alternative_id: coherencia con su propio grupo ----


def test_interaction_sequence_alternative_id_must_belong_to_its_group():
    group = AlternativeGroup(group_id="g1", alternative_ids=("aa", "q"))
    seq = InteractionSequence(sequence_id="seq_aa", steps=(_step(),), alternative_group=group, alternative_id="aa")
    assert seq.alternative_id == "aa"

    with pytest.raises(ValueError):
        InteractionSequence(sequence_id="bad", steps=(_step(),), alternative_group=group, alternative_id="not_in_group")


def test_interaction_sequence_alternative_group_and_id_must_be_declared_together():
    group = AlternativeGroup(group_id="g1", alternative_ids=("aa", "q"))
    with pytest.raises(ValueError):
        InteractionSequence(sequence_id="bad", steps=(_step(),), alternative_group=group, alternative_id=None)
    with pytest.raises(ValueError):
        InteractionSequence(sequence_id="bad", steps=(_step(),), alternative_group=None, alternative_id="aa")


# --- 19. StateDelta conserva snapshots distintos sin mutarlos ---------------


def test_state_delta_preserves_distinct_snapshots_without_mutating_them():
    before = _combat_state(level=3)
    after = _combat_state(level=6)

    delta = StateDelta(before=before, after=after)

    assert delta.before.candidate.level == 3
    assert delta.after.candidate.level == 6
    assert delta.before is before
    assert delta.after is after
    # y los snapshots originales conservan su valor tras construir el delta
    assert before.candidate.level == 3
    assert after.candidate.level == 6


def test_state_delta_rejects_non_combat_state_arguments():
    with pytest.raises(TypeError):
        StateDelta(before="not a state", after=_combat_state())  # type: ignore[arg-type]


# --- 20-21. trade favorable/neutral sin muerte -------------------------------


def test_trade_favorable_without_death():
    delta = StateDelta(before=_combat_state(), after=_combat_state(level=6))
    outcome = TradeOutcome(state_delta=delta, evaluation=Evaluation.CANDIDATE_FAVORED)

    assert outcome.evaluation is Evaluation.CANDIDATE_FAVORED
    assert outcome.terminal_event.kind is TerminalEventKind.UNKNOWN  # default: no se afirma nada de más
    assert outcome.terminal_event.killed_actors == ()


def test_trade_neutral_without_death():
    delta = StateDelta(before=_combat_state(), after=_combat_state())
    outcome = TradeOutcome(
        state_delta=delta, evaluation=Evaluation.NEUTRAL, terminal_event=TerminalEvent(kind=TerminalEventKind.NONE)
    )

    assert outcome.evaluation is Evaluation.NEUTRAL
    assert outcome.terminal_event.kind is TerminalEventKind.NONE
    assert outcome.terminal_event.killed_actors == ()


def test_trade_conditional_and_unresolved_are_representable():
    delta = StateDelta(before=_combat_state(), after=_combat_state())
    conditional = TradeOutcome(state_delta=delta, evaluation=Evaluation.CONDITIONAL)
    unresolved = TradeOutcome(state_delta=delta, evaluation=Evaluation.UNRESOLVED)

    assert conditional.evaluation is Evaluation.CONDITIONAL
    assert unresolved.evaluation is Evaluation.UNRESOLVED


# --- 14-18 (A9 numbering, TerminalEvent): unknown/none/kill/ambos actores --


def test_terminal_event_unknown_has_no_killed_actors():
    event = TerminalEvent(kind=TerminalEventKind.UNKNOWN)
    assert event.killed_actors == ()


def test_terminal_event_none_has_no_killed_actors():
    event = TerminalEvent(kind=TerminalEventKind.NONE)
    assert event.killed_actors == ()


def test_kill_event_of_candidate():
    event = TerminalEvent(kind=TerminalEventKind.KILL, killed_actors=(ActorRole.CANDIDATE,))
    assert event.killed_actors == (ActorRole.CANDIDATE,)


def test_kill_event_of_enemy():
    event = TerminalEvent(kind=TerminalEventKind.KILL, killed_actors=(ActorRole.ENEMY,))
    assert event.killed_actors == (ActorRole.ENEMY,)


def test_kill_event_of_both_actors_is_valid():
    event = TerminalEvent(kind=TerminalEventKind.KILL, killed_actors=(ActorRole.CANDIDATE, ActorRole.ENEMY))
    assert set(event.killed_actors) == {ActorRole.CANDIDATE, ActorRole.ENEMY}


def test_kill_event_without_actors_is_rejected():
    with pytest.raises(ValueError):
        TerminalEvent(kind=TerminalEventKind.KILL, killed_actors=())


def test_kill_event_rejects_repeated_actor():
    with pytest.raises(ValueError):
        TerminalEvent(kind=TerminalEventKind.KILL, killed_actors=(ActorRole.CANDIDATE, ActorRole.CANDIDATE))


@pytest.mark.parametrize("kind", [TerminalEventKind.NONE, TerminalEventKind.UNKNOWN])
def test_none_or_unknown_event_with_actors_is_rejected(kind):
    with pytest.raises(ValueError):
        TerminalEvent(kind=kind, killed_actors=(ActorRole.CANDIDATE,))


def test_terminal_event_death_does_not_determine_evaluation():
    # una TerminalEvent con kill es independiente de qué Evaluation se
    # declare — nada en estos tipos deriva una de la otra automáticamente.
    delta = StateDelta(before=_combat_state(), after=_combat_state())
    kill_event = TerminalEvent(kind=TerminalEventKind.KILL, killed_actors=(ActorRole.ENEMY,))

    outcome_neutral = TradeOutcome(state_delta=delta, evaluation=Evaluation.NEUTRAL, terminal_event=kill_event)
    outcome_favored = TradeOutcome(state_delta=delta, evaluation=Evaluation.CANDIDATE_FAVORED, terminal_event=kill_event)

    assert outcome_neutral.terminal_event.killed_actors == (ActorRole.ENEMY,)
    assert outcome_favored.terminal_event.killed_actors == (ActorRole.ENEMY,)


def test_favorable_evaluation_can_exist_without_any_death():
    delta = StateDelta(before=_combat_state(), after=_combat_state(level=6))
    outcome = TradeOutcome(state_delta=delta, evaluation=Evaluation.CANDIDATE_FAVORED)
    assert outcome.terminal_event.kind is TerminalEventKind.UNKNOWN


# --- 25. outcome bloqueado sin componentes -----------------------------------


def test_blocked_outcome_has_no_causal_components():
    seq = InteractionSequence(sequence_id="seq", steps=(_step("s1"),))
    blocked_result = _blocked_result("s1")

    outcome = ScenarioOutcome(sequence=seq, step_results=(blocked_result,))

    assert outcome.support is None
    assert outcome.causal_components == ()


def test_blocked_outcome_rejects_explicit_causal_components():
    seq = InteractionSequence(sequence_id="seq", steps=(_step("s1"),))
    blocked_result = _blocked_result("s1")
    component = _causal_component("seq")

    with pytest.raises(ValueError):
        ScenarioOutcome(sequence=seq, step_results=(blocked_result,), causal_components=(component,))


def test_unresolved_branch_selection_rejects_causal_components():
    group = AlternativeGroup(group_id="g_followup", alternative_ids=("aa", "q"))
    seq = InteractionSequence(
        sequence_id="seq_q", steps=(_step("s1"),), alternative_group=group, alternative_id="q"
    )
    ok_result = _result("s1")
    unresolved_group = AlternativeGroup(group_id="g_followup", alternative_ids=("aa", "q"))
    component = _causal_component("seq_q")

    with pytest.raises(ValueError):
        ScenarioOutcome(
            sequence=seq,
            step_results=(ok_result,),
            branch_selection=unresolved_group,
            causal_components=(component,),
        )


# --- 26. outcome ambiguo sin Support.STRUCTURAL -----------------------------


def test_ambiguous_outcome_never_carries_structural_support():
    seq = InteractionSequence(sequence_id="seq", steps=(_step("s1"),))
    unknown_result = _result("s1", statuses=(PreconditionStatus.UNKNOWN,), declared=Support.AMBIGUOUS)

    outcome = ScenarioOutcome(sequence=seq, step_results=(unknown_result,))

    assert outcome.support is not Support.STRUCTURAL


# --- 27. neutral/conditional/irresuelto sin polaridad forzada ---------------


@pytest.mark.parametrize("evaluation", [Evaluation.NEUTRAL, Evaluation.CONDITIONAL, Evaluation.UNRESOLVED])
def test_unsigned_evaluations_reject_signed_causal_components(evaluation):
    seq = InteractionSequence(sequence_id="seq", steps=(_step("s1"),))
    ok_result = _result("s1")
    delta = StateDelta(before=_combat_state(), after=_combat_state())
    trade = TradeOutcome(state_delta=delta, evaluation=evaluation)
    signed_component = _causal_component("seq", polarity=Polarity.PRO)

    with pytest.raises(ValueError):
        ScenarioOutcome(sequence=seq, step_results=(ok_result,), trade_outcome=trade, causal_components=(signed_component,))


@pytest.mark.parametrize("evaluation", [Evaluation.CANDIDATE_FAVORED, Evaluation.ENEMY_FAVORED])
def test_favored_evaluations_accept_signed_causal_components(evaluation):
    seq = InteractionSequence(sequence_id="seq", steps=(_step("s1"),))
    ok_result = _result("s1")
    delta = StateDelta(before=_combat_state(), after=_combat_state())
    trade = TradeOutcome(state_delta=delta, evaluation=evaluation)
    signed_component = _causal_component("seq", polarity=Polarity.PRO)

    outcome = ScenarioOutcome(sequence=seq, step_results=(ok_result,), trade_outcome=trade, causal_components=(signed_component,))
    assert outcome.causal_components[0].polarity is Polarity.PRO


# --- 28. varios CausalComponent conservan factores y deltas separados ------


def test_multiple_causal_components_preserve_separate_factors_and_deltas():
    seq = InteractionSequence(sequence_id="seq", steps=(_step("s1"),))
    ok_result = _result("s1")
    delta = StateDelta(before=_combat_state(), after=_combat_state())
    trade = TradeOutcome(state_delta=delta, evaluation=Evaluation.CANDIDATE_FAVORED)

    component_a = CausalComponent(
        factor=Factor.MECHANICAL_INTERACTION,
        delta=2.0,
        provenance=Provenance.DERIVED,
        fact_ref="synthetic:q",
        sequence_id="seq",
        polarity=Polarity.PRO,
    )
    component_b = CausalComponent(
        factor=Factor.STACKING_PAYOFF,
        delta=0.5,
        provenance=Provenance.DERIVED,
        fact_ref="synthetic:passive",
        sequence_id="seq",
        polarity=Polarity.PRO,
    )

    outcome = ScenarioOutcome(
        sequence=seq, step_results=(ok_result,), trade_outcome=trade, causal_components=(component_a, component_b)
    )

    assert outcome.causal_components[0].factor is Factor.MECHANICAL_INTERACTION
    assert outcome.causal_components[0].delta == 2.0
    assert outcome.causal_components[1].factor is Factor.STACKING_PAYOFF
    assert outcome.causal_components[1].delta == 0.5
    # no se fusionaron: siguen siendo dos componentes distintos, no uno promedio
    assert len(outcome.causal_components) == 2


def test_causal_component_rejects_wrong_typed_delta():
    with pytest.raises(TypeError):
        CausalComponent(
            factor=Factor.MECHANICAL_INTERACTION,
            delta="2.0",  # type: ignore[arg-type]
            provenance=Provenance.DERIVED,
            fact_ref="synthetic:q",
            sequence_id="seq",
        )


def test_causal_component_rejects_bool_delta():
    with pytest.raises(TypeError):
        CausalComponent(
            factor=Factor.MECHANICAL_INTERACTION,
            delta=True,  # type: ignore[arg-type]
            provenance=Provenance.DERIVED,
            fact_ref="synthetic:q",
            sequence_id="seq",
        )


# --- ScenarioOutcome: no emite RuleEffect, no toca el score -----------------


def test_scenario_outcome_has_no_rule_effect_emission_surface():
    outcome_fields = {f.name for f in dataclasses.fields(ScenarioOutcome)}
    assert "rule_effects" not in outcome_fields
    assert "matchup_score" not in outcome_fields


# ---------------------------------------------------------------------------
# §A1 — StepResult debe formar un prefijo ordenado
# ---------------------------------------------------------------------------


def _three_step_sequence() -> InteractionSequence:
    return InteractionSequence(
        sequence_id="seq3", steps=(_step("paso_1"), _step("paso_2"), _step("paso_3"))
    )


def test_a1_full_ordered_prefix_is_valid():
    seq = _three_step_sequence()
    results = (_result("paso_1"), _result("paso_2"), _result("paso_3"))

    outcome = ScenarioOutcome(sequence=seq, step_results=results)

    assert outcome.progress is SequenceProgress.COMPLETED
    assert [r.step_id for r in outcome.step_results] == ["paso_1", "paso_2", "paso_3"]


def test_a1_partial_ordered_prefix_is_valid():
    seq = _three_step_sequence()
    results = (_result("paso_1"), _result("paso_2"))

    outcome = ScenarioOutcome(sequence=seq, step_results=results)

    assert outcome.progress is SequenceProgress.PARTIAL
    assert [r.step_id for r in outcome.step_results] == ["paso_1", "paso_2"]


def test_a1_skipping_first_step_is_rejected():
    seq = _three_step_sequence()
    with pytest.raises(ValueError):
        ScenarioOutcome(sequence=seq, step_results=(_result("paso_2"),))


def test_a1_out_of_order_result_is_rejected():
    seq = _three_step_sequence()
    with pytest.raises(ValueError):
        ScenarioOutcome(sequence=seq, step_results=(_result("paso_1"), _result("paso_3")))


def test_a1_reversed_order_is_rejected():
    seq = _three_step_sequence()
    with pytest.raises(ValueError):
        ScenarioOutcome(sequence=seq, step_results=(_result("paso_2"), _result("paso_1")))


def test_a1_result_after_blocked_step_is_rejected():
    seq = _three_step_sequence()
    with pytest.raises(ValueError):
        ScenarioOutcome(
            sequence=seq, step_results=(_result("paso_1"), _blocked_result("paso_2"), _result("paso_3"))
        )


def test_a1_completed_outcome_with_missing_steps_is_rejected_via_require_sequence_progress():
    seq = _three_step_sequence()
    partial = (_result("paso_1"), _result("paso_2"))

    with pytest.raises(ValueError):
        require_sequence_progress(sequence=seq, step_results=partial, expected=SequenceProgress.COMPLETED)

    # y el propio outcome jamás se autoetiqueta COMPLETED con pasos faltantes
    outcome = ScenarioOutcome(sequence=seq, step_results=partial)
    assert outcome.progress is not SequenceProgress.COMPLETED


def test_a1_step_result_not_belonging_to_sequence_is_rejected():
    seq = _three_step_sequence()
    foreign_result = _result("paso_ajeno")
    with pytest.raises(ValueError):
        ScenarioOutcome(sequence=seq, step_results=(foreign_result,))


def test_a1_repeated_step_result_is_rejected():
    seq = _three_step_sequence()
    with pytest.raises(ValueError):
        ScenarioOutcome(sequence=seq, step_results=(_result("paso_1"), _result("paso_1")))


def test_a1_not_started_progress_for_empty_step_results():
    seq = _three_step_sequence()
    assert sequence_progress(sequence=seq, step_results=()) is SequenceProgress.NOT_STARTED

    outcome = ScenarioOutcome(sequence=seq, step_results=())
    assert outcome.progress is SequenceProgress.NOT_STARTED
    assert outcome.support is None


def test_a1_blocked_progress_even_when_length_matches_total_steps():
    # bloqueada en el último paso: no es "completada" pese a tener la
    # misma cantidad de resultados que pasos tiene la secuencia.
    seq = InteractionSequence(sequence_id="seq2", steps=(_step("paso_1"), _step("paso_2")))
    results = (_result("paso_1"), _blocked_result("paso_2"))

    outcome = ScenarioOutcome(sequence=seq, step_results=results)

    assert outcome.progress is SequenceProgress.BLOCKED
    assert outcome.support is None


# ---------------------------------------------------------------------------
# §A2 — Coherencia entre secuencia y selección de rama
# ---------------------------------------------------------------------------


def _followup_group() -> AlternativeGroup:
    return AlternativeGroup(group_id="g_followup", alternative_ids=("aa", "q"))


def _followup_sequence(alternative_id: str, *, sequence_id: str | None = None) -> InteractionSequence:
    return InteractionSequence(
        sequence_id=sequence_id or f"seq_{alternative_id}",
        steps=(_step("s1"),),
        alternative_group=_followup_group(),
        alternative_id=alternative_id,
    )


def test_a2_matching_branch_selection_allows_causal_components():
    seq_q = _followup_sequence("q")
    selection = AlternativeGroup(group_id="g_followup", alternative_ids=("aa", "q"), selected_id="q")
    component = _causal_component(seq_q.sequence_id)

    outcome = ScenarioOutcome(
        sequence=seq_q, step_results=(_result("s1"),), branch_selection=selection, causal_components=(component,)
    )

    assert outcome.causal_components == (component,)


def test_a2_selection_of_a_different_alternative_is_rejected():
    seq_q = _followup_sequence("q")
    selection_of_aa = AlternativeGroup(group_id="g_followup", alternative_ids=("aa", "q"), selected_id="aa")
    component = _causal_component(seq_q.sequence_id)

    with pytest.raises(ValueError):
        ScenarioOutcome(
            sequence=seq_q,
            step_results=(_result("s1"),),
            branch_selection=selection_of_aa,
            causal_components=(component,),
        )


def test_a2_wrong_group_id_is_rejected():
    seq_q = _followup_sequence("q")
    wrong_group_selection = AlternativeGroup(group_id="OTHER_GROUP", alternative_ids=("aa", "q"), selected_id="q")

    with pytest.raises(ValueError):
        ScenarioOutcome(sequence=seq_q, step_results=(_result("s1"),), branch_selection=wrong_group_selection)


def test_a2_ungrouped_sequence_with_foreign_selection_is_rejected():
    ungrouped = InteractionSequence(sequence_id="seq_solo", steps=(_step("s1"),))
    foreign_selection = _followup_group()

    with pytest.raises(ValueError):
        ScenarioOutcome(sequence=ungrouped, step_results=(_result("s1"),), branch_selection=foreign_selection)


def test_a2_unresolved_branch_has_no_causal_components():
    seq_q = _followup_sequence("q")
    unresolved_selection = _followup_group()  # selected_id=None

    outcome = ScenarioOutcome(sequence=seq_q, step_results=(_result("s1"),), branch_selection=unresolved_selection)

    assert outcome.causal_components == ()


def test_a2_missing_branch_selection_for_grouped_sequence_forbids_components():
    seq_q = _followup_sequence("q")
    component = _causal_component(seq_q.sequence_id)

    with pytest.raises(ValueError):
        ScenarioOutcome(sequence=seq_q, step_results=(_result("s1"),), causal_components=(component,))


# --- 29 (A9 numbering, tests obligatorios de secuencia): ambas ramas no activas simultáneamente


def test_a2_both_alternatives_cannot_be_active_in_the_same_outcome():
    # cada ScenarioOutcome representa UNA secuencia (una alternativa) — no
    # existe forma estructural de sumar aa+q en un mismo outcome porque
    # `sequence` es un único campo, nunca una colección de alternativas.
    fields = {f.name for f in dataclasses.fields(ScenarioOutcome)}
    assert "sequence" in fields
    assert "sequences" not in fields
    assert "alternatives" not in fields


# ---------------------------------------------------------------------------
# §A6 — Serialización de los tipos de secuencia
# ---------------------------------------------------------------------------


def _full_outcome_for_serialization() -> ScenarioOutcome:
    seq_q = _followup_sequence("q")
    selection = AlternativeGroup(group_id="g_followup", alternative_ids=("aa", "q"), selected_id="q")
    delta = StateDelta(before=_combat_state(level=3), after=_combat_state(level=6))
    trade = TradeOutcome(
        state_delta=delta,
        evaluation=Evaluation.CANDIDATE_FAVORED,
        terminal_event=TerminalEvent(kind=TerminalEventKind.KILL, killed_actors=(ActorRole.ENEMY,)),
    )
    component = _causal_component(seq_q.sequence_id, polarity=Polarity.PRO)
    return ScenarioOutcome(
        sequence=seq_q,
        step_results=(_result("s1"),),
        branch_selection=selection,
        trade_outcome=trade,
        causal_components=(component,),
    )


def test_a6_scenario_outcome_serializes_fully_to_json():
    outcome = _full_outcome_for_serialization()
    primitive = scenario_outcome_to_primitive(outcome)

    serialized = json.dumps(primitive)
    assert json.loads(serialized) == primitive


def test_a6_serialization_is_deterministic():
    outcome_a = _full_outcome_for_serialization()
    outcome_b = _full_outcome_for_serialization()

    assert scenario_outcome_to_primitive(outcome_a) == scenario_outcome_to_primitive(outcome_b)


def test_a6_mutating_serialized_result_does_not_affect_original_types():
    outcome = _full_outcome_for_serialization()
    primitive = scenario_outcome_to_primitive(outcome)

    primitive["step_results"][0]["declared_support"] = "mutated"
    primitive["causal_components"][0]["delta"] = 999.0
    del primitive["sequence"]["steps"][0]

    assert outcome.step_results[0].declared_support is Support.STRUCTURAL
    assert outcome.causal_components[0].delta == 1.0
    assert len(outcome.sequence.steps) == 1


def test_a6_serialization_uses_only_json_primitive_types():
    def _assert_all_primitive(node):
        if isinstance(node, dict):
            for key, value in node.items():
                assert isinstance(key, str)
                _assert_all_primitive(value)
        elif isinstance(node, list):
            for item in node:
                _assert_all_primitive(item)
        else:
            assert node is None or isinstance(node, (str, int, float, bool))

    _assert_all_primitive(scenario_outcome_to_primitive(_full_outcome_for_serialization()))


def test_a6_state_delta_serialization_reuses_combat_state_to_primitive():
    outcome = _full_outcome_for_serialization()
    primitive = scenario_outcome_to_primitive(outcome)

    before = primitive["trade_outcome"]["state_delta"]["before"]
    after = primitive["trade_outcome"]["state_delta"]["after"]
    assert before["candidate"]["level"] == 3
    assert after["candidate"]["level"] == 6


def test_a6_sequence_to_primitive_covers_causes_order_is_deterministic():
    id_a = _identity(component="a")
    id_b = _identity(component="b")
    seq = InteractionSequence(
        sequence_id="seq", steps=(_step("s1", consumes=(id_a, id_b)),)
    )

    first = sequence_to_primitive(seq)["covers_causes"]
    second = sequence_to_primitive(seq)["covers_causes"]
    assert first == second
    assert first == sorted(first, key=lambda item: (item["fact_ref"], item["causal_role"], item["component"]))


def test_a6_enums_serialize_to_their_string_values():
    outcome = _full_outcome_for_serialization()
    primitive = scenario_outcome_to_primitive(outcome)

    assert primitive["progress"] == "completed"
    assert primitive["support"] == "structural"
    assert primitive["trade_outcome"]["evaluation"] == "candidate_favored"
    assert primitive["trade_outcome"]["terminal_event"]["kind"] == "kill"
    assert primitive["trade_outcome"]["terminal_event"]["killed_actors"] == ["enemy"]


# --- 29. ningún tipo contiene nombres de campeón/mecánica concreta ----------

_FORBIDDEN_SUBSTRINGS = (
    "darius",
    "mordekaiser",
    "hemorrhage",
    "decimate",
    "apprehend",
    "guillotine",
    "indestructible",
    "darkness_rise",
    "obliterate",
)


def _all_declared_names(*types: type) -> set[str]:
    names: set[str] = set()
    for t in types:
        names.add(t.__name__)
        if issubclass(t, Enum):
            for member in t:
                names.add(member.name)
                names.add(str(member.value))
        if dataclasses.is_dataclass(t):
            for f in dataclasses.fields(t):
                names.add(f.name)
    return names


def test_no_champion_or_ability_specific_names_anywhere_in_the_sequence_model():
    types = (
        ActorRole,
        AlternativeGroup,
        CausalComponent,
        EffectIdentity,
        Evaluation,
        InteractionSequence,
        PreconditionStatus,
        ScenarioOutcome,
        SequenceProgress,
        SequenceStep,
        StateDelta,
        StepResult,
        TerminalEvent,
        TerminalEventKind,
        TradeOutcome,
    )
    declared = {name.lower() for name in _all_declared_names(*types)}

    offending = {forbidden for forbidden in _FORBIDDEN_SUBSTRINGS for name in declared if forbidden in name}
    assert not offending, f"nombres específicos de campeón/habilidad filtrados al modelo genérico: {offending}"


# --- 30. ningún test congela un ganador ni un score exacto -------------------
#
# (verificación estructural de este propio archivo: ningún assert compara
# contra un GlobalScore/PersonalScore ni un ganador de matchup — todos los
# asserts de arriba comparan tipos/estructura/enums de este módulo, nunca
# un resultado de scoring importado de otro lado)


def test_this_file_never_imports_scoring_or_matchup_result_types():
    import ast
    from pathlib import Path

    source = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert not any("scoring" in module or "result" in module for module in imported_modules)


# ---------------------------------------------------------------------------
# Cierre de hardening — fuente canónica única de pre/postcondiciones (§A2)
# ---------------------------------------------------------------------------


def test_sequence_step_serializes_its_real_typed_preconditions_and_postconditions():
    # Ningún SequenceStep de esta ronda declara preconditions/postconditions
    # como texto libre vacío mientras la lógica real vive escondida en otro
    # tipo — lo que se serializa es EXACTAMENTE lo que evaluator.py evalúa.
    precondition = _synthetic_precondition("candidate:ref")
    from lol_reasoner.reasoning.sequences.steps import PostconditionEffectKind, StructuralPostcondition

    postcondition = StructuralPostcondition(PostconditionEffectKind.ABILITY_ON_COOLDOWN, ActorRole.CANDIDATE, "slot")
    step = SequenceStep(
        step_id="s1",
        action_ref="candidate:q",
        actor=ActorRole.CANDIDATE,
        declared_support=Support.STRUCTURAL,
        preconditions=(precondition,),
        postconditions=(postcondition,),
    )
    seq = InteractionSequence(sequence_id="seq", steps=(step,))

    primitive = sequence_to_primitive(seq)["steps"][0]

    assert primitive["preconditions"] != []
    assert primitive["preconditions"][0]["kind"] == "action_connects"
    assert primitive["preconditions"][0]["actor"] == "candidate"
    assert primitive["preconditions"][0]["reference"] == "candidate:ref"
    assert primitive["postconditions"] != []
    assert primitive["postconditions"][0]["kind"] == "ability_on_cooldown"
    assert primitive["declared_support"] == "structural"


def test_step_without_declared_preconditions_serializes_a_genuinely_empty_list():
    # El contraste con el test anterior: un paso que DE VERDAD no declara
    # precondiciones serializa una lista vacía real — nunca se infla con
    # datos inventados, y nunca se confunde con el caso de arriba (donde SÍ
    # había precondiciones y antes se perdían).
    step = _step("s1")
    seq = InteractionSequence(sequence_id="seq", steps=(step,))

    primitive = sequence_to_primitive(seq)["steps"][0]
    assert primitive["preconditions"] == []
    assert primitive["postconditions"] == []


# ---------------------------------------------------------------------------
# Cierre de hardening — cada status serializado identifica su condición (§A2)
# ---------------------------------------------------------------------------


def test_serialized_precondition_result_identifies_its_condition():
    precondition = _synthetic_precondition("candidate:ref_x")
    result = StepResult(
        step_id="s1",
        precondition_results=(PreconditionResult(precondition=precondition, status=PreconditionStatus.UNSATISFIED),),
        declared_support=Support.STRUCTURAL,
    )
    seq = InteractionSequence(sequence_id="seq", steps=(_step("s1"),))
    outcome = ScenarioOutcome(sequence=seq, step_results=(result,))

    primitive = scenario_outcome_to_primitive(outcome)
    serialized_precondition_result = primitive["step_results"][0]["precondition_results"][0]

    assert serialized_precondition_result["precondition"]["kind"] == "action_connects"
    assert serialized_precondition_result["precondition"]["actor"] == "candidate"
    assert serialized_precondition_result["precondition"]["reference"] == "candidate:ref_x"
    assert serialized_precondition_result["status"] == "unsatisfied"


def test_serialization_never_uses_a_bare_status_list_without_condition_identity():
    outcome = _full_outcome_for_serialization()
    primitive = scenario_outcome_to_primitive(outcome)
    step_result_primitive = primitive["step_results"][0]

    assert "precondition_statuses" not in step_result_primitive  # el campo viejo ya no existe
    assert "precondition_results" in step_result_primitive
    for entry in step_result_primitive["precondition_results"]:
        assert "precondition" in entry and "status" in entry


# ---------------------------------------------------------------------------
# Cierre de hardening — herencia de incertidumbre visible en StepResult (§A3)
# ---------------------------------------------------------------------------


def test_step_result_exposes_own_and_inherited_execution_status_separately():
    result = _result("s1", statuses=(PreconditionStatus.SATISFIED,), inherited=ExecutionStatus.HYPOTHETICAL)

    assert result.own_execution_status is ExecutionStatus.CONFIRMED
    assert result.inherited_execution_status is ExecutionStatus.HYPOTHETICAL
    # el eslabón más débil entre ambos gana: no puede figurar como ejecución
    # efectivamente confirmada dependiendo de un estado producido hipotéticamente
    assert result.execution_status is ExecutionStatus.HYPOTHETICAL
    assert result.effective_support is not Support.STRUCTURAL


def test_step_result_rejects_blocked_as_an_inherited_execution_status():
    with pytest.raises(ValueError):
        StepResult(
            step_id="s1",
            precondition_results=_precondition_results((PreconditionStatus.SATISFIED,)),
            declared_support=Support.STRUCTURAL,
            inherited_execution_status=ExecutionStatus.BLOCKED,
        )


def test_serialized_step_result_exposes_all_three_execution_status_layers():
    result = _result("s1", statuses=(PreconditionStatus.SATISFIED,), inherited=ExecutionStatus.HYPOTHETICAL)
    seq = InteractionSequence(sequence_id="seq", steps=(_step("s1"),))
    outcome = ScenarioOutcome(sequence=seq, step_results=(result,))

    primitive = scenario_outcome_to_primitive(outcome)["step_results"][0]

    assert primitive["own_execution_status"] == "confirmed"
    assert primitive["inherited_execution_status"] == "hypothetical"
    assert primitive["execution_status"] == "hypothetical"


def test_chain_execution_status_still_works_with_inherited_results():
    strong = _result("s1", statuses=(PreconditionStatus.SATISFIED,), inherited=ExecutionStatus.CONFIRMED)
    inherited_weak = _result("s2", statuses=(PreconditionStatus.SATISFIED,), inherited=ExecutionStatus.HYPOTHETICAL)

    assert chain_execution_status((strong, inherited_weak)) is ExecutionStatus.HYPOTHETICAL
