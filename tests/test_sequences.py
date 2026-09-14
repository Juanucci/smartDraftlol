"""Tests de los tipos de secuencia y resultado (v1.7, Etapa 2).

Cubren únicamente `reasoning/sequences/{steps,sequence}.py`: identidad
mecánica estructural, el contrato declarativo de un paso, soporte de una
cadena (satisfecha/desconocida/no satisfecha, eslabón más débil), grupos
de exclusión mutua, el contrato no binario de un trade, y el resultado
agregado de un escenario. Todo con actores/habilidades/mecánicas
SINTÉTICAS — nada de esto es Darius, Mordekaiser, ni ningún campeón real.
No hay motor de transición, generador de escenarios, scoring ni
integración con `RuleEngine`/`ReasoningTrace` en este archivo — esa es una
etapa distinta. Ningún test de este archivo congela un ganador ni un
score exacto.
"""

from __future__ import annotations

import dataclasses
from enum import Enum

import pytest

from lol_reasoner.domain.combat_state import ActorState, CombatState
from lol_reasoner.domain.enums import Factor, Polarity, Provenance, Support
from lol_reasoner.reasoning.sequences import (
    ActorRole,
    AlternativeGroup,
    CausalComponent,
    EffectIdentity,
    Evaluation,
    InteractionSequence,
    PreconditionStatus,
    ScenarioOutcome,
    SequenceStep,
    StateDelta,
    StepResult,
    TerminalEvent,
    TerminalEventKind,
    TradeOutcome,
    chain_support,
    resolve_step_support,
)

# --- fixtures sintéticas -----------------------------------------------------


def _identity(component: str = "whole", causal_role: str = "damage", fact_ref: str = "synthetic:q") -> EffectIdentity:
    return EffectIdentity(fact_ref=fact_ref, causal_role=causal_role, component=component)


def _step(step_id: str = "s1", *, consumes: tuple[EffectIdentity, ...] = ()) -> SequenceStep:
    return SequenceStep(step_id=step_id, action_ref="candidate:q", actor=ActorRole.CANDIDATE, consumes=consumes)


def _combat_state(level: int | None = None) -> CombatState:
    return CombatState(candidate=ActorState(level=level), enemy=ActorState())


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
        EffectIdentity(fact_ref=bad_value, causal_role="damage", component="whole")


def test_sequence_step_rejects_empty_step_id():
    with pytest.raises(ValueError):
        SequenceStep(step_id="   ", action_ref="candidate:q", actor=ActorRole.CANDIDATE)


def test_sequence_step_rejects_wrong_typed_actor():
    with pytest.raises(TypeError):
        SequenceStep(step_id="s1", action_ref="candidate:q", actor="candidate")  # type: ignore[arg-type]


def test_interaction_sequence_rejects_empty_sequence_id():
    with pytest.raises(ValueError):
        InteractionSequence(sequence_id="   ", steps=(_step(),))


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
        SequenceStep(step_id="s1", action_ref="candidate:q", actor=ActorRole.CANDIDATE, consumes=(identity, identity))


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


def test_step_result_rejects_structural_support_with_unknown_precondition():
    with pytest.raises(ValueError):
        StepResult(step_id="s1", precondition_statuses=(PreconditionStatus.UNKNOWN,), support=Support.STRUCTURAL)


# --- 13. cadena hereda el soporte más débil (eslabón, no promedio) ----------


def test_chain_support_is_the_weakest_link_not_an_average():
    strong = StepResult(step_id="s1", precondition_statuses=(PreconditionStatus.SATISFIED,), support=Support.STRUCTURAL)
    weak = StepResult(step_id="s2", precondition_statuses=(PreconditionStatus.UNKNOWN,), support=Support.CONDITIONED)

    assert chain_support((strong, weak)) is Support.CONDITIONED
    assert chain_support((weak, strong)) is Support.CONDITIONED  # el orden no cambia el resultado


