"""StackRaceRule: las tres situaciones de una carrera de acumulaciones
(A: quién activa primero, B: si el intercambio se corta, C: si ambos
completan), la comparación de recompensas por dominancia parcial y el
comportamiento contrafactual — hitos 1.5, 1.6 y v1.6.1.

Tests ELIMINADOS en v1.6.1 y por qué:

  * `test_reward_magnitude_ignores_cooldown_reset_in_pure_1v1` exigía
    `reward_magnitude(...) == 9`. Congelaba tanto una función que ya no
    existe como un número que sumaba magnitudes ordinales de tipos
    heterogéneos (empoderamiento propio + amplificación + escalado), y
    dos de sus sumandos eran la MISMA relación causal declarada dos
    veces. Lo reemplaza `test_reward_comparison_uses_no_aggregated_ordinal_sum`
    más la batería de dominancia parcial.
  * `test_mordekaiser_reaches_threshold_before_darius_by_rank` afirmaba
    un orden de activación por ranking. Ahora A dice explícitamente que
    ese orden no puede predecirse; lo que se verifica es que el ordinal
    estructural se CITE en la traza (antes era un cálculo muerto).
"""

from __future__ import annotations

import copy
from importlib import resources

import yaml

from lol_reasoner.domain.enums import ALL_PHASES, EffectType, Phase, Polarity, Support
from lol_reasoner.knowledge.loader import load_champion_from_dict
from lol_reasoner.reasoning.engine import RuleEngine
from lol_reasoner.reasoning.rules.stacking import (
    accelerator_abilities,
    applications_needed,
    ramp_speed_rank,
    reward_profile,
)


def _raw_champion_dict(champion_id: str) -> dict:
    path = resources.files("lol_reasoner.knowledge.champions").joinpath(f"{champion_id}.yaml")
    with resources.as_file(path) as p:
        return yaml.safe_load(p.read_text(encoding="utf-8"))


def _entry(trace, category: str, phase=Phase.EARLY_LANE):
    return next((e for e in trace.for_phase(phase) if e.rule_id == "G12" and e.category == category), None)


# --------------------------------------------------------------- situación A


def test_first_activation_is_never_a_prediction(darius, mordekaiser):
    """A no puede afirmar quién activa primero: sin cadencia, cooldowns,
    acierto ni secuencia, eso no es derivable. Aporta cero al score en
    las dos direcciones."""

    engine = RuleEngine()
    for cand, enemy in ((darius, mordekaiser), (mordekaiser, darius)):
        trace = engine.build_trace(cand, enemy, ALL_PHASES)
        for e in trace.entries:
            if e.rule_id == "G12" and e.category == "stack_race_activation":
                assert e.polarity == Polarity.CONDITIONAL
                assert e.support == Support.AMBIGUOUS
                assert "No puede predecirse con certeza quién activa primero" in e.text


def test_first_activation_cites_the_structural_ordinal(darius, mordekaiser):
    """`ramp_speed_rank` era un cálculo muerto: se computaba solo como
    guarda de early-return, así que el aporte de los aceleradores no era
    observable en ninguna parte de la traza."""

    trace = RuleEngine().build_trace(darius, mordekaiser, (Phase.EARLY_LANE,))
    entry = _entry(trace, "stack_race_activation")
    paths = {p.path for p in entry.premises}
    assert any("ramp_speed_rank" in p for p in paths)

    hemorrhage = next(m for m in darius.stacking_mechanics if m.id == "hemorrhage")
    cited = {p.path: p.value for p in entry.premises}
    assert cited[f"darius.stacking.{hemorrhage.id}.ramp_speed_rank"] == ramp_speed_rank(
        darius, hemorrhage, Phase.EARLY_LANE
    )


def test_stack_race_registers_the_three_vs_five_tension(darius, mordekaiser):
    trace = RuleEngine().build_trace(darius, mordekaiser, ALL_PHASES)
    entry = _entry(trace, "stack_race_activation")

    hemorrhage = next(m for m in darius.stacking_mechanics if m.id == "hemorrhage")
    darkness_rise = next(m for m in mordekaiser.stacking_mechanics if m.id == "darkness_rise")
    assert applications_needed(hemorrhage) == 5
    assert applications_needed(darkness_rise) == 3

    cited_values = {p.value for p in entry.premises}
    assert 5 in cited_values
    assert 3 in cited_values


