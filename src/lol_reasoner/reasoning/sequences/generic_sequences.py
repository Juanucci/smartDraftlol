"""Familia mecánica GENÉRICA: control/desplazamiento habilita contacto ->
follow-up dañino aplica stack (v1.7, primera secuencia real, shadow mode).

Ningún tipo ni función de este módulo nombra un campeón, una habilidad ni
una mecánica concreta — la instancia real (Apprehend -> autoataque/Q ->
Hemorrhage, para Darius vs Mordekaiser) vive en `registry.py`, que
resuelve referencias reales del conocimiento existente y llama a las
funciones de acá con esas referencias como datos puros.

Modela un punto de decisión de dos pasos: un paso de CONTROL (habilita
contacto, no aplica el efecto dañino por sí mismo) seguido de EXACTAMENTE
UN follow-up entre varias alternativas mutuamente excluyentes — nunca
sumadas (§B4). Cada alternativa produce su propia `InteractionSequence`
(mismos dos pasos: control + esa alternativa), todas compartiendo el
mismo `AlternativeGroup` y cada una con su propio `alternative_id`.

**Fuente canónica única** (cierre de hardening): ya no existe
`GenericSequenceSpec`/`StepEvaluationSpec` — cada `SequenceStep` lleva
directamente su `declared_support` y sus precondiciones/postcondiciones
REALMENTE evaluables (`steps.py`). `ControlFollowupFamily` guarda
`InteractionSequence` directamente, no un envoltorio con specs alineados
aparte."""

from __future__ import annotations

from dataclasses import dataclass, field

from lol_reasoner.domain.enums import Support
from lol_reasoner.reasoning.sequences.sequence import AlternativeGroup, InteractionSequence
from lol_reasoner.reasoning.sequences.steps import (
    ActorRole,
    EffectIdentity,
    PostconditionEffectKind,
    PreconditionCheckKind,
    SequenceStep,
    StructuralPostcondition,
    StructuralPrecondition,
)


@dataclass(frozen=True, slots=True)
class FollowupAlternative:
    """UNA alternativa de follow-up del mismo punto de decisión (p. ej.
    autoataque o una habilidad concreta) — datos puros, sin lógica.

    `ability_slot=None` representa un follow-up sin `AbilityState` propio
    (p. ej. un autoataque: no tiene rango de puntos ni cooldown modelado
    en `domain.combat_state`) — en ese caso no se declara precondición ni
    postcondición de disponibilidad para él, solo la de conexión.

    `connect_reference` (microfix de esta ronda): el `action_ref` que se
    consulta para "¿esta alternativa conectó?" — por defecto igual a
    `action_ref`, pero puede ser OTRO más específico (p. ej. la zona
    exterior de una habilidad de dos zonas) cuando "estar en rango de la
    habilidad" y "conectar en la zona geométrica que aplica el efecto" son
    hechos distintos que no deben inferirse uno del otro (§3 del microfix).
    """

    alternative_id: str
    step_id: str
    action_ref: str
    ability_slot: str | None
    consumes: EffectIdentity
    stack_target: ActorRole
    stack_reference: str
    connect_reference: str | None = None  # None -> se completa con action_ref en __post_init__
    stack_threshold: int | None = None  # ver StructuralPostcondition.threshold

    def __post_init__(self) -> None:
        for field_name, value in (
            ("alternative_id", self.alternative_id),
            ("step_id", self.step_id),
            ("action_ref", self.action_ref),
            ("stack_reference", self.stack_reference),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"FollowupAlternative.{field_name} no puede ser vacío (recibido {value!r})")
        if self.ability_slot is not None and (not isinstance(self.ability_slot, str) or not self.ability_slot.strip()):
            raise ValueError(f"FollowupAlternative.ability_slot no puede ser una cadena vacía: {self.ability_slot!r}")
        if not isinstance(self.consumes, EffectIdentity):
            raise TypeError(f"FollowupAlternative.consumes debe ser EffectIdentity, no {self.consumes!r}")
        if not isinstance(self.stack_target, ActorRole):
            raise TypeError(f"FollowupAlternative.stack_target debe ser ActorRole, no {self.stack_target!r}")
        if self.connect_reference is None:
            object.__setattr__(self, "connect_reference", self.action_ref)
        elif not isinstance(self.connect_reference, str) or not self.connect_reference.strip():
            raise ValueError(f"FollowupAlternative.connect_reference no puede ser vacío: {self.connect_reference!r}")


