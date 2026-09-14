"""Registro mínimo de las secuencias reales Darius-Mordekaiser (v1.7,
shadow mode).

Dos familias, ambas construidas SOLO para este matchup (ver
`is_darius_mordekaiser_matchup`):

1. **Apprehend->follow-up** (microfix): Apprehend (control) habilita
   contacto -> autoataque o Decimate en zona exterior (follow-up,
   alternativas mutuamente excluyentes) aplica una carga de Hemorrhage.
2. **Trade bidireccional mínimo**: la familia anterior, extendida con UNA
   respuesta real de Mordekaiser (Obliterate) dentro de la MISMA
   hipótesis — ver `build_bidirectional_trade_registration` para la
   justificación de por qué Obliterate y no otra habilidad.

Este es el ÚNICO módulo de todo `reasoning/sequences/` que puede nombrar
un campeón — y solo para RESOLVER referencias reales contra el
conocimiento ya existente (`Champion`/`Ability`/`StackingMechanic`), nunca
para inventar un valor mecánico nuevo. Cada resolución falla
explícitamente (`ValueError`) si la referencia esperada no existe, en vez
de continuar con un supuesto silencioso — y cada hecho que este módulo
asume se re-verifica contra el conocimiento cargado, no se da por
sentado.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from lol_reasoner.domain.champion import Ability, Champion, StackingMechanic
from lol_reasoner.domain.combat_state import (
    AbilityAvailability,
    AbilityState,
    ActionContext,
    CombatState,
    RangeStatus,
    StackState,
    StackWindow,
)
from lol_reasoner.domain.enums import EffectCondition, EffectType, Support
from lol_reasoner.reasoning.scenario_builder import build_scenario_baseline
from lol_reasoner.reasoning.sequences.generic_sequences import (
    ControlFollowupFamily,
    FollowupAlternative,
    build_control_into_stack_sequences,
    extend_family_alternatives_with_step,
)
from lol_reasoner.reasoning.sequences.sequence import InteractionSequence
from lol_reasoner.reasoning.sequences.steps import (
    WHOLE_EFFECT_COMPONENT,
    ActorRole,
    EffectIdentity,
    PostconditionEffectKind,
    PreconditionCheckKind,
    SequenceStep,
    StructuralPostcondition,
    StructuralPrecondition,
)

DARIUS_ID = "darius"
MORDEKAISER_ID = "mordekaiser"

_APPREHEND_SLOT = "E"
_DECIMATE_SLOT = "Q"
_HEMORRHAGE_MECHANIC_ID = "hemorrhage"
_BASIC_ATTACK_TOKEN = "basic_attack"
_Q_OUTER_ZONE_TOKEN = "q_outer"  # referencia de conexión DISTINTA de "candidate:q" — ver §3 del microfix
_GROUP_ID = "darius_apprehend_followup"

AA_ALTERNATIVE_ID = "aa"
Q_ALTERNATIVE_ID = "q"

_MORDEKAISER_RESPONSE_SLOT = "Q"  # Obliterate
_DARKNESS_RISE_MECHANIC_ID = "darkness_rise"
# NOTA (cierre de hardening §B4): esta ronda ya NO declara un invalidador
# "apprehend_interrupt" reutilizando el CC breve de Apprehend contra la
# respuesta de Mordekaiser — ver el docstring de `response_step` en
# `build_bidirectional_trade_registration` para la cronología corregida.

_PERFORMER_LEVEL = 3  # E y Q disponibles desde EARLY_LANE, para ambos campeones


def is_darius_mordekaiser_matchup(candidate: Champion, enemy: Champion) -> bool:
    """SOLO este matchup ejecuta la secuencia — cualquier otro par
    devuelve `False` sin construir nada."""

    return {candidate.id, enemy.id} == {DARIUS_ID, MORDEKAISER_ID}


def action_ref_for(role: ActorRole, slot_or_token: str) -> str:
    """Convención ÚNICA de `action_ref`, compartida por todo este módulo
    y por quien construye el escenario baseline — para que dos lados no
    puedan derivar el string por separado y desalinearse."""

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
    """Todo lo que el evaluador/orquestación necesitan para esta familia
    en UNA orientación concreta: qué rol ocupa Darius, las referencias de
    acción/slot ya resueltas (incluida la de conexión de la zona exterior
    de Q, DISTINTA de la de su rango de casteo), y la `ControlFollowupFamily`
    (opening + una `GenericSequenceSpec` por alternativa)."""

    darius_role: ActorRole
    mordekaiser_role: ActorRole
    apprehend_action_ref: str
    apprehend_slot: str
    decimate_action_ref: str
    decimate_slot: str
    decimate_outer_zone_action_ref: str
    basic_attack_action_ref: str
    stack_reference: str
    family: ControlFollowupFamily

    def spec_for(self, alternative_id: str) -> InteractionSequence:
        return self.family.spec_for(alternative_id)


def build_apprehend_followup_registration(
    *, darius: Champion, darius_role: ActorRole
) -> ApprehendFollowupRegistration:
    """Resuelve la instancia real Darius/Hemorrhage y construye la familia
    (autoataque, Decimate en zona exterior) para la orientación en la que
    Darius ocupa `darius_role` en el `CombatState`.

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
    decimate_outer_zone_action_ref = action_ref_for(darius_role, _Q_OUTER_ZONE_TOKEN)
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
        # el alcance de autoataque ES su propia conexión: sin zona aparte
        connect_reference=basic_attack_action_ref,
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
        # estar en rango de casteo de Q NO implica haber conectado en su
        # zona exterior — referencia de conexión DISTINTA y propia (§3).
        connect_reference=decimate_outer_zone_action_ref,
    )

    family = build_control_into_stack_sequences(
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
        decimate_outer_zone_action_ref=decimate_outer_zone_action_ref,
        basic_attack_action_ref=basic_attack_action_ref,
        stack_reference=hemorrhage.id,
        family=family,
    )