def test_crippling_strike_appears_in_both_directions_with_correct_effects(darius, mordekaiser):
    """El reset de ataque y el slow deben citarse en ambas direcciones, y
    NO solo dentro de una entrada neutral: también en la situación B, que
    sí mueve el score."""

    engine = RuleEngine()
    trace_d = engine.build_trace(darius, mordekaiser, (Phase.EARLY_LANE,))
    trace_m = engine.build_trace(mordekaiser, darius, (Phase.EARLY_LANE,))

    for trace, direction in ((trace_d, "darius candidato"), (trace_m, "mordekaiser candidato")):
        activation = _entry(trace, "stack_race_activation")
        paths = {p.path for p in activation.premises}
        assert any(EffectType.AUTO_ATTACK_RESET.value in p for p in paths), f"falta reset en {direction}"
        assert any(EffectType.SLOW.value in p for p in paths), f"falta slow en {direction}"
        assert "Crippling Strike" in activation.text
        assert "conservar contacto" in activation.text

        # y también en la entrada que puntúa (B)
        short_trade = _entry(trace, "stack_race_short_trade")
        assert "Crippling Strike" in short_trade.text, f"reset/slow invisible en B ({direction})"
        assert short_trade.polarity in (Polarity.PRO, Polarity.CONTRA)


def test_slow_does_not_produce_a_second_scoring_entry(darius, mordekaiser):
    """El slow es parte de la misma cadena causal que el reset: no puede
    generar un delta aparte dentro de G12."""

    trace = RuleEngine().build_trace(darius, mordekaiser, (Phase.EARLY_LANE,))
    g12 = [e for e in trace.for_phase(Phase.EARLY_LANE) if e.rule_id == "G12"]
    assert len({e.category for e in g12}) == len(g12), "cada situación debe aportar una sola entrada por fase"


# --------------------------------------------------------------- situación B


def test_short_trade_favours_the_lower_threshold_side_reciprocally(darius, mordekaiser):
    engine = RuleEngine()
    d = _entry(engine.build_trace(darius, mordekaiser, (Phase.EARLY_LANE,)), "stack_race_short_trade")
    m = _entry(engine.build_trace(mordekaiser, darius, (Phase.EARLY_LANE,)), "stack_race_short_trade")

    # Mordekaiser necesita menos aplicaciones: si el trade se corta, es su ventaja.
    assert d.polarity == Polarity.CONTRA
    assert m.polarity == Polarity.PRO
    assert d.delta == m.delta
    assert d.support == m.support == Support.CONDITIONED
    assert "se corta temprano" in d.text and "se corta temprano" in m.text


# --------------------------------------------------------------- situación C


def test_full_payoff_states_that_activating_first_does_not_block_the_other(darius, mordekaiser):
    trace = RuleEngine().build_trace(darius, mordekaiser, (Phase.LEVEL_6,))
    entry = _entry(trace, "stack_race_payoff", Phase.LEVEL_6)
    assert "no elimina las cargas del otro" in entry.text
    assert "no bloquea sus aplicaciones futuras" in entry.text


def test_full_payoff_leans_only_with_a_demonstrated_compounding_chain(darius, mordekaiser):
    """C solo se inclina si la traza demuestra una cadena concreta: la
    recompensa de un lado alcanza a una habilidad que YA escalaba con el
    conteo de la MISMA mecánica. Antes de nivel 6 esa habilidad no está
    disponible, así que no hay cadena y no puede haber inclinación.

    v1.6.1 (última ronda): la inclinación ya NO se decide por dominancia
    del conjunto completo de capacidades. Con las capacidades derivadas
    con el mismo criterio para los dos lados, ninguna recompensa domina a
    la otra —cada una tiene capacidades que la otra no tiene—, así que
    desempatar por conjuntos exigiría ordenar tipos de efecto entre sí."""

    engine = RuleEngine()
    early = _entry(engine.build_trace(darius, mordekaiser, (Phase.EARLY_LANE,)), "stack_race_payoff")
    late = _entry(engine.build_trace(darius, mordekaiser, (Phase.LEVEL_6,)), "stack_race_payoff", Phase.LEVEL_6)

    assert early.polarity == Polarity.CONDITIONAL
    assert early.support == Support.AMBIGUOUS, "sin la habilidad que escala disponible no hay cadena que demostrar"

    assert late.polarity == Polarity.PRO
    assert late.support == Support.CONDITIONED
    cited = {p.path for p in late.premises}
    assert any("compounds_with" in p for p in cited)
    assert any("reward_capabilities" in p for p in cited)