@dataclass(frozen=True, slots=True)
class ControlFollowupFamily:
    """Resultado completo de `build_control_into_stack_sequences`:

    - `opening`: la secuencia de UN SOLO paso (solo control) — SIN
      `alternative_group` (no es ninguna de las alternativas, es el tramo
      compartido). Sirve para representar "todavía no se declaró qué
      follow-up ocurre" sin elegir ninguno arbitrariamente: al no
      pertenecer a ningún grupo, un `ScenarioOutcome` sobre `opening`
      estructuralmente NO PUEDE recibir una `branch_selection` (lo
      rechaza `ScenarioOutcome.__post_init__`, §A2) — nada que confirmar,
      nada que sumar.
    - `alternatives`: una `InteractionSequence` por follow-up, cada una
      con el MISMO paso de control (reutilizado, no duplicado) más su
      propio follow-up, compartiendo un único `AlternativeGroup`.
    - `pending_group` (cierre de hardening §B1): la proyección IRRESUELTA
      (`selected_id=None`, siempre) del mismo grupo — group_id y las
      alternativas disponibles, nunca cuál se eligió. Derivado
      (`field(init=False)`), nunca declarado a mano: existe para que
      `ScenarioOutcome.pending_alternatives` pueda auditar, sobre
      `opening`, qué alternativas seguían disponibles sin tener que
      simular ninguna ni elegir una por defecto.
    """

    opening: InteractionSequence
    alternatives: tuple[InteractionSequence, ...]
    pending_group: AlternativeGroup = field(init=False, default=None)  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if not isinstance(self.opening, InteractionSequence):
            raise TypeError(f"ControlFollowupFamily.opening debe ser InteractionSequence, no {self.opening!r}")
        if self.opening.alternative_group is not None:
            raise ValueError("ControlFollowupFamily.opening no puede pertenecer a ningún AlternativeGroup")
        if not isinstance(self.alternatives, tuple) or not self.alternatives:
            raise ValueError("ControlFollowupFamily.alternatives debe ser una tuple no vacía")
        first_group: AlternativeGroup | None = None
        for alt in self.alternatives:
            if not isinstance(alt, InteractionSequence):
                raise TypeError(f"ControlFollowupFamily.alternatives[] debe ser InteractionSequence, no {alt!r}")
            if alt.alternative_group is None:
                raise ValueError(
                    f"ControlFollowupFamily.alternatives[{alt.sequence_id!r}] debe pertenecer a "
                    "un AlternativeGroup"
                )
            if first_group is None:
                first_group = alt.alternative_group
            elif (
                alt.alternative_group.group_id != first_group.group_id
                or alt.alternative_group.alternative_ids != first_group.alternative_ids
            ):
                raise ValueError(
                    "ControlFollowupFamily.alternatives deben compartir el MISMO group_id/"
                    f"alternative_ids — {alt.sequence_id!r} declara {alt.alternative_group!r}, "
                    f"distinto de {first_group!r}"
                )
        object.__setattr__(
            self,
            "pending_group",
            AlternativeGroup(group_id=first_group.group_id, alternative_ids=first_group.alternative_ids),
        )

    def spec_for(self, alternative_id: str) -> InteractionSequence:
        for sequence in self.alternatives:
            if sequence.alternative_id == alternative_id:
                return sequence
        raise ValueError(
            f"{alternative_id!r} no es una alternativa registrada — disponibles: "
            f"{[sequence.alternative_id for sequence in self.alternatives]!r}"
        )