def build_apprehend_followup_baseline(
    registration: ApprehendFollowupRegistration,
    *,
    range_statuses: Mapping[str, RangeStatus] | None = None,
) -> CombatState:
    """Escenario mínimo: nivel del actor que ejecuta, disponibilidad de
    E/Q, `ActionContext` de las TRES referencias de conexión relevantes
    (Apprehend, autoataque, zona exterior de Q — cada una independiente,
    nunca inferida de otra), y el stack inicial de Hemorrhage en quien lo
    recibe.

    `range_statuses` declara EXPLÍCITAMENTE el `range_status` de cada
    referencia — cualquiera no mencionada queda `UNKNOWN` (nunca se
    rellena con el mejor caso). Sin overrides, las tres quedan `UNKNOWN`."""

    range_statuses = range_statuses or {}
    relevant_refs = (
        registration.apprehend_action_ref,
        registration.basic_attack_action_ref,
        registration.decimate_outer_zone_action_ref,
    )
    action_contexts = {
        ref: ActionContext(action_ref=ref, range_status=range_statuses.get(ref, RangeStatus.UNKNOWN))
        for ref in relevant_refs
    }

    performer_abilities = {
        registration.apprehend_slot: AbilityState(rank=1, availability=AbilityAvailability.READY),
        registration.decimate_slot: AbilityState(rank=1, availability=AbilityAvailability.READY),
    }
    receiver_stacks = {registration.stack_reference: StackState(count=0, window=StackWindow.UNKNOWN)}

    if registration.darius_role is ActorRole.CANDIDATE:
        return build_scenario_baseline(
            candidate_level=_PERFORMER_LEVEL,
            candidate_abilities=performer_abilities,
            enemy_stacks=receiver_stacks,
            action_contexts=action_contexts,
        )
    return build_scenario_baseline(
        enemy_level=_PERFORMER_LEVEL,
        enemy_abilities=performer_abilities,
        candidate_stacks=receiver_stacks,
        action_contexts=action_contexts,
    )


# ---------------------------------------------------------------------------
# Familia 2: trade bidireccional mínimo (Apprehend-followup + respuesta)
# ---------------------------------------------------------------------------