def test_neither_reward_dominates_the_other_as_a_whole(darius, mordekaiser):
    """Las capacidades se derivan con el MISMO criterio para los dos
    lados: la recompensa de daño persistente + velocidad tiene las suyas
    igual que la de empoderamiento ofensivo. Por eso ninguna domina, y por
    eso la inclinación no puede venir de la dominancia de conjuntos."""

    d = reward_profile(darius, darius.stacking_mechanics[0], Phase.LEVEL_6)
    m = reward_profile(mordekaiser, mordekaiser.stacking_mechanics[0], Phase.LEVEL_6)

    assert m.capabilities, "la recompensa del rival no puede quedarse sin capacidades derivadas"
    assert not d.dominates(m)
    assert not m.dominates(d)


def test_payoff_narration_describes_both_rewards_on_their_own_terms(darius, mordekaiser):
    """No se puede describir la recompensa del otro por lo que le falta
    ("no amplifica ninguna habilidad"), como si eso la volviera inferior
    en bloque."""

    entry = _entry(
        RuleEngine().build_trace(darius, mordekaiser, (Phase.LEVEL_6,)), "stack_race_payoff", Phase.LEVEL_6
    )
    assert "empoderamiento ofensivo general" in entry.text
    assert "daño persistente" in entry.text
    assert "velocidad para mantener contacto" in entry.text
    assert "son recompensas distintas, no una mejor y otra peor" in entry.text
    assert "no amplifica ninguna" not in entry.text


def test_noxian_might_is_a_general_offensive_empowerment_not_a_per_ability_buff(darius):
    """Noxian Might otorga bonus AD sobre el perfil ofensivo completo. Debe
    representarse UNA vez, con alcance, y no como una lista de
    amplificaciones por habilidad (eso volvería a producir una ventaja de
    score por cada habilidad a la que llega)."""

    from lol_reasoner.domain.enums import EffectType as ET

    mechanic = next(m for m in darius.stacking_mechanics if m.id == "hemorrhage")
    bonus = [e for e in mechanic.reward_effects if e.type == ET.BONUS_ATTACK_DAMAGE]
    assert len(bonus) == 1
    assert bonus[0].scope == "offensive_profile"

    per_ability = [e for e in mechanic.reward_effects if e.amplifies_slot is not None]
    assert not per_ability, "el bonus de AD ya cubre el ratio de la R: declararlo aparte lo cuenta dos veces"


def test_the_two_reward_mechanisms_stay_distinct(darius, mordekaiser):
    """Son mecanismos distintos y deben tener causas distintas: el
    empoderamiento ofensivo general (recompensa al umbral) y el escalado
    directo del daño de la R con las cargas ya aplicadas."""

    trace = RuleEngine().build_trace(darius, mordekaiser, (Phase.LEVEL_6,))
    payoff = _entry(trace, "stack_race_payoff", Phase.LEVEL_6)
    execute = next(e for e in trace.for_phase(Phase.LEVEL_6) if e.category == "true_damage_value")

    assert payoff.causal_key != execute.causal_key, "dos mecanismos distintos, dos causas distintas"
    assert "empoderamiento ofensivo general" in payoff.text
    assert "escala" in execute.text or "crece con las cargas" in execute.text


def test_full_payoff_never_claims_to_win_the_duel(darius, mordekaiser):
    from lol_reasoner.domain.enums import Factor

    engine = RuleEngine()
    for cand, enemy in ((darius, mordekaiser), (mordekaiser, darius)):
        trace = engine.build_trace(cand, enemy, ALL_PHASES)
        for e in trace.entries:
            if e.rule_id == "G12":
                assert e.factor == Factor.STACKING_PAYOFF, "G12 solo puede mover el subproblema de acumulación"
        payoff = _entry(trace, "stack_race_payoff", Phase.LEVEL_6)
        assert "quién gana el duelo sigue dependiendo" in payoff.text or payoff.support == Support.AMBIGUOUS