def build_control_into_stack_sequences(
    *,
    group_id: str,
    control_actor: ActorRole,
    control_step_id: str,
    control_action_ref: str,
    control_ability_slot: str,
    control_consumes: EffectIdentity,
    followups: tuple[FollowupAlternative, ...],
    sequence_id_prefix: str,
) -> ControlFollowupFamily:
    """Construye la familia completa: la secuencia `opening` (solo
    control, sin rama) y, para cada alternativa de `followups`, UNA
    `InteractionSequence` de dos pasos (control + esa alternativa) con
    `AlternativeGroup`/`alternative_id` coherentes entre sí — nunca
    sumadas (una sola se evalúa/selecciona por ejecución, ver §A2/§B4).

    Genérico: no lee conocimiento, no nombra campeones — todos los
    identificadores y referencias llegan como parámetros, ya resueltos
    por quien llama (ver `registry.py` para la instancia real)."""

    if len(followups) < 2:
        raise ValueError(
            "build_control_into_stack_sequences necesita al menos dos alternativas para que "
            "el grupo de exclusión mutua tenga sentido"
        )

    group = AlternativeGroup(group_id=group_id, alternative_ids=tuple(f.alternative_id for f in followups))

    control_step = SequenceStep(
        step_id=control_step_id,
        action_ref=control_action_ref,
        actor=control_actor,
        declared_support=Support.STRUCTURAL,
        preconditions=(
            StructuralPrecondition(PreconditionCheckKind.ACTION_CONNECTS, control_actor, control_action_ref),
            StructuralPrecondition(PreconditionCheckKind.ABILITY_READY, control_actor, control_ability_slot),
        ),
        consumes=(control_consumes,),
        postconditions=(
            StructuralPostcondition(
                PostconditionEffectKind.ABILITY_ON_COOLDOWN, control_actor, control_ability_slot
            ),
        ),
    )
    opening = InteractionSequence(sequence_id=f"{sequence_id_prefix}:opening", steps=(control_step,))

    alternatives: list[InteractionSequence] = []
    for followup in followups:
        preconditions = [
            StructuralPrecondition(
                PreconditionCheckKind.ACTION_CONNECTS, control_actor, followup.connect_reference
            )
        ]
        postconditions = [
            StructuralPostcondition(
                PostconditionEffectKind.STACK_APPLIED,
                followup.stack_target,
                followup.stack_reference,
                threshold=followup.stack_threshold,
            )
        ]
        if followup.ability_slot is not None:
            preconditions.append(
                StructuralPrecondition(PreconditionCheckKind.ABILITY_READY, control_actor, followup.ability_slot)
            )
            postconditions.append(
                StructuralPostcondition(
                    PostconditionEffectKind.ABILITY_ON_COOLDOWN, control_actor, followup.ability_slot
                )
            )

        followup_step = SequenceStep(
            step_id=followup.step_id,
            action_ref=followup.action_ref,
            actor=control_actor,  # quien sigue el follow-up es quien controló — mismo actor
            declared_support=Support.STRUCTURAL,
            preconditions=tuple(preconditions),
            consumes=(followup.consumes,),
            postconditions=tuple(postconditions),
        )

        sequence = InteractionSequence(
            sequence_id=f"{sequence_id_prefix}:{followup.alternative_id}",
            steps=(control_step, followup_step),
            alternative_group=group,
            alternative_id=followup.alternative_id,
        )
        alternatives.append(sequence)

    return ControlFollowupFamily(opening=opening, alternatives=tuple(alternatives))


def extend_family_alternatives_with_step(
    family: ControlFollowupFamily, *, extra_step: SequenceStep
) -> ControlFollowupFamily:
    """Extiende CADA alternativa de `family` (nunca `opening`) con un paso
    adicional al final — p. ej. la respuesta de un segundo actor dentro de
    la misma hipótesis (trade bidireccional). `opening` se conserva sin
    cambios: el paso extra representa una reacción a un follow-up que ya
    ocurrió, y `opening` es precisamente "todavía no se declaró cuál".

    Genérico: no sabe qué representa `extra_step` — solo reutiliza
    `SequenceStep` (fuente canónica única, ya validado) sin duplicar su
    lógica de construcción."""

    if extra_step.step_id in {step.step_id for alt in family.alternatives for step in alt.steps}:
        raise ValueError(
            f"extra_step.step_id={extra_step.step_id!r} ya existe en alguna alternativa de la "
            "familia — los step_id deben seguir siendo únicos por secuencia"
        )

    extended: list[InteractionSequence] = []
    for alt in family.alternatives:
        sequence = InteractionSequence(
            sequence_id=f"{alt.sequence_id}+{extra_step.step_id}",
            steps=(*alt.steps, extra_step),
            alternative_group=alt.alternative_group,
            alternative_id=alt.alternative_id,
        )
        extended.append(sequence)

    return ControlFollowupFamily(opening=family.opening, alternatives=tuple(extended))