def _require_mordekaiser_response(mordekaiser: Champion) -> tuple[Ability, StackingMechanic]:
    """Resuelve y verifica Obliterate (Q) + Darkness Rise contra el
    conocimiento cargado — ver `build_bidirectional_trade_registration`
    para la justificación de por qué esta es la respuesta elegida.

    Verifica AMBAS causas reales que justifican elegir esta respuesta
    (cierre de hardening §B6): `DAMAGE` (al menos un efecto, condicionado
    o no) Y `STACK_APPLICATION` condicionado a `ON_HIT` — nunca se declara
    una justificación que la propia base de conocimiento no sostiene."""

    obliterate = _require_ability(mordekaiser, _MORDEKAISER_RESPONSE_SLOT)
    darkness_rise = _require_stacking_mechanic(mordekaiser, _DARKNESS_RISE_MECHANIC_ID)

    if EffectType.DAMAGE not in obliterate.effect_types():
        raise ValueError(f"{obliterate.name!r} ya no tiene ningún efecto DAMAGE — la referencia de conocimiento cambió")
    if EffectType.STACK_APPLICATION not in obliterate.effect_types():
        raise ValueError(f"{obliterate.name!r} ya no aplica STACK_APPLICATION — la referencia de conocimiento cambió")
    on_hit_stack_effects = [
        effect
        for effect in obliterate.effects_of(EffectType.STACK_APPLICATION)
        if EffectCondition.ON_HIT in effect.conditions
    ]
    if not on_hit_stack_effects:
        raise ValueError(f"{obliterate.name!r} no tiene un efecto STACK_APPLICATION condicionado a ON_HIT")
    if obliterate.slot not in darkness_rise.applied_by:
        raise ValueError(
            f"{darkness_rise.id!r} ya no admite el slot {obliterate.slot!r} como fuente — la "
            "referencia de conocimiento cambió"
        )

    return obliterate, darkness_rise


@dataclass(frozen=True, slots=True)
class BidirectionalTradeRegistration:
    """La familia Apprehend-followup extendida con la respuesta de
    Mordekaiser — mismas alternativas (aa/q), cada una con un tercer paso
    (`response_obliterate`) al final."""

    apprehend_followup: ApprehendFollowupRegistration
    mordekaiser_response_action_ref: str
    mordekaiser_response_slot: str
    mordekaiser_stack_reference: str
    mordekaiser_stack_threshold: int
    family: ControlFollowupFamily

    def spec_for(self, alternative_id: str) -> InteractionSequence:
        return self.family.spec_for(alternative_id)


