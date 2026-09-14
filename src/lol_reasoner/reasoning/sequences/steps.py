"""Contrato de paso de secuencia (v1.7, Etapa 2 — tipos, sin motor).

Esta ronda define QUÉ es un paso de secuencia — su identidad mecánica, sus
precondiciones declaradas, qué identifica de forma estructural, y qué
postcondiciones anuncia — nunca la función que lo evaluaría contra un
`CombatState` real. No hay `SequenceStep.apply(state) -> CombatState`
todavía: eso es el motor de transición, explícitamente fuera de alcance de
esta ronda (docs/design/v1.7-sequence-state-design.md §B.6).

**Genérico por diseño**: ningún tipo de este módulo nombra un campeón, una
habilidad ni una mecánica concreta. `action_ref`, los strings de
`preconditions`/`postconditions`, y los componentes de `EffectIdentity` son
identificadores libres que puebla quien construya una secuencia concreta
(fuera de esta ronda) — este módulo no sabe qué kit describen.

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


def _require_immutable_nonempty_string_tuple(value: object, *, field_name: str) -> None:
    """Exige una `tuple[str, ...]` de strings no vacíos, sin duplicados
    silenciosos (dos entradas idénticas no declaran nada nuevo que una
    sola no dijera ya)."""

    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} debe ser tuple, no {type(value).__name__}")
    for item in value:
        _require_nonempty_string(item, field_name=f"{field_name}[]")
    if len(set(value)) != len(value):
        raise ValueError(f"{field_name} tiene elementos repetidos: {value!r}")


# ---------------------------------------------------------------------------
# Roles — mismos que CombatState, nunca "self"/"other"
# ---------------------------------------------------------------------------


class ActorRole(str, Enum):
    CANDIDATE = "candidate"
    ENEMY = "enemy"


# ---------------------------------------------------------------------------
# Identidad mecánica estructural
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EffectIdentity:
    """Identidad mecánica mínima de UN efecto concreto — deliberadamente
    más granular que `(ability_id, effect_type)` (diseño §B.3): dos
    efectos de la MISMA habilidad con el mismo rol causal pero distinto
    componente (p. ej. filo/mango de un área con dos zonas) deben poder
    distinguirse. Fusionarlos solo porque comparten habilidad/tipo sería
    doble conteo o pérdida de matiz semántico.

    Los tres campos son texto explícito, no vacío — nada de esto se infiere
    ni se normaliza. Sin mappings internos: es hashable y usable como
    elemento de un `frozenset`/clave de deduplicación futura.
    """

    fact_ref: str  # referencia estable al hecho/efecto (ability_id, effect_id, o equivalente)
    causal_role: str  # p. ej. "damage", "heal", "stack_application", "displacement"
    component: str  # parte/fase concreta del efecto (p. ej. "blade", "handle", "whole")

    def __post_init__(self) -> None:
        _require_nonempty_string(self.fact_ref, field_name="EffectIdentity.fact_ref")
        _require_nonempty_string(self.causal_role, field_name="EffectIdentity.causal_role")
        _require_nonempty_string(self.component, field_name="EffectIdentity.component")


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
    """Soporte real de un paso una vez aplicadas sus precondiciones.

    Devuelve `None` si el paso queda **bloqueado** (alguna precondición
    `UNSATISFIED`) — un paso bloqueado no tiene un nivel de soporte, no
    tiene ninguno. Si ninguna precondición está `UNSATISFIED` pero alguna
    está `UNKNOWN`, el soporte declarado se **limita** a como mucho
    `CONDITIONED` — nunca se conserva `STRUCTURAL` sobre una precondición
    no observada. Es una función pura: no muta nada, no consulta ningún
    `CombatState` (eso es el motor de transición futuro).
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
# SequenceStep — contrato declarativo, sin callables ni motor de transición
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SequenceStep:
    """Paso declarativo de una secuencia.

    Declara identidad, quién actúa, qué precondiciones exige (como texto
    calificado, no evaluado — la evaluación real contra un `CombatState`
    vive en un motor futuro), qué identidades mecánicas consume (para que
    `InteractionSequence.covers_causes` pueda derivarse estructuralmente,
    §B.3) y qué postcondiciones anuncia conceptualmente. Ninguna de las
    dos últimas se APLICA en esta ronda — son contrato, no ejecución.

    Deliberadamente sin callables ni closures: un paso es datos, nunca
    código embebido — lo que permite auditar/serializar cualquier
    secuencia sin ejecutar nada.
    """

    step_id: str
    action_ref: str
    actor: ActorRole
    preconditions: tuple[str, ...] = field(default_factory=tuple)
    consumes: tuple[EffectIdentity, ...] = field(default_factory=tuple)
    postconditions: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _require_nonempty_string(self.step_id, field_name="SequenceStep.step_id")
        _require_nonempty_string(self.action_ref, field_name="SequenceStep.action_ref")
        if not isinstance(self.actor, ActorRole):
            raise TypeError(
                f"SequenceStep.actor debe ser ActorRole, no {self.actor!r} "
                f"({type(self.actor).__name__})"
            )
        _require_immutable_nonempty_string_tuple(self.preconditions, field_name="SequenceStep.preconditions")
        _require_immutable_nonempty_string_tuple(self.postconditions, field_name="SequenceStep.postconditions")

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
