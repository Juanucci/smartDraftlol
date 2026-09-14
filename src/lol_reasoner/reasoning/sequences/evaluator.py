"""Evaluador genérico de pasos de secuencia contra un `CombatState` real.

v1.7 — cierre de hardening: `SequenceStep` (`steps.py`) es ahora la ÚNICA
fuente canónica de precondiciones/postcondiciones/`declared_support` de un
paso — este módulo ya NO define su propio vocabulario de
`StructuralPrecondition`/`StructuralPostcondition` (los importa de
`steps.py`) ni empareja nada aparte vía un `StepEvaluationSpec`: ese tipo
desapareció, era exactamente la segunda fuente de verdad capaz de
divergir de `SequenceStep`. `evaluate_step`/`evaluate_sequence_prefix`
ahora reciben `SequenceStep` directamente.

Ningún tipo ni función de este módulo nombra un campeón, una habilidad o
una mecánica concreta: la instancia real (Darius/Mordekaiser,
Apprehend/Decimate/Hemorrhage) vive en `registry.py`, que resuelve
referencias contra el conocimiento existente y las pasa acá como datos.

**Vocabulario genérico, no ad hoc**: los tipos de precondición/
postcondición que este módulo sabe resolver leen/escriben exclusivamente
campos que YA existen en `domain.combat_state` (`RangeStatus`,
`AbilityAvailability`, `InvalidatorStatus`, `StackState`) — ningún campo
nuevo, ninguna simulación de tiempo, ninguna probabilidad. Una clave
ausente en el `CombatState` es `PreconditionStatus.UNKNOWN` (no
observada), nunca se infiere `SATISFIED`/`UNSATISFIED` a partir de su
ausencia. Cada `StructuralPrecondition` se liga a UNA acción/invalidador
concreto (`reference`) — nunca un booleano global: estar en rango de un
autoataque no dice nada del `reference`, distinto, de la zona exterior de
otra habilidad, y un invalidador ausente para una acción no se infiere de
que otra acción haya conectado.

**Snapshot nuevo, nunca mutado in-place**: `evaluate_step`/
`evaluate_sequence_prefix` jamás modifican el `CombatState` recibido —
`dataclasses.replace` reconstruye actores/estado, lo que vuelve a correr
`__post_init__` (revalida y re-congela cualquier mapping tocado). El
snapshot de entrada queda intacto para quien lo llamó.

**Seguridad de estados proyectados** (cierre de hardening — §A3): un paso
`CONFIRMED` produce un `CombatState` confirmado; uno `HYPOTHETICAL`
produce, con la misma mecánica de aplicar postcondiciones, una
PROYECCIÓN — nunca indistinguible de un hecho porque viaja envuelta en
`StepTransition` junto al `StepResult` que declara explícitamente su
`execution_status`; uno `BLOCKED` no aplica sus postcondiciones y no
produce transición (`StepTransition.state is None`, blindado en su
`__post_init__`). Un paso posterior que evalúa contra una proyección
HEREDA esa incertidumbre vía `inherited_execution_status`
(`evaluate_sequence_prefix` la enhebra paso a paso) — nunca puede figurar
como ejecución efectivamente confirmada dependiendo de un estado
hipotético (ver `StepResult` en `sequence.py`).
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from lol_reasoner.domain.combat_state import (
    AbilityAvailability,
    AbilityState,
    ActorState,
    CombatState,
    InvalidatorStatus,
    RangeStatus,
    RewardState,
    StackState,
    StackWindow,
)
from lol_reasoner.reasoning.sequences.sequence import (
    ExecutionStatus,
    PreconditionResult,
    PreconditionStatus,
    StepResult,
)
from lol_reasoner.reasoning.sequences.steps import (
    ActorRole,
    PreconditionCheckKind,
    PostconditionEffectKind,
    SequenceStep,
    StructuralPostcondition,
    StructuralPrecondition,
)

# ---------------------------------------------------------------------------
# Lectura de precondiciones (nunca infiere SATISFIED/UNSATISFIED de una
# clave ausente — eso es UNKNOWN, la misma regla de tres/cuatro lecturas
# de domain.combat_state)
# ---------------------------------------------------------------------------


def _actor_state_of(state: CombatState, actor: ActorRole) -> ActorState:
    return state.candidate if actor is ActorRole.CANDIDATE else state.enemy


def _with_actor_state(state: CombatState, actor: ActorRole, new_actor_state: ActorState) -> CombatState:
    if actor is ActorRole.CANDIDATE:
        return dataclasses.replace(state, candidate=new_actor_state)
    return dataclasses.replace(state, enemy=new_actor_state)


def _resolve_precondition(precondition: StructuralPrecondition, state: CombatState) -> PreconditionStatus:
    if precondition.kind is PreconditionCheckKind.ACTION_CONNECTS:
        context = state.shared.action_contexts.get(precondition.reference)
        if context is None:
            return PreconditionStatus.UNKNOWN
        if context.range_status is RangeStatus.IN_RANGE:
            return PreconditionStatus.SATISFIED
        if context.range_status is RangeStatus.OUT_OF_RANGE:
            return PreconditionStatus.UNSATISFIED
        return PreconditionStatus.UNKNOWN

    if precondition.kind is PreconditionCheckKind.ABILITY_READY:
        actor_state = _actor_state_of(state, precondition.actor)
        ability = actor_state.abilities.get(precondition.reference)
        if ability is None:
            return PreconditionStatus.UNKNOWN
        if ability.availability is AbilityAvailability.READY:
            return PreconditionStatus.SATISFIED
        if ability.availability in (AbilityAvailability.ON_COOLDOWN, AbilityAvailability.UNLEARNED):
            return PreconditionStatus.UNSATISFIED
        return PreconditionStatus.UNKNOWN

    if precondition.kind is PreconditionCheckKind.INVALIDATOR_ABSENT:
        context = state.shared.action_contexts.get(precondition.reference)
        if context is None:
            return PreconditionStatus.UNKNOWN
        status = context.invalidators.get(precondition.invalidator_key)  # type: ignore[arg-type]
        if status is None or status is InvalidatorStatus.UNKNOWN:
            return PreconditionStatus.UNKNOWN
        if status is InvalidatorStatus.ABSENT:
            return PreconditionStatus.SATISFIED
        return PreconditionStatus.UNSATISFIED  # InvalidatorStatus.PRESENT

    raise ValueError(f"PreconditionCheckKind no soportado: {precondition.kind!r}")  # pragma: no cover


# ---------------------------------------------------------------------------
# Aplicación de postcondiciones — produce un CombatState NUEVO, nunca muta
# el recibido; falla explícito si la referencia requerida no existe.
# ---------------------------------------------------------------------------


def _apply_ability_on_cooldown(actor_state: ActorState, reference: str) -> ActorState:
    ability = actor_state.abilities.get(reference)
    if ability is None:
        raise ValueError(
            f"No se puede aplicar ABILITY_ON_COOLDOWN: {reference!r} no está declarado en "
            "`abilities` de este ActorState — referencia requerida ausente"
        )
    if ability.availability is AbilityAvailability.UNLEARNED:
        raise ValueError(
            f"No se puede poner en cooldown una habilidad UNLEARNED ({reference!r}) — "
            "inconsistencia entre la precondición ABILITY_READY (que debería haber "
            "bloqueado este paso) y su postcondición"
        )
    updated = dict(actor_state.abilities)
    updated[reference] = AbilityState(rank=ability.rank, availability=AbilityAvailability.ON_COOLDOWN)
    return dataclasses.replace(actor_state, abilities=updated)


def _apply_stack(actor_state: ActorState, reference: str, threshold: int | None) -> ActorState:
    existing = actor_state.stacks.get(reference)
    if existing is None:
        raise ValueError(
            f"No se puede aplicar STACK_APPLIED: {reference!r} no está declarado en `stacks` de "
            "este ActorState — la mecánica debe existir explícitamente en el baseline antes de "
            "poder recibir una aplicación"
        )
    if existing.count is None:
        # Stack inicial desconocido: aplicar un golpe no inventa un conteo
        # exacto (§B5/B6) — solo confirma que el ciclo está activo. Sin
        # conteo, tampoco puede saberse si se cruzó un umbral: el
        # reward_state anterior se preserva sin cambios.
        new_count = None
        new_reward = existing.reward_state
    else:
        new_count = existing.count + 1
        if threshold is None:
            new_reward = existing.reward_state  # esta aplicación no modela lógica de umbral
        elif new_count >= threshold:
            new_reward = RewardState.ACTIVE  # umbral alcanzado: hecho conocido, se activa
        else:
            new_reward = RewardState.INACTIVE  # bajo el umbral: hecho conocido, NO se activa
    updated_stack = StackState(count=new_count, window=StackWindow.ACTIVE, reward_state=new_reward)
    updated = dict(actor_state.stacks)
    updated[reference] = updated_stack
    return dataclasses.replace(actor_state, stacks=updated)


def _apply_postcondition(state: CombatState, postcondition: StructuralPostcondition) -> CombatState:
    actor_state = _actor_state_of(state, postcondition.actor)
    if postcondition.kind is PostconditionEffectKind.ABILITY_ON_COOLDOWN:
        updated_actor_state = _apply_ability_on_cooldown(actor_state, postcondition.reference)
    elif postcondition.kind is PostconditionEffectKind.STACK_APPLIED:
        updated_actor_state = _apply_stack(actor_state, postcondition.reference, postcondition.threshold)
    else:
        raise ValueError(f"PostconditionEffectKind no soportado: {postcondition.kind!r}")  # pragma: no cover
    return _with_actor_state(state, postcondition.actor, updated_actor_state)


# ---------------------------------------------------------------------------
# StepTransition — par (StepResult, CombatState | None) donde `None` es
# SIEMPRE Y ÚNICAMENTE el caso BLOCKED (cierre de hardening — §A3)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StepTransition:
    """Resultado de evaluar UN paso: su `StepResult` (con `execution_status`
    ya resuelto — `CONFIRMED`/`HYPOTHETICAL`/`BLOCKED`, incluida la
    herencia de incertidumbre) junto con el `CombatState` que produjo, si
    produjo alguno.

    `state is None` es SIEMPRE y ÚNICAMENTE el caso `BLOCKED` (blindado
    acá abajo): "no hubo transición porque el paso bloqueó" queda
    estructuralmente distinto de "hubo una transición y produjo este
    estado", sea confirmado o proyectado. Un `state` no-`None` con
    `result.execution_status is HYPOTHETICAL` es una PROYECCIÓN bajo
    hipótesis, nunca un hecho confirmado — `result.execution_status`
    (siempre serializado junto a este estado, nunca por separado) es la
    única fuente que dice cuál es cuál; este tipo no duplica esa
    distinción con un campo booleano propio."""

    result: StepResult
    state: CombatState | None

    __hash__ = None  # type: ignore[assignment]  # puede contener un CombatState no hashable

    def __post_init__(self) -> None:
        if not isinstance(self.result, StepResult):
            raise TypeError(f"StepTransition.result debe ser StepResult, no {self.result!r} ({type(self.result).__name__})")
        if self.state is not None and not isinstance(self.state, CombatState):
            raise TypeError(
                f"StepTransition.state debe ser CombatState o None, no {self.state!r} "
                f"({type(self.state).__name__})"
            )
        is_blocked = self.result.execution_status is ExecutionStatus.BLOCKED
        if is_blocked and self.state is not None:
            raise ValueError(
                "StepTransition.state debe ser None cuando result.execution_status es BLOCKED — "
                "un paso bloqueado no aplica sus postcondiciones, no hay transición que representar"
            )
        if not is_blocked and self.state is None:
            raise ValueError(
                "StepTransition.state no puede ser None salvo cuando result.execution_status es "
                "BLOCKED — CONFIRMED y HYPOTHETICAL siempre producen un CombatState (confirmado o "
                "proyectado, respectivamente)"
            )


# ---------------------------------------------------------------------------
# API pública: evaluar un paso, o una secuencia completa como prefijo
# ---------------------------------------------------------------------------


def evaluate_step(
    step: SequenceStep,
    state: CombatState,
    *,
    inherited_execution_status: ExecutionStatus = ExecutionStatus.CONFIRMED,
) -> StepTransition:
    """Evalúa UN `SequenceStep` (fuente canónica única, `steps.py`) contra
    `state`, heredando `inherited_execution_status` — la certeza del
    `CombatState` de entrada (`CONFIRMED` por defecto: el baseline o una
    transición previa confirmada; `HYPOTHETICAL` si `state` es en sí mismo
    una proyección de un paso anterior). Nunca `BLOCKED` (`StepResult` lo
    rechaza — ver `sequence.py`).

    Devuelve un `StepTransition`: `state=None` si el paso queda bloqueado
    (`result.execution_status is BLOCKED`, sin aplicar sus
    postcondiciones); si no, el `CombatState` resultante — confirmado o
    proyectado según `result.execution_status`, nunca mutado in-place."""

    if not isinstance(step, SequenceStep):
        raise TypeError(f"evaluate_step espera un SequenceStep, no {step!r} ({type(step).__name__})")
    if not isinstance(state, CombatState):
        raise TypeError(f"evaluate_step espera un CombatState, no {state!r} ({type(state).__name__})")

    precondition_results = tuple(
        PreconditionResult(precondition=p, status=_resolve_precondition(p, state)) for p in step.preconditions
    )
    result = StepResult(
        step_id=step.step_id,
        precondition_results=precondition_results,
        declared_support=step.declared_support,
        inherited_execution_status=inherited_execution_status,
    )

    if result.execution_status is ExecutionStatus.BLOCKED:
        return StepTransition(result=result, state=None)  # bloqueado: no hay transición que aplicar

    next_state = state
    for postcondition in step.postconditions:
        next_state = _apply_postcondition(next_state, postcondition)

    return StepTransition(result=result, state=next_state)


def evaluate_sequence_prefix(
    steps: tuple[SequenceStep, ...], initial_state: CombatState
) -> tuple[tuple[StepResult, ...], CombatState]:
    """Evalúa una secuencia de `SequenceStep` EN ORDEN, deteniéndose en el
    primer paso bloqueado — así `step_results` es, por construcción,
    siempre el prefijo ordenado que `ScenarioOutcome` exige (§A1): nunca
    se generan resultados posteriores a un bloqueo porque el bucle corta
    ahí mismo.

    **Herencia de incertidumbre enhebrada** (cierre de hardening — §A3):
    el primer paso hereda `CONFIRMED` (el baseline es, por definición, el
    punto de partida conocido); cada paso siguiente hereda el
    `execution_status` YA RESUELTO (con su propia herencia incluida) del
    paso anterior — así una vez que la cadena entra en `HYPOTHETICAL`,
    todo paso posterior quedará como mucho `HYPOTHETICAL` (nunca
    `CONFIRMED`), sin necesidad de que `chain_execution_status` haga nada
    especial: cada `StepResult` ya trae su estado final correctamente
    degradado.

    Devuelve los `StepResult` obtenidos y el último `CombatState`
    producido (el de entrada, sin cambios, si el primer paso ya bloquea)."""

    results: list[StepResult] = []
    state = initial_state
    inherited_status = ExecutionStatus.CONFIRMED
    for step in steps:
        transition = evaluate_step(step, state, inherited_execution_status=inherited_status)
        results.append(transition.result)
        if transition.result.execution_status is ExecutionStatus.BLOCKED:
            break
        state = transition.state  # type: ignore[assignment]  # no-None: no bloqueado (StepTransition lo garantiza)
        inherited_status = transition.result.execution_status
    return tuple(results), state
