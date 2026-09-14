"""Tests del evaluador genérico de pasos de secuencia (v1.7 — cierre de
hardening, seguridad de estados proyectados).

Cubren únicamente `reasoning/sequences/evaluator.py`: `StepTransition`
(el par resultado/estado donde `state=None` es SIEMPRE y ÚNICAMENTE el
caso BLOCKED), `evaluate_step` (confirmado produce estado confirmado,
hipotético produce una proyección, bloqueado no aplica postcondiciones),
y `evaluate_sequence_prefix` (herencia de incertidumbre enhebrada paso a
paso, prefijo ordenado preservado hasta el primer bloqueo). Todo con
actores/habilidades/mecánicas SINTÉTICAS — nada de esto es Darius,
Mordekaiser, ni ningún campeón real."""

from __future__ import annotations

import pytest

from lol_reasoner.domain.combat_state import (
    AbilityAvailability,
    AbilityState,
    ActionContext,
    ActorState,
    CombatState,
    RangeStatus,
    SharedContext,
    StackState,
    StackWindow,
)
from lol_reasoner.domain.enums import Support
from lol_reasoner.reasoning.sequences.evaluator import StepTransition, evaluate_sequence_prefix, evaluate_step
from lol_reasoner.reasoning.sequences.sequence import ExecutionStatus
from lol_reasoner.reasoning.sequences.steps import (
    ActorRole,
    EffectIdentity,
    PostconditionEffectKind,
    PreconditionCheckKind,
    SequenceStep,
    StructuralPostcondition,
    StructuralPrecondition,
    WHOLE_EFFECT_COMPONENT,
)

# --- fixtures sintéticas -----------------------------------------------------

_ACTION_REF = "candidate:synthetic_action"
_ABILITY_SLOT = "synthetic_slot"
_STACK_REF = "synthetic_stack"


def _identity(component: str = WHOLE_EFFECT_COMPONENT) -> EffectIdentity:
    return EffectIdentity(fact_ref="synthetic:action", causal_role="damage", component=component)


def _step_with_action_connects_precondition(
    *, ability_ready_too: bool = False
) -> SequenceStep:
    preconditions = [StructuralPrecondition(PreconditionCheckKind.ACTION_CONNECTS, ActorRole.CANDIDATE, _ACTION_REF)]
    if ability_ready_too:
        preconditions.append(
            StructuralPrecondition(PreconditionCheckKind.ABILITY_READY, ActorRole.CANDIDATE, _ABILITY_SLOT)
        )
    return SequenceStep(
        step_id="s1",
        action_ref=_ACTION_REF,
        actor=ActorRole.CANDIDATE,
        declared_support=Support.STRUCTURAL,
        preconditions=tuple(preconditions),
        consumes=(_identity(),),
        postconditions=(StructuralPostcondition(PostconditionEffectKind.STACK_APPLIED, ActorRole.CANDIDATE, _STACK_REF),),
    )


def _state_with_range_status(range_status: RangeStatus) -> CombatState:
    return CombatState(
        candidate=ActorState(
            abilities={_ABILITY_SLOT: AbilityState(rank=1, availability=AbilityAvailability.READY)},
            stacks={_STACK_REF: StackState(count=0, window=StackWindow.UNKNOWN)},
        ),
        enemy=ActorState(),
        shared=SharedContext(action_contexts={_ACTION_REF: ActionContext(action_ref=_ACTION_REF, range_status=range_status)}),
    )


# ---------------------------------------------------------------------------
# StepTransition: state=None es SIEMPRE y ÚNICAMENTE el caso BLOCKED
# ---------------------------------------------------------------------------


def test_confirmed_step_produces_a_confirmed_transition_with_state():
    step = _step_with_action_connects_precondition()
    state = _state_with_range_status(RangeStatus.IN_RANGE)

    transition = evaluate_step(step, state)

    assert isinstance(transition, StepTransition)
    assert transition.result.execution_status is ExecutionStatus.CONFIRMED
    assert transition.state is not None
    assert transition.state.candidate.stacks[_STACK_REF].count == 1


def test_hypothetical_step_produces_a_projection_not_none():
    step = _step_with_action_connects_precondition()
    state = _state_with_range_status(RangeStatus.UNKNOWN)

    transition = evaluate_step(step, state)

    assert transition.result.execution_status is ExecutionStatus.HYPOTHETICAL
    assert transition.state is not None  # se aplicó la postcondición: es una PROYECCIÓN, no None
    assert transition.state.candidate.stacks[_STACK_REF].count == 1


def test_blocked_step_does_not_apply_its_own_postconditions():
    step = _step_with_action_connects_precondition()
    state = _state_with_range_status(RangeStatus.OUT_OF_RANGE)

    transition = evaluate_step(step, state)

    assert transition.result.execution_status is ExecutionStatus.BLOCKED
    assert transition.state is None
    # y el CombatState de entrada permanece sin la aplicación de stack
    assert state.candidate.stacks[_STACK_REF].count == 0


def test_step_transition_rejects_a_state_alongside_a_blocked_result():
    step = _step_with_action_connects_precondition()
    state = _state_with_range_status(RangeStatus.OUT_OF_RANGE)
    blocked_result, _ = evaluate_step(step, state).result, None

    with pytest.raises(ValueError):
        StepTransition(result=blocked_result, state=state)


def test_step_transition_rejects_none_state_for_a_non_blocked_result():
    step = _step_with_action_connects_precondition()
    state = _state_with_range_status(RangeStatus.IN_RANGE)
    confirmed_result = evaluate_step(step, state).result

    with pytest.raises(ValueError):
        StepTransition(result=confirmed_result, state=None)