def test_chain_support_is_blocked_if_any_step_is_blocked():
    ok = StepResult(step_id="s1", precondition_statuses=(PreconditionStatus.SATISFIED,), support=Support.STRUCTURAL)
    blocked = StepResult(step_id="s2", precondition_statuses=(PreconditionStatus.UNSATISFIED,), support=None)

    assert chain_support((ok, blocked)) is None


def test_step_result_blocked_cannot_declare_support():
    with pytest.raises(ValueError):
        StepResult(step_id="s1", precondition_statuses=(PreconditionStatus.UNSATISFIED,), support=Support.CONDITIONED)


def test_step_result_not_blocked_must_declare_a_real_support():
    with pytest.raises(ValueError):
        StepResult(step_id="s1", precondition_statuses=(PreconditionStatus.SATISFIED,), support=None)


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


def test_trade_neutral_without_death():
    delta = StateDelta(before=_combat_state(), after=_combat_state())
    outcome = TradeOutcome(
        state_delta=delta, evaluation=Evaluation.NEUTRAL, terminal_event=TerminalEvent(kind=TerminalEventKind.NONE)
    )

    assert outcome.evaluation is Evaluation.NEUTRAL
    assert outcome.terminal_event.kind is TerminalEventKind.NONE
    assert outcome.terminal_event.actor is None


def test_trade_conditional_and_unresolved_are_representable():
    delta = StateDelta(before=_combat_state(), after=_combat_state())
    conditional = TradeOutcome(state_delta=delta, evaluation=Evaluation.CONDITIONAL)
    unresolved = TradeOutcome(state_delta=delta, evaluation=Evaluation.UNRESOLVED)

    assert conditional.evaluation is Evaluation.CONDITIONAL
    assert unresolved.evaluation is Evaluation.UNRESOLVED


# --- 22-24. evento terminal ---------------------------------------------------


def test_kill_event_with_valid_actor():
    event = TerminalEvent(kind=TerminalEventKind.KILL, actor=ActorRole.ENEMY)
    assert event.actor is ActorRole.ENEMY


def test_kill_event_without_actor_is_rejected():
    with pytest.raises(ValueError):
        TerminalEvent(kind=TerminalEventKind.KILL, actor=None)


@pytest.mark.parametrize("kind", [TerminalEventKind.NONE, TerminalEventKind.UNKNOWN])
def test_none_or_unknown_event_with_actor_is_rejected(kind):
    with pytest.raises(ValueError):
        TerminalEvent(kind=kind, actor=ActorRole.CANDIDATE)


# --- 25. outcome bloqueado sin componentes -----------------------------------


def test_blocked_outcome_has_no_causal_components():
    step = _step("s1")
    seq = InteractionSequence(sequence_id="seq", steps=(step,))
    blocked_result = StepResult(step_id="s1", precondition_statuses=(PreconditionStatus.UNSATISFIED,), support=None)

    outcome = ScenarioOutcome(sequence=seq, step_results=(blocked_result,))

    assert outcome.support is None
    assert outcome.causal_components == ()


def test_blocked_outcome_rejects_explicit_causal_components():
    step = _step("s1")
    seq = InteractionSequence(sequence_id="seq", steps=(step,))
    blocked_result = StepResult(step_id="s1", precondition_statuses=(PreconditionStatus.UNSATISFIED,), support=None)
    component = CausalComponent(
        factor=Factor.MECHANICAL_INTERACTION,
        delta=1.0,
        provenance=Provenance.DERIVED,
        fact_ref="synthetic:q",
        sequence_id="seq",
    )

    with pytest.raises(ValueError):
        ScenarioOutcome(sequence=seq, step_results=(blocked_result,), causal_components=(component,))


