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
"""

from __future__ import annotations

from dataclasses import dataclass

from lol_reasoner.domain.enums import Support
from lol_reasoner.reasoning.sequences.evaluator import (
    PostconditionEffectKind,
    PreconditionCheckKind,
    StepEvaluationSpec,
    StructuralPostcondition,
    StructuralPrecondition,
)
from lol_reasoner.reasoning.sequences.sequence import AlternativeGroup, InteractionSequence
from lol_reasoner.reasoning.sequences.steps import ActorRole, EffectIdentity, SequenceStep


@dataclass(frozen=True, slots=True)
class FollowupAlternative:
    """UNA alternativa de follow-up del mismo punto de decisión (p. ej.
    autoataque o una habilidad concreta) — datos puros, sin lógica.

    `ability_slot=None` representa un follow-up sin `AbilityState` propio
    (p. ej. un autoataque: no tiene rango de puntos ni cooldown modelado
    en `domain.combat_state`) — en ese caso no se declara precondición ni
    postcondición de disponibilidad para él, solo la de rango.
    """

    alternative_id: str
    step_id: str
    action_ref: str
    ability_slot: str | None
    consumes: EffectIdentity
    stack_target: ActorRole
    stack_reference: str

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


@dataclass(frozen=True, slots=True)
class GenericSequenceSpec:
    """Una `InteractionSequence` YA evaluable: sus pasos y el
    `StepEvaluationSpec` de cada uno, alineados 1:1 en el mismo orden."""

    sequence: InteractionSequence
    step_specs: tuple[StepEvaluationSpec, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.sequence, InteractionSequence):
            raise TypeError(f"GenericSequenceSpec.sequence debe ser InteractionSequence, no {self.sequence!r}")
        if len(self.step_specs) != len(self.sequence.steps):
            raise ValueError(
                "GenericSequenceSpec.step_specs debe tener exactamente un StepEvaluationSpec por "
                f"paso de sequence.steps ({len(self.sequence.steps)}), recibió {len(self.step_specs)}"
            )
        for step, spec in zip(self.sequence.steps, self.step_specs, strict=True):
            if spec.step is not step:
                raise ValueError(
                    "GenericSequenceSpec.step_specs debe estar alineado 1:1 y en el mismo orden "
                    f"que sequence.steps (desalineado en step_id={step.step_id!r})"
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
) -> tuple[GenericSequenceSpec, ...]:
    """Construye, para cada alternativa de `followups`, UNA
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
        consumes=(control_consumes,),
    )
    control_spec = StepEvaluationSpec(
        step=control_step,
        declared_support=Support.STRUCTURAL,
        preconditions=(
            StructuralPrecondition(PreconditionCheckKind.ACTION_IN_RANGE, control_actor, control_action_ref),
            StructuralPrecondition(PreconditionCheckKind.ABILITY_READY, control_actor, control_ability_slot),
        ),
        postconditions=(
            StructuralPostcondition(
                PostconditionEffectKind.ABILITY_ON_COOLDOWN, control_actor, control_ability_slot
            ),
        ),
    )

    specs: list[GenericSequenceSpec] = []
    for followup in followups:
        followup_step = SequenceStep(
            step_id=followup.step_id,
            action_ref=followup.action_ref,
            actor=control_actor,  # quien sigue el follow-up es quien controló — mismo actor
            consumes=(followup.consumes,),
        )

        preconditions = [
            StructuralPrecondition(PreconditionCheckKind.ACTION_IN_RANGE, control_actor, followup.action_ref)
        ]
        postconditions = [
            StructuralPostcondition(
                PostconditionEffectKind.STACK_APPLIED, followup.stack_target, followup.stack_reference
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

        followup_spec = StepEvaluationSpec(
            step=followup_step,
            declared_support=Support.STRUCTURAL,
            preconditions=tuple(preconditions),
            postconditions=tuple(postconditions),
        )

        sequence = InteractionSequence(
            sequence_id=f"{sequence_id_prefix}:{followup.alternative_id}",
            steps=(control_step, followup_step),
            alternative_group=group,
            alternative_id=followup.alternative_id,
        )
        specs.append(GenericSequenceSpec(sequence=sequence, step_specs=(control_spec, followup_spec)))

    return tuple(specs)
