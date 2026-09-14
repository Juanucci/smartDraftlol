"""Registro mínimo de la primera secuencia real (v1.7, shadow mode).

Instancia concreta de `generic_sequences.build_control_into_stack_sequences`
para Darius vs Mordekaiser: Apprehend (control) habilita contacto ->
autoataque o Decimate (follow-up, alternativas mutuamente excluyentes)
aplica una carga de Hemorrhage. SOLO este matchup — cualquier otro par de
campeones no ejecuta nada acá (ver `is_darius_mordekaiser_matchup`).

Este es el ÚNICO módulo de todo `reasoning/sequences/` que puede nombrar
un campeón — y solo para RESOLVER referencias reales contra el
conocimiento ya existente (`Champion`/`Ability`/`StackingMechanic`), nunca
para inventar un valor mecánico nuevo. Cada resolución falla
explícitamente (`ValueError`) si la referencia esperada no existe, en vez
de continuar con un supuesto silencioso — y cada hecho que este módulo
asume (que Apprehend no aplica Hemorrhage, que Decimate sí, que Hemorrhage
admite autoataque y Q como fuentes) se re-verifica contra el conocimiento
cargado, no se da por sentado.
"""

from __future__ import annotations

from dataclasses import dataclass

from lol_reasoner.domain.champion import Ability, Champion, StackingMechanic
from lol_reasoner.domain.enums import EffectCondition, EffectType
from lol_reasoner.reasoning.sequences.generic_sequences import (
    FollowupAlternative,
    GenericSequenceSpec,
    build_control_into_stack_sequences,
)
from lol_reasoner.reasoning.sequences.steps import WHOLE_EFFECT_COMPONENT, ActorRole, EffectIdentity

DARIUS_ID = "darius"
MORDEKAISER_ID = "mordekaiser"

_APPREHEND_SLOT = "E"
_DECIMATE_SLOT = "Q"
_HEMORRHAGE_MECHANIC_ID = "hemorrhage"
_BASIC_ATTACK_TOKEN = "basic_attack"
_GROUP_ID = "darius_apprehend_followup"

AA_ALTERNATIVE_ID = "aa"
Q_ALTERNATIVE_ID = "q"


def is_darius_mordekaiser_matchup(candidate: Champion, enemy: Champion) -> bool:
    """SOLO este matchup ejecuta la secuencia — cualquier otro par
    devuelve `False` sin construir nada."""

    return {candidate.id, enemy.id} == {DARIUS_ID, MORDEKAISER_ID}


def action_ref_for(role: ActorRole, slot_or_token: str) -> str:
    """Convención ÚNICA de `action_ref`, compartida por el registro y por
    quien construye el escenario baseline — para que ninguno de los dos
    lados pueda derivar el string por separado y desalinearse."""

    return f"{role.value}:{slot_or_token.lower()}"


def _require_ability(champion: Champion, slot: str) -> Ability:
    ability = champion.ability(slot)
    if ability is None:
        raise ValueError(
            f"Referencia mecánica requerida ausente: {champion.id!r} no tiene una habilidad en "
            f"el slot {slot!r} — no se puede construir la secuencia sin ella"
        )
    return ability


def _require_stacking_mechanic(champion: Champion, mechanic_id: str) -> StackingMechanic:
    for mechanic in champion.stacking_mechanics:
        if mechanic.id == mechanic_id:
            return mechanic
    raise ValueError(
        f"Referencia mecánica requerida ausente: {champion.id!r} no declara una StackingMechanic "
        f"con id {mechanic_id!r} — no se puede construir la secuencia sin ella"
    )


@dataclass(frozen=True, slots=True)
class ApprehendFollowupRegistration:
    """Todo lo que `scenario_builder`/orquestación necesitan para evaluar
    esta secuencia en UNA orientación concreta: qué rol ocupa Darius, las
    referencias de acción/slot ya resueltas, y las `GenericSequenceSpec`
    (una por alternativa de follow-up)."""

    darius_role: ActorRole
    mordekaiser_role: ActorRole
    apprehend_action_ref: str
    apprehend_slot: str
    decimate_action_ref: str
    decimate_slot: str
    basic_attack_action_ref: str
    stack_reference: str
    sequence_specs: tuple[GenericSequenceSpec, ...]

    def spec_for(self, alternative_id: str) -> GenericSequenceSpec:
        for spec in self.sequence_specs:
            if spec.sequence.alternative_id == alternative_id:
                return spec
        raise ValueError(
            f"{alternative_id!r} no es una alternativa registrada — disponibles: "
            f"{[s.sequence.alternative_id for s in self.sequence_specs]!r}"
        )