def test_unresolved_branch_selection_rejects_causal_components():
    step = _step("s1")
    seq = InteractionSequence(sequence_id="seq", steps=(step,))
    ok_result = StepResult(step_id="s1", precondition_statuses=(PreconditionStatus.SATISFIED,), support=Support.STRUCTURAL)
    unresolved_group = AlternativeGroup(group_id="g", alternative_ids=("alt_a", "alt_b"))
    component = CausalComponent(
        factor=Factor.MECHANICAL_INTERACTION,
        delta=1.0,
        provenance=Provenance.DERIVED,
        fact_ref="synthetic:q",
        sequence_id="seq",
    )

    with pytest.raises(ValueError):
        ScenarioOutcome(
            sequence=seq,
            step_results=(ok_result,),
            branch_selection=unresolved_group,
            causal_components=(component,),
        )


# --- 26. outcome ambiguo sin Support.STRUCTURAL -----------------------------


def test_ambiguous_outcome_never_carries_structural_support():
    step = _step("s1")
    seq = InteractionSequence(sequence_id="seq", steps=(step,))
    unknown_result = StepResult(step_id="s1", precondition_statuses=(PreconditionStatus.UNKNOWN,), support=Support.AMBIGUOUS)

    outcome = ScenarioOutcome(sequence=seq, step_results=(unknown_result,))

    assert outcome.support is not Support.STRUCTURAL


# --- 27. neutral/conditional/irresuelto sin polaridad forzada ---------------


@pytest.mark.parametrize("evaluation", [Evaluation.NEUTRAL, Evaluation.CONDITIONAL, Evaluation.UNRESOLVED])
def test_unsigned_evaluations_reject_signed_causal_components(evaluation):
    step = _step("s1")
    seq = InteractionSequence(sequence_id="seq", steps=(step,))
    ok_result = StepResult(step_id="s1", precondition_statuses=(PreconditionStatus.SATISFIED,), support=Support.STRUCTURAL)
    delta = StateDelta(before=_combat_state(), after=_combat_state())
    trade = TradeOutcome(state_delta=delta, evaluation=evaluation)
    signed_component = CausalComponent(
        factor=Factor.MECHANICAL_INTERACTION,
        delta=1.0,
        provenance=Provenance.DERIVED,
        fact_ref="synthetic:q",
        sequence_id="seq",
        polarity=Polarity.PRO,
    )

    with pytest.raises(ValueError):
        ScenarioOutcome(sequence=seq, step_results=(ok_result,), trade_outcome=trade, causal_components=(signed_component,))


@pytest.mark.parametrize("evaluation", [Evaluation.CANDIDATE_FAVORED, Evaluation.ENEMY_FAVORED])
def test_favored_evaluations_accept_signed_causal_components(evaluation):
    step = _step("s1")
    seq = InteractionSequence(sequence_id="seq", steps=(step,))
    ok_result = StepResult(step_id="s1", precondition_statuses=(PreconditionStatus.SATISFIED,), support=Support.STRUCTURAL)
    delta = StateDelta(before=_combat_state(), after=_combat_state())
    trade = TradeOutcome(state_delta=delta, evaluation=evaluation)
    signed_component = CausalComponent(
        factor=Factor.MECHANICAL_INTERACTION,
        delta=1.0,
        provenance=Provenance.DERIVED,
        fact_ref="synthetic:q",
        sequence_id="seq",
        polarity=Polarity.PRO,
    )

    outcome = ScenarioOutcome(sequence=seq, step_results=(ok_result,), trade_outcome=trade, causal_components=(signed_component,))
    assert outcome.causal_components[0].polarity is Polarity.PRO


# --- 28. varios CausalComponent conservan factores y deltas separados ------


def test_multiple_causal_components_preserve_separate_factors_and_deltas():
    step = _step("s1")
    seq = InteractionSequence(sequence_id="seq", steps=(step,))
    ok_result = StepResult(step_id="s1", precondition_statuses=(PreconditionStatus.SATISFIED,), support=Support.STRUCTURAL)
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
