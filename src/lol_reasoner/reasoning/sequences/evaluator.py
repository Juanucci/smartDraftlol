"""Evaluador genérico de pasos de secuencia contra un `CombatState` real.

v1.7 — cierre de Etapa 2 más primera secuencia real, exclusivamente en
shadow mode. Ningún tipo ni función de este módulo nombra un campeón, una
habilidad o una mecánica concreta: la instancia real (Darius/Mordekaiser,
Apprehend/Decimate/Hemorrhage) vive en `registry.py`, que resuelve
referencias contra el conocimiento existente y las pasa acá como datos.

**Contrato mínimo**: cada `SequenceStep` (declarativo, Etapa 2, sin
callables) se empareja con un `StepEvaluationSpec` — qué hechos
ESTRUCTURALES de un `CombatState` hay que leer para resolver sus
precondiciones (`StructuralPrecondition`), y qué transición
POSTCONDICIONAL aplica si el paso no queda bloqueado
(`StructuralPostcondition`). El emparejamiento vive APARTE de
`SequenceStep` a propósito — no reabre su API pública de Etapa 2 (no
agrega campos ni cambia sus invariantes).

**Vocabulario genérico, no ad hoc**: los dos tipos de precondición/
postcondición que este módulo sabe resolver leen/escriben exclusivamente
campos que YA existen en `domain.combat_state` (`RangeStatus`,
`AbilityAvailability`, `StackState`) — ningún campo nuevo, ninguna
simulación de tiempo, ninguna probabilidad. Una clave ausente en el
`CombatState` es `PreconditionStatus.UNKNOWN` (no observada), nunca se
infiere `SATISFIED`/`UNSATISFIED` a partir de su ausencia. Cada
`StructuralPrecondition` se liga a UNA acción concreta (`reference`) —
nunca un booleano global: estar en rango de un autoataque no dice nada
del `reference`, distinto, de la zona exterior de otra habilidad.

**Snapshot nuevo, nunca mutado in-place**: `evaluate_step`/
`evaluate_sequence_prefix` jamás modifican el `CombatState` recibido —
`dataclasses.replace` reconstruye actores/estado, lo que vuelve a correr
`__post_init__` (revalida y re-congela cualquier mapping tocado). El
snapshot de entrada queda intacto para quien lo llamó.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from enum import Enum

from lol_reasoner.domain.combat_state import (
    AbilityAvailability,
    AbilityState,
    ActorState,
    CombatState,
    RangeStatus,
    StackState,
    StackWindow,
)
from lol_reasoner.domain.enums import Support
from lol_reasoner.reasoning.sequences.sequence import PreconditionStatus, StepResult
from lol_reasoner.reasoning.sequences.steps import ActorRole, SequenceStep

# ---------------------------------------------------------------------------
# Vocabulario genérico de precondiciones/postcondiciones estructurales
# ---------------------------------------------------------------------------


class PreconditionCheckKind(str, Enum):
    """Hechos estructurales que este evaluador sabe leer de un
    `CombatState` — ninguno nombra una mecánica concreta; ambos ya
    existen en `domain.combat_state`.

    `ACTION_CONNECTS` (antes `ACTION_IN_RANGE`, renombrado en el microfix
    de esta ronda) deliberadamente NO es un único chequeo "global": cada
    `StructuralPrecondition` de este tipo se liga a un `reference`
    (`action_ref`) DISTINTO por acción/zona — alcance de autoataque,
    impacto de un desplazamiento, o la zona exterior específica de una
    habilidad de dos zonas son entradas INDEPENDIENTES de
    `SharedContext.action_contexts`, nunca inferidas una de otra. Que el
    action_ref de un desplazamiento esté `IN_RANGE` no dice nada sobre el
    action_ref, distinto, de la zona exterior de otra habilidad."""

    ACTION_CONNECTS = "action_connects"  # SharedContext.action_contexts[reference].range_status
    ABILITY_READY = "ability_ready"  # ActorState.abilities[reference].availability


@dataclass(frozen=True, slots=True)
class StructuralPrecondition:
    kind: PreconditionCheckKind
    actor: ActorRole
    reference: str  # action_ref (ACTION_CONNECTS) o slot dentro de `abilities` (ABILITY_READY)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, PreconditionCheckKind):
            raise TypeError(f"StructuralPrecondition.kind debe ser PreconditionCheckKind, no {self.kind!r}")
        if not isinstance(self.actor, ActorRole):
            raise TypeError(f"StructuralPrecondition.actor debe ser ActorRole, no {self.actor!r}")
        if not isinstance(self.reference, str) or not self.reference.strip():
            raise ValueError(f"StructuralPrecondition.reference no puede ser vacío (recibido {self.reference!r})")


class PostconditionEffectKind(str, Enum):
    """Transiciones estructurales que este evaluador sabe aplicar sobre un
    `CombatState` — ninguna inventa un valor mecánico nuevo: solo mueve
    campos ya existentes a otro de sus propios valores cualitativos."""

    ABILITY_ON_COOLDOWN = "ability_on_cooldown"  # ActorState.abilities[reference] -> ON_COOLDOWN
    STACK_APPLIED = "stack_applied"  # ActorState.stacks[reference] -> una aplicación más


@dataclass(frozen=True, slots=True)
class StructuralPostcondition:
    kind: PostconditionEffectKind
    actor: ActorRole  # a quién se le aplica — el OBJETIVO, no necesariamente quien actúa
    reference: str  # slot dentro de `abilities`, o clave dentro de `stacks`

    def __post_init__(self) -> None:
        if not isinstance(self.kind, PostconditionEffectKind):
            raise TypeError(f"StructuralPostcondition.kind debe ser PostconditionEffectKind, no {self.kind!r}")
        if not isinstance(self.actor, ActorRole):
            raise TypeError(f"StructuralPostcondition.actor debe ser ActorRole, no {self.actor!r}")
        if not isinstance(self.reference, str) or not self.reference.strip():
            raise ValueError(f"StructuralPostcondition.reference no puede ser vacío (recibido {self.reference!r})")


@dataclass(frozen=True, slots=True)
class StepEvaluationSpec:
    """Empareja UN `SequenceStep` con cómo evaluarlo contra un
    `CombatState` real. `declared_support` es la certeza que este paso
    tendría SI todas sus precondiciones se sostuvieran — la misma
    semántica declared/effective ya cerrada en `StepResult` (§A4)."""

    step: SequenceStep
    declared_support: Support
    preconditions: tuple[StructuralPrecondition, ...] = ()
    postconditions: tuple[StructuralPostcondition, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.step, SequenceStep):
            raise TypeError(f"StepEvaluationSpec.step debe ser SequenceStep, no {self.step!r}")
        if not isinstance(self.declared_support, Support):
            raise TypeError(f"StepEvaluationSpec.declared_support debe ser Support, no {self.declared_support!r}")
        if not isinstance(self.preconditions, tuple) or not all(
            isinstance(p, StructuralPrecondition) for p in self.preconditions
        ):
            raise TypeError("StepEvaluationSpec.preconditions debe ser tuple[StructuralPrecondition, ...]")
        if not isinstance(self.postconditions, tuple) or not all(
            isinstance(p, StructuralPostcondition) for p in self.postconditions
        ):
            raise TypeError("StepEvaluationSpec.postconditions debe ser tuple[StructuralPostcondition, ...]")


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


def _apply_stack(actor_state: ActorState, reference: str) -> ActorState:
    existing = actor_state.stacks.get(reference)
    if existing is None:
        raise ValueError(
            f"No se puede aplicar STACK_APPLIED: {reference!r} no está declarado en `stacks` de "
            "este ActorState — la mecánica debe existir explícitamente en el baseline antes de "
            "poder recibir una aplicación"
        )
    if existing.count is None:
        # Stack inicial desconocido: aplicar un golpe no inventa un conteo
        # exacto (§B5/B6) — solo confirma que el ciclo está activo.
        updated_stack = StackState(count=None, window=StackWindow.ACTIVE, reward_state=existing.reward_state)
    else:
        updated_stack = StackState(
            count=existing.count + 1, window=StackWindow.ACTIVE, reward_state=existing.reward_state
        )
    updated = dict(actor_state.stacks)
    updated[reference] = updated_stack
    return dataclasses.replace(actor_state, stacks=updated)


def _apply_postcondition(state: CombatState, postcondition: StructuralPostcondition) -> CombatState:
    actor_state = _actor_state_of(state, postcondition.actor)
    if postcondition.kind is PostconditionEffectKind.ABILITY_ON_COOLDOWN:
        updated_actor_state = _apply_ability_on_cooldown(actor_state, postcondition.reference)
    elif postcondition.kind is PostconditionEffectKind.STACK_APPLIED:
        updated_actor_state = _apply_stack(actor_state, postcondition.reference)
    else:
        raise ValueError(f"PostconditionEffectKind no soportado: {postcondition.kind!r}")  # pragma: no cover
    return _with_actor_state(state, postcondition.actor, updated_actor_state)


# ---------------------------------------------------------------------------
# API pública: evaluar un paso, o una secuencia completa como prefijo
# ---------------------------------------------------------------------------


def evaluate_step(spec: StepEvaluationSpec, state: CombatState) -> tuple[StepResult, CombatState]:
    """Evalúa UN paso contra `state`.

    Devuelve `(result, next_state)`: `next_state` es el MISMO `state`
    recibido si el paso queda bloqueado (`result.effective_support is
    None`) o no declara postcondiciones estructurales; uno NUEVO (nunca
    mutado in-place) si aplica alguna."""

    if not isinstance(state, CombatState):
        raise TypeError(f"evaluate_step espera un CombatState, no {state!r} ({type(state).__name__})")

    statuses = tuple(_resolve_precondition(p, state) for p in spec.preconditions)
    result = StepResult(
        step_id=spec.step.step_id, precondition_statuses=statuses, declared_support=spec.declared_support
    )

    if result.effective_support is None:
        return result, state  # bloqueado: no hay transición que aplicar

    next_state = state
    for postcondition in spec.postconditions:
        next_state = _apply_postcondition(next_state, postcondition)

    return result, next_state


def evaluate_sequence_prefix(
    specs: tuple[StepEvaluationSpec, ...], initial_state: CombatState
) -> tuple[tuple[StepResult, ...], CombatState]:
    """Evalúa una secuencia de specs EN ORDEN, deteniéndose en el primer
    paso bloqueado — así `step_results` es, por construcción, siempre el
    prefijo ordenado que `ScenarioOutcome` exige (§A1): nunca se generan
    resultados posteriores a un bloqueo porque el bucle corta ahí mismo.

    Devuelve los `StepResult` obtenidos y el último `CombatState`
    producido (el de entrada, sin cambios, si el primer paso ya bloquea).
    """

    results: list[StepResult] = []
    state = initial_state
    for spec in specs:
        result, state = evaluate_step(spec, state)
        results.append(result)
        if result.effective_support is None:
            break
    return tuple(results), state