def build_bidirectional_trade_registration(
    *, darius: Champion, mordekaiser: Champion, darius_role: ActorRole
) -> BidirectionalTradeRegistration:
    """Extiende la familia Apprehend-followup con LA respuesta elegida de
    Mordekaiser para ESTA vertical: **Obliterate (Q)**, una respuesta
    OFENSIVA.

    Justificación de Obliterate (no autoataque): de las cuatro habilidades
    tempranas de Mordekaiser, Obliterate es la única con un efecto
    `DAMAGE` Y `STACK_APPLICATION` (`ON_HIT`) que además alimenta su
    PROPIA `StackingMechanic` (`darkness_rise`, `applied_by` incluye su
    slot) — una contrarrespuesta mecánicamente real y no trivial, no un
    autoataque genérico.

    **Por qué no `W` esta ronda (corrección de hardening §B5)**: `W`
    (Indestructible) NO fue descartada por ser estructuralmente inválida
    como respuesta — sí es una respuesta DEFENSIVA activa real dentro de
    un trade (acumula/convierte escudo real, un efecto mecánico legítimo).
    Se excluyó únicamente porque esta vertical eligió deliberadamente
    representar un contra-golpe OFENSIVO (Obliterate demuestra daño,
    aplicación de stack Y cooldown en un solo paso, más rico para esta
    prueba). Nada en el conocimiento cargado ni en este módulo exige que
    una respuesta tenga que impactar al rival para ser válida — `W` sigue
    disponible como una rama defensiva futura, no implementada en esta
    ronda (ver `test_w_is_documented_as_a_future_defensive_branch_not_structurally_invalid`).
    Mordekaiser es `RESOURCELESS`, así que no hace falta modelar maná para
    poder castear la respuesta elegida.
    """

    base = build_apprehend_followup_registration(darius=darius, darius_role=darius_role)
    if mordekaiser.id != MORDEKAISER_ID:
        raise ValueError(f"build_bidirectional_trade_registration espera a Mordekaiser, recibió {mordekaiser.id!r}")

    obliterate, darkness_rise = _require_mordekaiser_response(mordekaiser)

    # Auditoría de identidad de stacks (cierre de hardening §B8):
    # `StackingMechanic.id` NO es único globalmente entre campeones — solo
    # local por campeón (knowledge/loader.py no valida colisiones entre
    # YAML de campeones distintos). Este trade es el ÚNICO lugar de todo
    # el código que combina la mecánica RECIBIDA de un campeón
    # (`base.stack_reference`, Hemorrhage) con la PROPIA de otro
    # (`darkness_rise.id`) en el MISMO `ActorState.stacks` de Mordekaiser
    # (ver `build_bidirectional_trade_baseline`) — si algún día coincidieran,
    # se fusionarían silenciosamente en una sola entrada. Namespacing
    # global (p. ej. `champion_id:mechanic_id`) tocaría `domain.champion`,
    # el schema de conocimiento y las reglas de stacking — fuera de alcance
    # esta ronda (LÍMITES) — así que la mitigación mínima es esta guarda
    # explícita en el único punto real de colisión, que falla ruidosamente
    # en vez de fusionar en silencio.
    if base.stack_reference == darkness_rise.id:
        raise ValueError(
            f"Colisión de StackingMechanic.id detectada: {base.stack_reference!r} identificaría a "
            "la vez la mecánica recibida de Darius y la propia de Mordekaiser en el mismo "
            "ActorState.stacks — StackingMechanic.id no es único globalmente entre campeones; "
            "esta construcción no puede continuar sin fusionar dos mecánicas distintas"
        )

    mordekaiser_role = base.mordekaiser_role
    response_action_ref = action_ref_for(mordekaiser_role, obliterate.slot)
    response_slot = obliterate.slot.lower()

    response_step = SequenceStep(
        step_id="response_obliterate",
        action_ref=response_action_ref,
        actor=mordekaiser_role,
        declared_support=Support.STRUCTURAL,
        # Cronología corregida (cierre de hardening §B4): la secuencia es
        # Apprehend -> follow-up de Darius -> ESTA respuesta, evaluada
        # DESPUÉS de que el follow-up ya ocurrió. El breve CC/interrupt de
        # Apprehend (BRIEF_CC/INTERRUPT) ya se resolvió para entonces — no
        # es coherente reusarlo como si siguiera activo para bloquear un
        # tercer paso posterior, y este módulo no simula tiempo para saber
        # si en cambio expiró. La respuesta se bloquea SOLO por sus propias
        # precondiciones reales: alcance (`ACTION_CONNECTS`) y
        # disponibilidad de la habilidad (`ABILITY_READY`) — nunca por un
        # invalidador de un control que ya pasó. Un futuro "response
        # window" contextual (ligado a esta rama del trade, no al CC
        # inicial) queda fuera de esta ronda.
        preconditions=(
            StructuralPrecondition(PreconditionCheckKind.ACTION_CONNECTS, mordekaiser_role, response_action_ref),
            StructuralPrecondition(PreconditionCheckKind.ABILITY_READY, mordekaiser_role, response_slot),
        ),
        # Ambas causas reales verificadas contra el conocimiento cargado
        # (cierre de hardening §B6): el daño de Q Y la aplicación de
        # Darkness Rise — la selección de esta respuesta se justificó por
        # DAMAGE + STACK_APPLICATION (ver docstring de arriba), así que
        # ambas identidades deben quedar trazables acá, nunca solo una.
        # No se suman como "doble ventaja": son dos efectos reales
        # distintos, cada uno con su propio causal_role.
        consumes=(
            EffectIdentity(
                fact_ref=f"{mordekaiser.id}:{response_slot}",
                causal_role="damage",
                component=WHOLE_EFFECT_COMPONENT,
            ),
            EffectIdentity(
                fact_ref=f"{mordekaiser.id}:{response_slot}",
                causal_role="stack_application",
                component=EffectCondition.ON_HIT.value,
            ),
        ),
        postconditions=(
            StructuralPostcondition(PostconditionEffectKind.ABILITY_ON_COOLDOWN, mordekaiser_role, response_slot),
            StructuralPostcondition(
                PostconditionEffectKind.STACK_APPLIED,
                mordekaiser_role,  # Darkness Rise se acumula en el propio Mordekaiser, no en Darius
                darkness_rise.id,
                threshold=darkness_rise.threshold,
            ),
        ),
    )

    family = extend_family_alternatives_with_step(base.family, extra_step=response_step)

    return BidirectionalTradeRegistration(
        apprehend_followup=base,
        mordekaiser_response_action_ref=response_action_ref,
        mordekaiser_response_slot=response_slot,
        mordekaiser_stack_reference=darkness_rise.id,
        mordekaiser_stack_threshold=darkness_rise.threshold,
        family=family,
    )


