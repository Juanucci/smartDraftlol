"""Contrato de paso de secuencia (v1.7 — auditable, fuente canónica única).

Define QUÉ es un paso de secuencia: su identidad mecánica, sus
precondiciones y postcondiciones ESTRUCTURALES (tipadas, no texto libre),
y qué identifica de forma estructural — nunca la función que lo
evaluaría contra un `CombatState` real (esa lógica de LECTURA/ESCRITURA
de `domain.combat_state` vive en `evaluator.py`, que importa los tipos de
este módulo; este módulo nunca importa `domain.combat_state`, así se
evita cualquier ciclo).

**Fuente canónica única** (cierre de hardening: antes existían dos
contratos capaces de divergir — `SequenceStep.preconditions`/
`postconditions` como texto libre, casi siempre vacío, y la lógica real
en un `StepEvaluationSpec` aparte que nunca se serializaba). Ahora
`SequenceStep` lleva las precondiciones/postcondiciones REALMENTE
evaluables (`StructuralPrecondition`/`StructuralPostcondition`) y su
`declared_support` — es la ÚNICA fuente, y es exactamente lo que
`evaluator.py` consume y lo que la serialización expone. No existe ya un
`StepEvaluationSpec` separado.

**Genérico por diseño**: ningún tipo de este módulo nombra un campeón, una
habilidad ni una mecánica concreta. `action_ref`, `reference`, y los
componentes de `EffectIdentity` son identificadores libres que puebla
quien construya una secuencia concreta (`registry.py`) — este módulo no
sabe qué kit describen.

**`ActorRole`** reutiliza exactamente los roles ya establecidos por
`CombatState` (`domain/combat_state.py`) y por
`ReasoningContext.candidate_abilities()/enemy_abilities()` — nunca
"self"/"other", que son ambiguos sin decir de quién.

**Soporte de una cadena, no un promedio** (diseño, principio B0/B5 de
`domain/enums.Support`): una precondición `UNSATISFIED` bloquea el paso por
completo (no hay "soporte parcial" de un paso bloqueado); una precondición
`UNKNOWN` nunca permite que el paso conserve `Support.STRUCTURAL` — como
mucho `CONDITIONED`. Esta regla se aplica con una **prioridad explícita**
(`_SUPPORT_PRIORITY`), nunca con el orden de declaración accidental del
enum `Support`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType

from lol_reasoner.domain.enums import Support

# ---------------------------------------------------------------------------
# Validación explícita (mismo principio que domain/combat_state.py)
# ---------------------------------------------------------------------------


def _require_nonempty_string(value: object, *, field_name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} debe ser str, no {value!r} ({type(value).__name__})")
    if not value.strip():
        raise ValueError(f"{field_name} no puede ser vacío ni contener solo espacios (recibido {value!r})")


# ---------------------------------------------------------------------------
# Roles — mismos que CombatState, nunca "self"/"other"
# ---------------------------------------------------------------------------


class ActorRole(str, Enum):
    CANDIDATE = "candidate"
    ENEMY = "enemy"


# ---------------------------------------------------------------------------
# Identidad mecánica estructural
# ---------------------------------------------------------------------------

# Componente reservado para un efecto sin partes distinguibles — nunca un
# string mágico repetido en código/tests. Un efecto sin partes NO usa
# `None` (ver docs/design/v1.7-sequence-state-design.md §B.3, endurecido en
# Etapa 2): usa esta constante, explícita e inequívoca. No introducir
# sinónimos ("full"/"entire"/"all"): un solo nombre para un solo concepto.
WHOLE_EFFECT_COMPONENT = "whole"


@dataclass(frozen=True, slots=True)
class EffectIdentity:
    """Identidad mecánica mínima de UN efecto concreto — deliberadamente
    más granular que `(ability_id, effect_type)` (diseño §B.3): dos
    efectos de la MISMA habilidad con el mismo rol causal pero distinto
    componente (p. ej. filo/mango de un área con dos zonas, o daño vs.
    aplicación de stack de la MISMA habilidad) deben poder distinguirse.
    Fusionarlos solo porque comparten habilidad/tipo sería doble conteo o
    pérdida de matiz semántico.

    Los tres campos son texto explícito, no vacío — nada de esto se infiere
    ni se normaliza. Un efecto sin partes distinguibles declara
    `component=WHOLE_EFFECT_COMPONENT`, nunca `None` ni un sinónimo ad hoc.
    Sin mappings internos: es hashable y usable como elemento de un
    `frozenset`/clave de deduplicación futura.
    """

    fact_ref: str  # referencia estable al hecho/efecto (ability_id, effect_id, o equivalente)
    causal_role: str  # p. ej. "damage", "heal", "stack_application", "displacement"
    component: str  # parte/fase concreta del efecto, o WHOLE_EFFECT_COMPONENT si no aplica

    def __post_init__(self) -> None:
        _require_nonempty_string(self.fact_ref, field_name="EffectIdentity.fact_ref")
        _require_nonempty_string(self.causal_role, field_name="EffectIdentity.causal_role")
        _require_nonempty_string(self.component, field_name="EffectIdentity.component")


def _effect_identity_to_primitive(identity: EffectIdentity) -> dict[str, object]:
    return {
        "fact_ref": identity.fact_ref,
        "causal_role": identity.causal_role,
        "component": identity.component,
    }


# ---------------------------------------------------------------------------
# Estado de una precondición y soporte de una cadena
# ---------------------------------------------------------------------------


class PreconditionStatus(str, Enum):
    """Tri-estado explícito de UNA precondición evaluada — nunca una
    probabilidad. `UNKNOWN` no es lo mismo que `UNSATISFIED`: una
    precondición desconocida limita el soporte alcanzable (ver
    `resolve_step_support`), pero no bloquea la rama; `UNSATISFIED` sí la
    bloquea."""

    SATISFIED = "satisfied"
    UNKNOWN = "unknown"
    UNSATISFIED = "unsatisfied"


# Prioridad EXPLÍCITA de certeza, de menor a mayor — nunca el orden de
# declaración accidental de `Support` (que además tampoco es totalmente
# ordinal: es un `(str, Enum)`, no un `IntEnum`).
_SUPPORT_PRIORITY: MappingProxyType[Support, int] = MappingProxyType(
    {
        Support.AMBIGUOUS: 0,
        Support.CONDITIONED: 1,
        Support.STRUCTURAL: 2,
    }
)


def resolve_step_support(
    *, declared_support: Support, precondition_statuses: Iterable[PreconditionStatus]
) -> Support | None:
    """Soporte real de un paso una vez aplicadas sus precondiciones
    PROPIAS (sin considerar aún si el estado de entrada era en sí mismo
    una proyección heredada — eso lo aplica `StepResult`, ver `sequence.py`).

    Devuelve `None` si el paso queda **bloqueado** (alguna precondición
    `UNSATISFIED`) — un paso bloqueado no tiene un nivel de soporte, no
    tiene ninguno. Si ninguna precondición está `UNSATISFIED` pero alguna
    está `UNKNOWN`, el soporte declarado se **limita** a como mucho
    `CONDITIONED` — nunca se conserva `STRUCTURAL` sobre una precondición
    no observada. Es una función pura: no muta nada, no consulta ningún
    `CombatState` (eso es el motor de transición, en `evaluator.py`).
    """

    if not isinstance(declared_support, Support):
        raise TypeError(
            f"resolve_step_support: declared_support debe ser Support, no "
            f"{declared_support!r} ({type(declared_support).__name__})"
        )
    statuses = tuple(precondition_statuses)
    for status in statuses:
        if not isinstance(status, PreconditionStatus):
            raise TypeError(
                f"resolve_step_support: cada precondition_status debe ser "
                f"PreconditionStatus, no {status!r} ({type(status).__name__})"
            )

    if any(status is PreconditionStatus.UNSATISFIED for status in statuses):
        return None

    support = declared_support
    if any(status is PreconditionStatus.UNKNOWN for status in statuses):
        if _SUPPORT_PRIORITY[support] > _SUPPORT_PRIORITY[Support.CONDITIONED]:
            support = Support.CONDITIONED
    return support


# ---------------------------------------------------------------------------
# Vocabulario genérico de precondiciones/postcondiciones estructurales
# (antes vivía en evaluator.py; movido acá para que SequenceStep pueda
# usarlo como fuente canónica sin crear un ciclo evaluator.py <-> sequence.py)
# ---------------------------------------------------------------------------


class PreconditionCheckKind(str, Enum):
    """Hechos estructurales que el evaluador (`evaluator.py`) sabe leer de
    un `CombatState` — ninguno nombra una mecánica concreta; los tres ya
    existen en `domain.combat_state`.

    `ACTION_CONNECTS` deliberadamente NO es un único chequeo "global":
    cada `StructuralPrecondition` de este tipo se liga a un `reference`
    (`action_ref`) DISTINTO por acción/zona — alcance de autoataque,
    impacto de un desplazamiento, o la zona exterior específica de una
    habilidad de dos zonas son tres entradas INDEPENDIENTES de
    `SharedContext.action_contexts`, nunca inferidas una de otra.

    `INVALIDATOR_ABSENT`: un control/desplazamiento NO bloquea
    automáticamente una acción posterior — solo lo hace si un invalidador
    CONCRETO de esa acción está `PRESENT`, reusando el tri-estado
    `InvalidatorStatus` ya existente en `ActionContext`."""

    ACTION_CONNECTS = "action_connects"  # SharedContext.action_contexts[reference].range_status
    ABILITY_READY = "ability_ready"  # ActorState.abilities[reference].availability
    INVALIDATOR_ABSENT = "invalidator_absent"  # SharedContext.action_contexts[reference].invalidators[invalidator_key]


@dataclass(frozen=True, slots=True)
class StructuralPrecondition:
    """Identidad COMPLETA de una precondición estructural — kind, quién,
    y sobre qué referencia. Es el tipo que viaja tanto en
    `SequenceStep.preconditions` (declarativo) como en cada
    `PreconditionResult` (`sequence.py`, ya evaluado) — la MISMA
    instancia/igualdad estructural en ambos lados, nunca dos objetos
    capaces de divergir."""

    kind: PreconditionCheckKind
    actor: ActorRole
    reference: str  # action_ref (ACTION_CONNECTS/INVALIDATOR_ABSENT) o slot de `abilities` (ABILITY_READY)
    invalidator_key: str | None = None  # SOLO para INVALIDATOR_ABSENT: qué invalidador de `reference` consultar

    def __post_init__(self) -> None:
        if not isinstance(self.kind, PreconditionCheckKind):
            raise TypeError(f"StructuralPrecondition.kind debe ser PreconditionCheckKind, no {self.kind!r}")
        if not isinstance(self.actor, ActorRole):
            raise TypeError(f"StructuralPrecondition.actor debe ser ActorRole, no {self.actor!r}")
        if not isinstance(self.reference, str) or not self.reference.strip():
            raise ValueError(f"StructuralPrecondition.reference no puede ser vacío (recibido {self.reference!r})")
        if self.kind is PreconditionCheckKind.INVALIDATOR_ABSENT:
            if not isinstance(self.invalidator_key, str) or not self.invalidator_key.strip():
                raise ValueError(
                    "StructuralPrecondition.invalidator_key es obligatorio y no vacío cuando "
                    f"kind == INVALIDATOR_ABSENT (recibido {self.invalidator_key!r})"
                )
        elif self.invalidator_key is not None:
            raise ValueError(
                f"StructuralPrecondition.invalidator_key solo aplica a INVALIDATOR_ABSENT, no a "
                f"{self.kind!r} (recibido {self.invalidator_key!r})"
            )


def _structural_precondition_to_primitive(precondition: StructuralPrecondition) -> dict[str, object]:
    return {
        "kind": precondition.kind.value,
        "actor": precondition.actor.value,
        "reference": precondition.reference,
        "invalidator_key": precondition.invalidator_key,
    }


class PostconditionEffectKind(str, Enum):
    """Transiciones estructurales que el evaluador sabe aplicar sobre un
    `CombatState` — ninguna inventa un valor mecánico nuevo: solo mueve
    campos ya existentes a otro de sus propios valores cualitativos."""

    ABILITY_ON_COOLDOWN = "ability_on_cooldown"  # ActorState.abilities[reference] -> ON_COOLDOWN
    STACK_APPLIED = "stack_applied"  # ActorState.stacks[reference] -> una aplicación más (± reward)


@dataclass(frozen=True, slots=True)
class StructuralPostcondition:
    kind: PostconditionEffectKind
    actor: ActorRole  # a quién se le aplica — el OBJETIVO, no necesariamente quien actúa
    reference: str  # slot dentro de `abilities`, o clave dentro de `stacks`
    # SOLO para STACK_APPLIED: umbral de la StackingMechanic que `reference`
    # alimenta. Si se alcanza o supera con esta aplicación, activa
    # `RewardState.ACTIVE`; si no se alcanza, dice `RewardState.INACTIVE`
    # (un hecho CONOCIDO, no una omisión); si el conteo previo es
    # desconocido, no puede saberse si se cruzó — se preserva el
    # `reward_state` anterior sin inventar nada. `None` = esta aplicación
    # no modela lógica de umbral (p. ej. Hemorrhage en esta ronda, cuyo
    # umbral de 5 queda fuera de alcance — "no llegues a cinco cargas").
    threshold: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, PostconditionEffectKind):
            raise TypeError(f"StructuralPostcondition.kind debe ser PostconditionEffectKind, no {self.kind!r}")
        if not isinstance(self.actor, ActorRole):
            raise TypeError(f"StructuralPostcondition.actor debe ser ActorRole, no {self.actor!r}")
        if not isinstance(self.reference, str) or not self.reference.strip():
            raise ValueError(f"StructuralPostcondition.reference no puede ser vacío (recibido {self.reference!r})")
        if self.threshold is not None:
            if self.kind is not PostconditionEffectKind.STACK_APPLIED:
                raise ValueError(
                    f"StructuralPostcondition.threshold solo aplica a STACK_APPLIED, no a "
                    f"{self.kind!r} (recibido {self.threshold!r})"
                )
            if isinstance(self.threshold, bool) or not isinstance(self.threshold, int) or self.threshold <= 0:
                raise ValueError(
                    f"StructuralPostcondition.threshold debe ser un int positivo real, no "
                    f"{self.threshold!r} ({type(self.threshold).__name__})"
                )


def _structural_postcondition_to_primitive(postcondition: StructuralPostcondition) -> dict[str, object]:
    return {
        "kind": postcondition.kind.value,
        "actor": postcondition.actor.value,
        "reference": postcondition.reference,
        "threshold": postcondition.threshold,
    }


def _require_immutable_precondition_tuple(value: object, *, field_name: str) -> None:
    if not isinstance(value, tuple) or not all(isinstance(item, StructuralPrecondition) for item in value):
        raise TypeError(f"{field_name} debe ser tuple[StructuralPrecondition, ...]")
    if len(set(value)) != len(value):
        raise ValueError(f"{field_name} tiene StructuralPrecondition duplicadas: {value!r}")


def _require_immutable_postcondition_tuple(value: object, *, field_name: str) -> None:
    if not isinstance(value, tuple) or not all(isinstance(item, StructuralPostcondition) for item in value):
        raise TypeError(f"{field_name} debe ser tuple[StructuralPostcondition, ...]")
    if len(set(value)) != len(value):
        raise ValueError(f"{field_name} tiene StructuralPostcondition duplicadas: {value!r}")


# ---------------------------------------------------------------------------
# SequenceStep — FUENTE CANÓNICA ÚNICA: identidad + precondiciones/
# postcondiciones REALMENTE evaluables + certeza declarada. Sin callables
# ni motor de transición (eso vive en evaluator.py, que lee estos campos).
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SequenceStep:
    """Paso declarativo de una secuencia — y ÚNICA fuente de verdad de sus
    precondiciones/postcondiciones (cierre de hardening): lo que
    `evaluator.py` evalúa es EXACTAMENTE `self.preconditions`/
    `self.postconditions`, y es EXACTAMENTE lo que la serialización expone
    — nunca una lista declarativa vacía mientras la lógica real vive
    escondida en otro objeto.

    `declared_support` es la certeza que este paso tendría SI todas sus
    precondiciones se sostuvieran (lo que una regla/hecho mecánico
    declararía en el mejor caso) — un dato del PASO, no de una evaluación
    puntual, por eso vive acá y no en un tipo de evaluación aparte.

    Deliberadamente sin callables ni closures: un paso es datos, nunca
    código embebido — lo que permite auditar/serializar cualquier
    secuencia sin ejecutar nada.
    """

    step_id: str
    action_ref: str
    actor: ActorRole
    declared_support: Support
    preconditions: tuple[StructuralPrecondition, ...] = field(default_factory=tuple)
    consumes: tuple[EffectIdentity, ...] = field(default_factory=tuple)
    postconditions: tuple[StructuralPostcondition, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _require_nonempty_string(self.step_id, field_name="SequenceStep.step_id")
        _require_nonempty_string(self.action_ref, field_name="SequenceStep.action_ref")
        if not isinstance(self.actor, ActorRole):
            raise TypeError(
                f"SequenceStep.actor debe ser ActorRole, no {self.actor!r} "
                f"({type(self.actor).__name__})"
            )
        if not isinstance(self.declared_support, Support):
            raise TypeError(
                f"SequenceStep.declared_support debe ser Support, no {self.declared_support!r} "
                f"({type(self.declared_support).__name__})"
            )
        _require_immutable_precondition_tuple(self.preconditions, field_name="SequenceStep.preconditions")
        _require_immutable_postcondition_tuple(self.postconditions, field_name="SequenceStep.postconditions")

        if not isinstance(self.consumes, tuple):
            raise TypeError(f"SequenceStep.consumes debe ser tuple, no {type(self.consumes).__name__}")
        for identity in self.consumes:
            if not isinstance(identity, EffectIdentity):
                raise TypeError(
                    f"SequenceStep.consumes[] debe ser EffectIdentity, no {identity!r} "
                    f"({type(identity).__name__})"
                )
        if len(set(self.consumes)) != len(self.consumes):
            raise ValueError(f"SequenceStep.consumes tiene EffectIdentity duplicadas: {self.consumes!r}")


def _sequence_step_to_primitive(step: SequenceStep) -> dict[str, object]:
    """Frontera de serialización para UN paso — sub-parte privada de
    `sequence.sequence_to_primitive`/`sequence.scenario_outcome_to_primitive`
    (ver ese módulo para la API pública y el resto de los tipos de
    secuencia). Serializa las precondiciones/postcondiciones REALES — las
    mismas que usa `evaluator.py` — nunca listas vacías."""

    return {
        "step_id": step.step_id,
        "action_ref": step.action_ref,
        "actor": step.actor.value,
        "declared_support": step.declared_support.value,
        "preconditions": [_structural_precondition_to_primitive(p) for p in step.preconditions],
        "consumes": [_effect_identity_to_primitive(identity) for identity in step.consumes],
        "postconditions": [_structural_postcondition_to_primitive(p) for p in step.postconditions],
    }