def test_reward_comparison_uses_no_aggregated_ordinal_sum(darius, mordekaiser):
    """Reemplaza al viejo `assert magnitude == 9`: ninguna entrada puede
    publicar una magnitud agregada, porque sumar ordinales de tipos
    heterogéneos no produce unidades comparables."""

    engine = RuleEngine()
    for cand, enemy in ((darius, mordekaiser), (mordekaiser, darius)):
        trace = engine.build_trace(cand, enemy, ALL_PHASES)
        for e in trace.entries:
            assert "magnitud agregada" not in e.text
            for premise in e.premises:
                assert "reward_magnitude" not in premise.path


def test_hemorrhage_to_ultimate_relation_is_declared_once(darius):
    """La relación "las cargas potencian la definitiva" se declaraba dos
    veces (un `amplify_ability` autorreferencial en la R más la
    amplificación de la recompensa), y ambas se sumaban."""

    r = darius.ability("R")
    self_amplifying = [
        e for e in r.effects if e.type == EffectType.AMPLIFY_ABILITY and e.amplifies_slot == "R"
    ]
    assert not self_amplifying, "la R no debe amplificarse a sí misma: eso duplica la relación con la mecánica"

    scaling = [e for e in r.effects if e.stack_scaling == "hemorrhage"]
    assert len(scaling) == 1
    assert scaling[0].type == EffectType.DAMAGE, "el escalado va sobre el efecto que realmente escala"


def test_reward_profile_is_built_only_from_kb_relations(darius, mordekaiser):
    hemorrhage = next(m for m in darius.stacking_mechanics if m.id == "hemorrhage")

    early = reward_profile(darius, hemorrhage, Phase.EARLY_LANE)
    late = reward_profile(darius, hemorrhage, Phase.LEVEL_6)

    # La cadena depende de la disponibilidad real de la habilidad que escala.
    assert not early.compounds_with_accumulation
    assert late.stack_scaling_slots == frozenset({"R"})
    assert late.empowers_offensive_profile
    assert late.compounds_with_accumulation


def test_reward_without_compounding_chain_stays_ambiguous(darius, mordekaiser):
    """Si ninguna recompensa demuestra la cadena de composición, el
    resultado debe ser ambiguo, no un desempate inventado."""

    a = reward_profile(darius, darius.stacking_mechanics[0], Phase.EARLY_LANE)
    b = reward_profile(mordekaiser, mordekaiser.stacking_mechanics[0], Phase.EARLY_LANE)
    assert a.effect_types != b.effect_types
    assert not a.compounds_with_accumulation and not b.compounds_with_accumulation


# ------------------------------------------------------------- contrafactual


def test_counterfactual_lowering_threshold_changes_cited_values_and_flips_short_trade():
    """Mutar el umbral (5 -> 2) debe cambiar los valores citados Y dar
    vuelta la situación B, que es la que depende del umbral. La situación
    A sigue sin afirmar un orden de activación."""

    original = _raw_champion_dict("darius")
    mutated = copy.deepcopy(original)
    for mechanic in mutated["stacking_mechanics"]:
        if mechanic["id"] == "hemorrhage":
            mechanic["threshold"] = 2

    darius_original = load_champion_from_dict(original, source="<original>")
    darius_mutated = load_champion_from_dict(mutated, source="<counterfactual>")
    mordekaiser = load_champion_from_dict(_raw_champion_dict("mordekaiser"), source="<mordekaiser>")

    engine = RuleEngine()
    before = engine.build_trace(darius_original, mordekaiser, (Phase.EARLY_LANE,))
    after = engine.build_trace(darius_mutated, mordekaiser, (Phase.EARLY_LANE,))

    assert _entry(before, "stack_race_short_trade").polarity == Polarity.CONTRA
    assert _entry(after, "stack_race_short_trade").polarity == Polarity.PRO

    values_before = {p.value for p in _entry(before, "stack_race_activation").premises}
    values_after = {p.value for p in _entry(after, "stack_race_activation").premises}
    assert 5 in values_before and 2 not in values_before
    assert 2 in values_after and 5 not in values_after

    # A no cambia de polaridad nunca: no es una predicción.
    assert _entry(before, "stack_race_activation").polarity == Polarity.CONDITIONAL
    assert _entry(after, "stack_race_activation").polarity == Polarity.CONDITIONAL


def test_accelerator_detection_is_structural_not_declared(darius):
    hemorrhage = next(m for m in darius.stacking_mechanics if m.id == "hemorrhage")
    slots = {a.slot for a in accelerator_abilities(darius, hemorrhage, Phase.EARLY_LANE)}
    assert "W" in slots