def build_apprehend_followup_registration(
    *, darius: Champion, darius_role: ActorRole
) -> ApprehendFollowupRegistration:
    """Resuelve la instancia real Darius/Hemorrhage y construye las
    `GenericSequenceSpec` (autoataque, Decimate) para la orientación en la
    que Darius ocupa `darius_role` en el `CombatState`.

    `darius_role=ActorRole.ENEMY` es la orientación inversa del matchup
    (Mordekaiser como candidate) — la secuencia sigue siendo "Darius hace
    Apprehend y aplica Hemorrhage", solo que Darius ocupa el rol `enemy`
    del `CombatState` en esa orientación.
    """

    if darius.id != DARIUS_ID:
        raise ValueError(f"build_apprehend_followup_registration espera a Darius, recibió {darius.id!r}")
    if not isinstance(darius_role, ActorRole):
        raise TypeError(f"darius_role debe ser ActorRole, no {darius_role!r}")

    apprehend = _require_ability(darius, _APPREHEND_SLOT)
    decimate = _require_ability(darius, _DECIMATE_SLOT)
    hemorrhage = _require_stacking_mechanic(darius, _HEMORRHAGE_MECHANIC_ID)

    # --- Aserciones estructurales contra el conocimiento existente ---
    # Nunca inventadas: si alguna dejara de ser cierta en el YAML, esta
    # función debe fallar explícitamente en vez de construir una
    # secuencia que ya no representa lo que declara (§B2/§B5).
    if EffectType.STACK_APPLICATION in apprehend.effect_types():
        raise ValueError(
            f"{apprehend.name!r} ya aplica STACK_APPLICATION en el conocimiento cargado — "
            "esta secuencia asume que el control NUNCA aplica el stack por sí mismo"
        )
    if EffectType.STACK_APPLICATION not in decimate.effect_types():
        raise ValueError(f"{decimate.name!r} ya no aplica STACK_APPLICATION — la referencia de conocimiento cambió")
    if _BASIC_ATTACK_TOKEN not in hemorrhage.applied_by:
        raise ValueError(
            f"{hemorrhage.id!r} ya no admite {_BASIC_ATTACK_TOKEN!r} como fuente — la referencia "
            "de conocimiento cambió"
        )
    if decimate.slot not in hemorrhage.applied_by:
        raise ValueError(
            f"{hemorrhage.id!r} ya no admite el slot {decimate.slot!r} como fuente — la "
            "referencia de conocimiento cambió"
        )

    outer_zone_stack_effects = [
        effect
        for effect in decimate.effects_of(EffectType.STACK_APPLICATION)
        if EffectCondition.ON_OUTER_ZONE in effect.conditions
    ]
    if not outer_zone_stack_effects:
        raise ValueError(
            f"{decimate.name!r} no tiene un efecto STACK_APPLICATION condicionado a "
            "ON_OUTER_ZONE — la referencia de conocimiento cambió"
        )

    mordekaiser_role = ActorRole.ENEMY if darius_role is ActorRole.CANDIDATE else ActorRole.CANDIDATE

    apprehend_action_ref = action_ref_for(darius_role, _APPREHEND_SLOT)
    decimate_action_ref = action_ref_for(darius_role, _DECIMATE_SLOT)
    basic_attack_action_ref = action_ref_for(darius_role, _BASIC_ATTACK_TOKEN)

    control_consumes = EffectIdentity(
        fact_ref=f"{darius.id}:{_APPREHEND_SLOT.lower()}",
        causal_role="displacement",
        component=WHOLE_EFFECT_COMPONENT,
    )

    aa_followup = FollowupAlternative(
        alternative_id=AA_ALTERNATIVE_ID,
        step_id="followup_basic_attack",
        action_ref=basic_attack_action_ref,
        ability_slot=None,
        consumes=EffectIdentity(
            fact_ref=f"{darius.id}:{_BASIC_ATTACK_TOKEN}",
            causal_role="stack_application",
            component=WHOLE_EFFECT_COMPONENT,
        ),
        stack_target=mordekaiser_role,
        stack_reference=hemorrhage.id,
    )
    q_followup = FollowupAlternative(
        alternative_id=Q_ALTERNATIVE_ID,
        step_id="followup_decimate",
        action_ref=decimate_action_ref,
        ability_slot=_DECIMATE_SLOT.lower(),
        consumes=EffectIdentity(
            fact_ref=f"{darius.id}:{_DECIMATE_SLOT.lower()}",
            causal_role="stack_application",
            component=EffectCondition.ON_OUTER_ZONE.value,
        ),
        stack_target=mordekaiser_role,
        stack_reference=hemorrhage.id,
    )

    sequence_specs = build_control_into_stack_sequences(
        group_id=_GROUP_ID,
        control_actor=darius_role,
        control_step_id="control_apprehend",
        control_action_ref=apprehend_action_ref,
        control_ability_slot=_APPREHEND_SLOT.lower(),
        control_consumes=control_consumes,
        followups=(aa_followup, q_followup),
        sequence_id_prefix=f"{_GROUP_ID}:{darius_role.value}",
    )

    return ApprehendFollowupRegistration(
        darius_role=darius_role,
        mordekaiser_role=mordekaiser_role,
        apprehend_action_ref=apprehend_action_ref,
        apprehend_slot=_APPREHEND_SLOT.lower(),
        decimate_action_ref=decimate_action_ref,
        decimate_slot=_DECIMATE_SLOT.lower(),
        basic_attack_action_ref=basic_attack_action_ref,
        stack_reference=hemorrhage.id,
        sequence_specs=sequence_specs,
    )
