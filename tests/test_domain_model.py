"""Tests semánticos sobre la estructura del KB (hito 1.5, puntos 1-2, 7-11).

Verifican el modelo de dominio en sí — no la traza — comprobando que la
representación estructural captura correctamente los hechos que el
brief exigió, sin depender de que un substring aparezca en un texto.
"""

from __future__ import annotations

from lol_reasoner.domain.enums import EffectCondition, EffectType, ResourceType, TacticalUse


def test_darius_and_mordekaiser_have_all_five_slots(champions):
    for champ in champions.values():
        assert {a.slot for a in champ.abilities} == {"P", "Q", "W", "E", "R"}, champ.id


def test_at_least_one_ability_has_multiple_distinct_effect_types(darius):
    w = darius.ability("W")
    assert len(w.effect_types()) >= 3, "la W de Darius debe representar varios efectos distintos"


# --- punto 8: la W de Darius representa slow, auto-reset y aceleración de stacks ---


def test_darius_w_represents_slow_autoreset_and_stack_acceleration(darius):
    from lol_reasoner.domain.enums import Phase
    from lol_reasoner.reasoning.rules.stacking import accelerator_abilities

    w = darius.ability("W")
    types = w.effect_types()
    assert EffectType.SLOW in types
    assert EffectType.AUTO_ATTACK_RESET in types
    assert EffectType.EMPOWER_NEXT_ATTACK in types

    hemorrhage = next(m for m in darius.stacking_mechanics if m.id == "hemorrhage")
    accel_slots = {a.slot for a in accelerator_abilities(darius, hemorrhage, Phase.EARLY_LANE)}
    assert "W" in accel_slots, "W debe ser detectada estructuralmente como aceleradora, no declarada a mano"


def test_darius_w_does_not_duplicate_stack_application(darius):
    """W potencia/resetea el ataque básico, pero NO debe declarar su
    propio efecto STACK_APPLICATION: el golpe que aplica la carga es el
    ataque básico (ya contado en applied_by), no un segundo evento."""

    w = darius.ability("W")
    assert EffectType.STACK_APPLICATION not in w.effect_types()


# --- punto 9/10: la Q de Darius representa zona exterior/interior condicionalmente ---


def test_darius_q_outer_zone_heals_and_applies_stack_conditionally(darius):
    q = darius.ability("Q")
    heals = q.effects_of(EffectType.HEAL)
    assert heals, "Decimate debe tener un efecto de curación"
    assert all(EffectCondition.ON_OUTER_ZONE in h.conditions for h in heals), "la curación debe ser condicional al filo exterior"

    stack_effects = q.effects_of(EffectType.STACK_APPLICATION)
    assert stack_effects, "Decimate debe poder aplicar una carga de Hemorrhage"
    assert all(EffectCondition.ON_OUTER_ZONE in s.conditions for s in stack_effects), "la carga debe ser condicional al filo exterior"


def test_darius_q_inner_zone_denies_value(darius):
    q = darius.ability("Q")
    outer_damage = [e for e in q.effects_of(EffectType.DAMAGE) if EffectCondition.ON_OUTER_ZONE in e.conditions]
    inner_damage = [e for e in q.effects_of(EffectType.DAMAGE) if EffectCondition.ON_INNER_ZONE in e.conditions]
    assert outer_damage and inner_damage
    assert max(e.magnitude for e in inner_damage) < max(e.magnitude for e in outer_damage)

    # la zona interior no debe traer curación ni carga: eso es lo que "niega" su valor
    inner_effects_have_heal_or_stack = any(
        (EffectCondition.ON_INNER_ZONE in e.conditions) and e.type in (EffectType.HEAL, EffectType.STACK_APPLICATION)
        for e in q.effects
    )
    assert not inner_effects_have_heal_or_stack


# --- punto 7: Apprehend no aplica Hemorrhage y no es desplazamiento propio ---