# ---------------------------------------------------------------------------
# evaluate_sequence_prefix: herencia de incertidumbre enhebrada
# ---------------------------------------------------------------------------


def _two_step_sequence() -> tuple[SequenceStep, SequenceStep]:
    step_1 = _step_with_action_connects_precondition()
    step_2 = SequenceStep(
        step_id="s2",
        action_ref=_ACTION_REF,
        actor=ActorRole.CANDIDATE,
        declared_support=Support.STRUCTURAL,
        preconditions=(),  # sin precondiciones PROPIAS: satisfecho por sí mismo
        consumes=(_identity(component="second"),),
    )
    return step_1, step_2


def test_step_confirmed_by_itself_inherits_hypothetical_from_a_projected_predecessor():
    step_1, step_2 = _two_step_sequence()
    state = _state_with_range_status(RangeStatus.UNKNOWN)  # step_1 queda HYPOTHETICAL

    results, _ = evaluate_sequence_prefix((step_1, step_2), state)

    assert results[0].execution_status is ExecutionStatus.HYPOTHETICAL
    # step_2 no tiene precondiciones propias (todas SATISFIED por vacuidad)
    # pero NO puede figurar como CONFIRMED: heredó la incertidumbre de step_1.
    assert results[1].own_execution_status is ExecutionStatus.CONFIRMED
    assert results[1].inherited_execution_status is ExecutionStatus.HYPOTHETICAL
    assert results[1].execution_status is ExecutionStatus.HYPOTHETICAL


def test_first_step_of_a_sequence_always_inherits_confirmed():
    step_1, _ = _two_step_sequence()
    state = _state_with_range_status(RangeStatus.IN_RANGE)

    results, _ = evaluate_sequence_prefix((step_1,), state)

    assert results[0].inherited_execution_status is ExecutionStatus.CONFIRMED


def test_confirmed_chain_keeps_every_step_confirmed():
    step_1, step_2 = _two_step_sequence()
    state = _state_with_range_status(RangeStatus.IN_RANGE)

    results, _ = evaluate_sequence_prefix((step_1, step_2), state)

    assert all(result.execution_status is ExecutionStatus.CONFIRMED for result in results)


def test_prefix_before_a_block_is_preserved_with_correct_semantics():
    step_1 = _step_with_action_connects_precondition()
    # una segunda referencia que SÍ bloquea explícitamente
    blocking_step = SequenceStep(
        step_id="s3",
        action_ref="candidate:blocked_action",
        actor=ActorRole.CANDIDATE,
        declared_support=Support.STRUCTURAL,
        preconditions=(StructuralPrecondition(PreconditionCheckKind.ACTION_CONNECTS, ActorRole.CANDIDATE, "candidate:blocked_action"),),
    )
    state = _state_with_range_status(RangeStatus.IN_RANGE)
    state = CombatState(
        candidate=state.candidate,
        enemy=state.enemy,
        shared=SharedContext(
            action_contexts={
                **state.shared.action_contexts,
                "candidate:blocked_action": ActionContext(
                    action_ref="candidate:blocked_action", range_status=RangeStatus.OUT_OF_RANGE
                ),
            }
        ),
    )

    results, final_state = evaluate_sequence_prefix((step_1, blocking_step), state)

    assert len(results) == 2
    assert results[0].execution_status is ExecutionStatus.CONFIRMED
    assert results[1].execution_status is ExecutionStatus.BLOCKED
    # el estado final es el que produjo el ÚLTIMO paso NO bloqueado (step_1),
    # nunca el de entrada del bloqueado ni None
    assert final_state.candidate.stacks[_STACK_REF].count == 1


def test_evaluate_sequence_prefix_stops_at_the_first_block():
    step_1 = _step_with_action_connects_precondition()
    blocking_step = SequenceStep(
        step_id="s2",
        action_ref="candidate:blocked_action",
        actor=ActorRole.CANDIDATE,
        declared_support=Support.STRUCTURAL,
        preconditions=(StructuralPrecondition(PreconditionCheckKind.ACTION_CONNECTS, ActorRole.CANDIDATE, "candidate:blocked_action"),),
    )
    trailing_step = SequenceStep(
        step_id="s3", action_ref="candidate:trailing", actor=ActorRole.CANDIDATE, declared_support=Support.STRUCTURAL
    )
    state = _state_with_range_status(RangeStatus.IN_RANGE)
    state = CombatState(
        candidate=state.candidate,
        enemy=state.enemy,
        shared=SharedContext(
            action_contexts={
                **state.shared.action_contexts,
                "candidate:blocked_action": ActionContext(
                    action_ref="candidate:blocked_action", range_status=RangeStatus.OUT_OF_RANGE
                ),
            }
        ),
    )

    results, _ = evaluate_sequence_prefix((step_1, blocking_step, trailing_step), state)

    assert [r.step_id for r in results] == ["s1", "s2"]  # trailing_step nunca se evaluó


def test_evaluate_step_rejects_non_sequence_step():
    with pytest.raises(TypeError):
        evaluate_step("not a step", _state_with_range_status(RangeStatus.IN_RANGE))  # type: ignore[arg-type]


def test_evaluate_step_rejects_non_combat_state():
    step = _step_with_action_connects_precondition()
    with pytest.raises(TypeError):
        evaluate_step(step, "not a state")  # type: ignore[arg-type]