def build_bidirectional_trade_baseline(
    registration: BidirectionalTradeRegistration,
    *,
    range_statuses: Mapping[str, RangeStatus] | None = None,
    mordekaiser_initial_darkness_rise_count: int | None = 0,
) -> CombatState:
    """Escenario mínimo del trade: todo lo del baseline de
    Apprehend-followup, más disponibilidad de Obliterate, su propio
    `ActionContext`, y el stack inicial de Darkness Rise EN Mordekaiser
    (acumulación propia, no recibida).

    La respuesta YA NO declara ningún invalidador (cierre de hardening
    §B4: la cronología de este trade nunca justificó reusar el CC breve
    de Apprehend contra un tercer paso posterior) — este baseline no
    declara ni rellena ninguno por default; `response_obliterate` se
    bloquea únicamente por `ACTION_CONNECTS`/`ABILITY_READY`, igual que
    cualquier otro paso de esta familia.

    `mordekaiser_initial_darkness_rise_count=None` deja el conteo inicial
    genuinamente desconocido (para probar que una aplicación sobre un
    conteo `unknown` no inventa si cruzó el umbral)."""

    base = registration.apprehend_followup
    range_statuses = range_statuses or {}

    relevant_refs = (base.apprehend_action_ref, base.basic_attack_action_ref, base.decimate_outer_zone_action_ref)
    action_contexts = {
        ref: ActionContext(action_ref=ref, range_status=range_statuses.get(ref, RangeStatus.UNKNOWN))
        for ref in relevant_refs
    }
    action_contexts[registration.mordekaiser_response_action_ref] = ActionContext(
        action_ref=registration.mordekaiser_response_action_ref,
        range_status=range_statuses.get(registration.mordekaiser_response_action_ref, RangeStatus.UNKNOWN),
    )

    darius_abilities = {
        base.apprehend_slot: AbilityState(rank=1, availability=AbilityAvailability.READY),
        base.decimate_slot: AbilityState(rank=1, availability=AbilityAvailability.READY),
    }
    mordekaiser_abilities = {
        registration.mordekaiser_response_slot: AbilityState(rank=1, availability=AbilityAvailability.READY),
    }
    darkness_rise_window = (
        StackWindow.UNKNOWN
        if mordekaiser_initial_darkness_rise_count in (None, 0)
        else StackWindow.ACTIVE
    )
    mordekaiser_stacks = {
        base.stack_reference: StackState(count=0, window=StackWindow.UNKNOWN),  # Hemorrhage RECIBIDO
        registration.mordekaiser_stack_reference: StackState(
            count=mordekaiser_initial_darkness_rise_count, window=darkness_rise_window
        ),
    }

    if base.darius_role is ActorRole.CANDIDATE:
        return build_scenario_baseline(
            candidate_level=_PERFORMER_LEVEL,
            candidate_abilities=darius_abilities,
            enemy_level=_PERFORMER_LEVEL,
            enemy_abilities=mordekaiser_abilities,
            enemy_stacks=mordekaiser_stacks,
            action_contexts=action_contexts,
        )
    return build_scenario_baseline(
        enemy_level=_PERFORMER_LEVEL,
        enemy_abilities=darius_abilities,
        candidate_level=_PERFORMER_LEVEL,
        candidate_abilities=mordekaiser_abilities,
        candidate_stacks=mordekaiser_stacks,
        action_contexts=action_contexts,
    )