def test_apprehend_is_not_a_self_dash_and_does_not_apply_hemorrhage(darius):
    e = darius.ability("E")
    types = e.effect_types()
    assert EffectType.SELF_DASH not in types
    assert EffectType.STACK_APPLICATION not in types
    assert EffectType.DISPLACE_ENEMY in types
    assert TacticalUse.SUSTAIN not in e.tactical_uses  # no es una herramienta de disengage/sustain


def test_apprehend_has_no_disengage_tactical_use(darius):
    e = darius.ability("E")
    # DISENGAGE ni siquiera es un TacticalUse activo en este hito (ver
    # domain/enums.py); su ausencia total del vocabulario activo es la
    # afirmación de que Apprehend (o cualquier otra habilidad) no puede
    # taggearse como tal todavía.
    assert not any(u.value == "disengage" for u in TacticalUse)


# --- punto 11: Darkness Rise se activa con 3 impactos y no es un escudo ---


def test_darkness_rise_activates_at_three_hits_and_is_not_a_shield(mordekaiser):
    mechanic = next(m for m in mordekaiser.stacking_mechanics if m.id == "darkness_rise")
    assert mechanic.threshold == 3

    p = mordekaiser.ability("P")
    assert EffectType.SHIELD_FROM_STORED not in p.effect_types()
    assert EffectType.STACK_APPLICATION in p.effect_types()

    reward_types = {e.type for e in mechanic.reward_effects}
    assert EffectType.AURA_DAMAGE in reward_types
    assert EffectType.MOVEMENT_SPEED in reward_types
    assert EffectType.SHIELD_FROM_STORED not in reward_types


def test_darkness_rise_is_not_fed_by_w(mordekaiser):
    """La W de Mordekaiser no debe figurar como fuente de Darkness Rise:
    Indestructible no impacta al enemigo."""

    mechanic = next(m for m in mordekaiser.stacking_mechanics if m.id == "darkness_rise")
    assert "W" not in mechanic.applied_by


def test_indestructible_does_not_remove_stacks(mordekaiser):
    """No existe ningún EffectType que "quite" cargas de una StackingMechanic
    en todo el vocabulario activo: la ausencia estructural es la garantía,
    no un chequeo puntual sobre W."""

    stack_removing_types = {"remove_stack", "reset_stack", "clear_stack"}
    assert not (stack_removing_types & {t.value for t in EffectType})


# --- punto 13: Mordekaiser tiene poke sin maná ---


def test_mordekaiser_is_resourceless_and_q_is_poke(mordekaiser):
    assert mordekaiser.casting_resource == ResourceType.RESOURCELESS
    q = mordekaiser.ability("Q")
    assert TacticalUse.POKE in q.tactical_uses
    assert EffectType.SLOW not in q.effect_types(), "no se debe inventar un slow en Q"


# --- v1.6.1: Decimate no es una herramienta de poke ---


def test_decimate_is_not_a_poke_tool(darius):
    """Decimate es un intercambio cuerpo a cuerpo con filo exterior, no
    poke a distancia. Tratarla como poke hacía que el motor describiera a
    Darius como campeón de poke y que un eje editorial de sustain rival lo
    "licuara"."""

    q = darius.ability("Q")
    assert TacticalUse.POKE not in q.tactical_uses
    # pero conserva todo lo que sí es: sustain en el trade, waveclear y
    # capacidad de extender el intercambio.
    assert {TacticalUse.SUSTAIN, TacticalUse.WAVECLEAR, TacticalUse.TRADE_EXTEND} <= q.tactical_uses


def test_pulls_declare_their_direction(darius, mordekaiser):
    """Atraer y empujar son consecuencias opuestas del mismo EffectType:
    sin la dirección declarada son indistinguibles."""

    for champion in (darius, mordekaiser):
        pulls = [e for e in champion.ability("E").effects if e.type == EffectType.DISPLACE_ENEMY]
        assert pulls
        for effect in pulls:
            assert effect.displacement_vector == "toward_self"


def test_trade_cut_is_no_longer_part_of_the_vocabulary():
    """Se eliminó en v1.6.1: ningún YAML lo usaba y la única rama que lo
    leía era inalcanzable."""

    assert not any(u.value == "trade_cut" for u in TacticalUse)
