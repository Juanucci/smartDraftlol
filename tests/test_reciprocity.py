"""Reciprocidad de reglas generales — hito 1.6, punto 1 del brief.

Bug real encontrado en el hito 1.5: cuatro reglas generales
(`RangeAccessRule`, `EarlyPressureVsScalingRule`, `WaveclearGatingRule`,
`DisplacementVsMobilityRule`) solo implementaban la mitad de una
comparación mecánica compartida — el lado favorecido recibía PRO como
candidato, pero el mismo hecho nunca aparecía como CONTRA cuando el lado
favorecido pasaba a ser el enemigo. Que una regla "vuelva a ejecutarse"
al invertir candidato/enemigo NO prueba que produzca la amenaza
correspondiente: cada mitad de la comparación debe verificarse por
separado.

Este archivo NO se conforma con "las dos trazas son distintas" (eso ya
lo cubre `test_rules.py::test_directionality_darius_vs_mordekaiser_is_not_a_mirror`).
Comprueba, para cada regla reauditada, que el MISMO hecho causal (las
mismas `FactRef` — mismo campeón, mismo eje/habilidad, mismo valor) migra
de PRO a CONTRA (o aparece con el signo correcto en ambas direcciones a
la vez) según de qué lado quede el campeón favorecido — usando campeones
sintéticos mínimos para aislar cada regla de cualquier otra interacción
del kit real de Darius/Mordekaiser.

`PokeVsSustainRule` se incluye también, pero para documentar y verificar
lo contrario: no describe un hecho compartido con dueño ambiguo (dos
preguntas independientes: "¿me cura mi propio poke?" vs. "¿el sustain
rival licua mi poke?"), así que NO se le exige — ni se le debe exigir —
reciprocidad de espejo.
"""

from __future__ import annotations

from lol_reasoner.domain.champion import Ability, Champion, DamageProfile, Effect
from lol_reasoner.domain.enums import (
    ALL_AXES,
    ALL_PHASES,
    Axis,
    CooldownClass,
    DamageType,
    EffectType,
    Phase,
    Polarity,
    Provenance,
    ResourceType,
    Support,
    TacticalUse,
)
from lol_reasoner.reasoning.engine import RuleEngine

_ZERO_AXES = {axis: 0 for axis in ALL_AXES}


def _champion(champion_id: str, *, axes: dict[Axis, int] | None = None, abilities: tuple[Ability, ...] = ()) -> Champion:
    """Campeón sintético mínimo: todos los ejes en 0 salvo los indicados,
    sin recursos ni mecánicas que disparen otras reglas por accidente —
    para que cada test aísle exclusivamente la regla bajo prueba."""

    merged_axes = dict(_ZERO_AXES)
    if axes:
        merged_axes.update(axes)
    return Champion(
        id=champion_id,
        name=champion_id.capitalize(),
        archetype="synthetic",
        damage_profile=DamageProfile(physical=0, magic=0, true=0),
        axes=merged_axes,
        casting_resource=ResourceType.MANA,
        trade_patterns=frozenset(),
        tags=frozenset(),
        abilities=abilities,
        stacking_mechanics=(),
        spikes=(),
        knowledge_version="test",
    )


def _entries(trace, rule_id: str):
    return [e for e in trace.entries if e.rule_id == rule_id]


def test_range_access_reciprocity_same_fact_opposite_polarity():
    """Ejemplo concreto del tipo Kennen-vs-Darius citado en la revisión:
    A tiene más rango que B y B no puede cerrarlo con un self-dash. Que A
    sea candidato o enemigo no debe cambiar el hecho citado, solo su
    signo desde la perspectiva del candidato."""

    a = _champion("a", axes={Axis.ATTACK_RANGE: 4})
    b = _champion("b", axes={Axis.ATTACK_RANGE: 1})
    engine = RuleEngine()

    trace_a_candidate = engine.build_trace(a, b, (Phase.EARLY_LANE,))
    trace_b_candidate = engine.build_trace(b, a, (Phase.EARLY_LANE,))

    entry_a = _entries(trace_a_candidate, "G01")
    entry_b = _entries(trace_b_candidate, "G01")
    assert len(entry_a) == 1 and len(entry_b) == 1
    entry_a, entry_b = entry_a[0], entry_b[0]

    # El hecho citado (los mismos dos FactRef: attack_range de a y de b,
    # con los mismos valores) es idéntico en ambas direcciones.
    assert set(entry_a.premises) == set(entry_b.premises)

    # Pero la polaridad es la contraria: cuando A (el favorecido) es
    # candidato, es PRO; cuando B (el perjudicado) es candidato, el MISMO
    # hecho aparece como CONTRA. No desaparece por estar del lado enemy.
    assert entry_a.polarity == Polarity.PRO
    assert entry_b.polarity == Polarity.CONTRA


def test_range_access_no_reciprocity_bug_regression():
    """Antes de la corrección del hito 1.6, `RangeAccessRule` solo
    implementaba la rama `range_diff >= 2`: si B (perjudicado) era
    candidato, la regla no emitía nada. Este test falla si esa mitad de
    la comparación vuelve a faltar."""

    a = _champion("a", axes={Axis.ATTACK_RANGE: 4})
    b = _champion("b", axes={Axis.ATTACK_RANGE: 1})
    trace_b_candidate = RuleEngine().build_trace(b, a, (Phase.EARLY_LANE,))
    assert _entries(trace_b_candidate, "G01"), "el rango superior del enemigo debe seguir citándose como riesgo del candidato"


def test_early_pressure_vs_scaling_reciprocity_same_fact_opposite_polarity():
    a = _champion("a", axes={Axis.EARLY_PRESSURE: 4})
    b = _champion("b", axes={Axis.EARLY_PRESSURE: 1})
    engine = RuleEngine()

    trace_a_candidate = engine.build_trace(a, b, (Phase.EARLY_LANE,))
    trace_b_candidate = engine.build_trace(b, a, (Phase.EARLY_LANE,))

    entry_a = _entries(trace_a_candidate, "G07")[0]
    entry_b = _entries(trace_b_candidate, "G07")[0]

    assert set(entry_a.premises) == set(entry_b.premises)
    assert entry_a.polarity == Polarity.PRO
    assert entry_b.polarity == Polarity.CONTRA


def test_scaling_prior_is_identical_and_scoreless_in_both_directions():
    """v1.6.1: el eje `scaling` dejó de puntuar (es un prior editorial que
    esta V0 no puede derivar), así que la reciprocidad que se le exige ya
    no es "PRO de un lado y CONTRA del otro" sino que sea EL MISMO hecho
    declarado, sin score, en las dos direcciones.

    Este test reemplaza a `test_scaling_sidelane_reciprocity_same_fact_opposite_polarity`,
    que exigía que el prior editorial moviera el score con signo opuesto."""

    a = _champion("a", axes={Axis.SCALING: 4})
    b = _champion("b", axes={Axis.SCALING: 1})
    engine = RuleEngine()

    entry_a = _entries(engine.build_trace(a, b, (Phase.SIDE_LANE_LATE,)), "G07")[0]
    entry_b = _entries(engine.build_trace(b, a, (Phase.SIDE_LANE_LATE,)), "G07")[0]

    assert set(entry_a.premises) == set(entry_b.premises)
    assert entry_a.causal_key == entry_b.causal_key
    assert entry_a.polarity == entry_b.polarity == Polarity.CONDITIONAL
    assert entry_a.provenance == entry_b.provenance == Provenance.EDITORIAL_PRIOR
    assert entry_a.support == entry_b.support == Support.AMBIGUOUS


def test_waveclear_gating_reciprocity_same_fact_opposite_polarity():
    waveclear_ability = Ability(
        slot="Q",
        name="Synthetic Clear",
        cooldown_class=CooldownClass.MEDIUM,
        effects=(Effect(type=EffectType.DAMAGE, magnitude=2),),
        tactical_uses=frozenset({TacticalUse.WAVECLEAR}),
    )
    a = _champion("a", axes={Axis.WAVECLEAR: 4}, abilities=(waveclear_ability,))
    b = _champion("b", axes={Axis.WAVECLEAR: 1})
    engine = RuleEngine()

    trace_a_candidate = engine.build_trace(a, b, (Phase.SIDE_LANE_LATE,))
    trace_b_candidate = engine.build_trace(b, a, (Phase.SIDE_LANE_LATE,))

    entry_a = _entries(trace_a_candidate, "G08")[0]
    entry_b = _entries(trace_b_candidate, "G08")[0]

    assert set(entry_a.premises) == set(entry_b.premises)
    assert entry_a.polarity == Polarity.PRO
    assert entry_b.polarity == Polarity.CONTRA


def test_waveclear_gating_no_reciprocity_bug_regression():
    """Antes de la corrección, si el ENEMIGO tenía la brecha de waveclear
    a favor, la regla no emitía nada para el candidato perjudicado."""

    waveclear_ability = Ability(
        slot="Q",
        name="Synthetic Clear",
        cooldown_class=CooldownClass.MEDIUM,
        effects=(Effect(type=EffectType.DAMAGE, magnitude=2),),
        tactical_uses=frozenset({TacticalUse.WAVECLEAR}),
    )
    a = _champion("a", axes={Axis.WAVECLEAR: 4}, abilities=(waveclear_ability,))
    b = _champion("b", axes={Axis.WAVECLEAR: 1})
    trace_b_candidate = RuleEngine().build_trace(b, a, (Phase.SIDE_LANE_LATE,))
    assert _entries(trace_b_candidate, "G08"), "la brecha de waveclear del enemigo debe seguir citándose como riesgo del candidato"


def test_displacement_vs_mobility_both_owners_visible_in_a_single_query():
    """Caso más fuerte de reciprocidad: cuando AMBOS lados tienen una
    herramienta de desplazamiento real y el rival tiene movilidad que
    negar, una única consulta (un solo `build_trace`, sin invertir nada)
    ya debe traer la ventaja propia (PRO) Y el riesgo por la herramienta
    del enemigo (CONTRA) — la ventaja mecánica del enemigo no desaparece
    por estar ubicado en `enemy`."""

    displace_ability = lambda slot, magnitude: Ability(  # noqa: E731
        slot=slot,
        name=f"Synthetic Displace {slot}",
        cooldown_class=CooldownClass.MEDIUM,
        effects=(Effect(type=EffectType.DISPLACE_ENEMY, magnitude=magnitude),),
        tactical_uses=frozenset({TacticalUse.INITIATE}),
    )
    a = _champion("a", axes={Axis.MOBILITY: 2}, abilities=(displace_ability("E", 4),))
    b = _champion("b", axes={Axis.MOBILITY: 2}, abilities=(displace_ability("E", 2),))
    engine = RuleEngine()

    trace_a_candidate = engine.build_trace(a, b, (Phase.EARLY_LANE,))
    entries = _entries(trace_a_candidate, "G15")
    assert len(entries) == 2

    by_polarity = {e.polarity: e for e in entries}
    assert set(by_polarity) == {Polarity.PRO, Polarity.CONTRA}
    assert by_polarity[Polarity.PRO].causal_key == "a:E:displace_enemy"
    assert by_polarity[Polarity.CONTRA].causal_key == "b:E:displace_enemy"

    # Al invertir la consulta, los dos MISMOS hechos causales (la
    # habilidad de A y la de B) siguen ambos presentes, cada uno con el
    # signo correspondiente a su nuevo dueño relativo — no se pierde
    # ninguno de los dos, solo intercambian de PRO a CONTRA y viceversa.
    trace_b_candidate = engine.build_trace(b, a, (Phase.EARLY_LANE,))
    entries_swapped = _entries(trace_b_candidate, "G15")
    by_causal_key_before = {e.causal_key: e.polarity for e in entries}
    by_causal_key_after = {e.causal_key: e.polarity for e in entries_swapped}
    assert set(by_causal_key_before) == set(by_causal_key_after) == {"a:E:displace_enemy", "b:E:displace_enemy"}
    assert by_causal_key_before["a:E:displace_enemy"] != by_causal_key_after["a:E:displace_enemy"]
    assert by_causal_key_before["b:E:displace_enemy"] != by_causal_key_after["b:E:displace_enemy"]


def test_displacement_vs_mobility_no_reciprocity_bug_regression():
    """Antes de la corrección, `DisplacementVsMobilityRule` solo evaluaba
    `_one_direction(candidate, ..., enemy, PRO)`: la herramienta de
    desplazamiento del ENEMIGO nunca se traducía en un riesgo CONTRA para
    el candidato, sin importar cuál de los dos fuera candidato."""

    displace_ability = Ability(
        slot="E",
        name="Synthetic Displace",
        cooldown_class=CooldownClass.MEDIUM,
        effects=(Effect(type=EffectType.DISPLACE_ENEMY, magnitude=3),),
        tactical_uses=frozenset({TacticalUse.INITIATE}),
    )
    a = _champion("a", axes={Axis.MOBILITY: 2}, abilities=(displace_ability,))
    b = _champion("b", axes={Axis.MOBILITY: 2})  # b no tiene herramienta propia

    trace_b_candidate = RuleEngine().build_trace(b, a, (Phase.EARLY_LANE,))
    entries = _entries(trace_b_candidate, "G15")
    assert len(entries) == 1
    assert entries[0].polarity == Polarity.CONTRA
    assert entries[0].causal_key == "a:E:displace_enemy"


def test_trade_sustain_is_reciprocal(darius, mordekaiser):
    """REEMPLAZA a `test_poke_vs_sustain_is_deliberately_not_mirrored`.

    La vieja G02 sí era legítimamente asimétrica, pero porque mezclaba dos
    preguntas: "mi poke me cura" (hecho propio) y "el sustain rival licua
    mi poke" (inferencia desde un eje editorial, que además era falsa).
    Al eliminar la segunda, lo que queda —una curación estructural dentro
    del intercambio— SÍ es un hecho compartido: sostiene a su dueño y
    erosiona el saldo del otro. Debe aparecer recíproco."""

    engine = RuleEngine()
    d = _entries(engine.build_trace(darius, mordekaiser, (Phase.EARLY_LANE,)), "G02")
    m = _entries(engine.build_trace(mordekaiser, darius, (Phase.EARLY_LANE,)), "G02")
    assert len(d) == len(m) == 1

    assert d[0].causal_key == m[0].causal_key
    assert d[0].delta == m[0].delta
    assert {d[0].polarity, m[0].polarity} == {Polarity.PRO, Polarity.CONTRA}

    # Y ninguna dirección puede volver a describirlo como poke.
    for entry in (*d, *m):
        assert "poke" not in entry.text.lower()


# --------------------------------------------------------------------------
# Barrido general: TODA causa compartida debe ser recíproca, no solo las
# reglas que alguien se acordó de auditar.
# --------------------------------------------------------------------------

# Causas que dependen del KIT DEL CANDIDATO y por lo tanto NO tienen que
# aparecer en la dirección inversa. Cada excepción se justifica: si una
# entrada describe una interacción COMPARTIDA, no pertenece a esta lista.
_CANDIDATE_OWN_FACTS = {
    # "¿puedo repetir mi poke sin pagar maná?" es una propiedad del
    # presupuesto de recursos del propio candidato, no una interacción
    # entre los dos kits.
    "resource_attrition": "economía de recursos del propio candidato",
    # "¿mi plan depende de acertar una habilidad clave?" es exigencia de
    # ejecución propia: alimenta PersonalScore, no el matchup.
    "ability_reliance": "exigencia de ejecución del propio candidato",
    # "¿mi all-in es fuerte pero frágil?" describe al candidato solo.
    "all_in_readiness": "fragilidad del propio candidato",
}


def _causal_index(trace, subject_id):
    return {
        e.causal_key: e
        for e in trace.deduped_for_scoring(subject_id)
        if e.causal_key is not None
    }


def test_every_shared_cause_is_reciprocal_in_both_directions(darius, mordekaiser):
    """Invariante general (v1.6.1): para una misma causa, invertir la
    consulta debe conservar `causal_key` y premisas, invertir la polaridad
    y mantener EXACTAMENTE la misma magnitud absoluta.

    Es el test que faltaba en el hito 1.6: la reciprocidad se había
    verificado regla por regla sobre las cuatro que se habían auditado, y
    tres escaneos unidireccionales dentro de otra regla sobrevivieron sin
    que nada fallara."""

    engine = RuleEngine()
    a = _causal_index(engine.build_trace(darius, mordekaiser, ALL_PHASES), "darius")
    b = _causal_index(engine.build_trace(mordekaiser, darius, ALL_PHASES), "mordekaiser")

    problems: list[str] = []
    for key in sorted(set(a) | set(b)):
        left, right = a.get(key), b.get(key)
        if left is None or right is None:
            present = left or right
            if present.category in _CANDIDATE_OWN_FACTS:
                continue  # asimetría justificada y documentada
            problems.append(f"{key}: unidireccional (categoría {present.category})")
            continue
        if abs(left.delta - right.delta) > 1e-9:
            problems.append(f"{key}: magnitudes distintas ({left.delta} vs {right.delta})")
        if left.polarity != right.polarity and {left.polarity, right.polarity} != {Polarity.PRO, Polarity.CONTRA}:
            problems.append(f"{key}: polaridades incoherentes ({left.polarity} vs {right.polarity})")
        if left.polarity == right.polarity and left.polarity != Polarity.CONDITIONAL:
            problems.append(f"{key}: misma polaridad en ambas direcciones ({left.polarity})")
        if {p.path for p in left.premises} != {p.path for p in right.premises}:
            problems.append(f"{key}: premisas distintas entre direcciones")
    assert not problems, "causas compartidas no recíprocas:\n  " + "\n  ".join(problems)


def test_true_damage_and_penetration_are_reciprocal_with_synthetic_champions():
    """Sin nombrar a Darius ni a Mordekaiser: un remate de daño verdadero
    y una penetración del rival deben aparecer como riesgo del candidato.
    Antes solo se escaneaba `candidate_abilities()`, así que la amenaza
    del rival no existía en la evaluación."""

    executioner = _champion(
        "executioner",
        abilities=(
            Ability(
                slot="R",
                name="Synthetic Execute",
                cooldown_class=CooldownClass.LONG,
                effects=(Effect(type=EffectType.DAMAGE, magnitude=3, damage_type=DamageType.TRUE),),
            ),
            Ability(
                slot="E",
                name="Synthetic Rend",
                cooldown_class=CooldownClass.MEDIUM,
                effects=(Effect(type=EffectType.ARMOR_PENETRATION, magnitude=2),),
            ),
        ),
    )
    plain = _champion("plain")
    engine = RuleEngine()

    own = _causal_index(engine.build_trace(executioner, plain, (Phase.EARLY_LANE,)), "executioner")
    facing = _causal_index(engine.build_trace(plain, executioner, (Phase.EARLY_LANE,)), "plain")

    for key in ("executioner:R:damage:true", "executioner:E:armor_penetration"):
        assert key in own, f"{key} debe registrarse como ventaja de su dueño"
        assert key in facing, f"{key} debe registrarse como riesgo del rival"
        assert own[key].polarity == Polarity.PRO
        assert facing[key].polarity == Polarity.CONTRA
        assert own[key].delta == facing[key].delta


def test_shield_absorption_is_reciprocal_with_synthetic_champions():
    """La misma capacidad de absorción no puede valer distinto según quién
    haga la consulta, ni siquiera cuando el rival tiene un plan de
    intercambio extendido (que era lo que activaba la variante "rica" y
    asimétrica)."""

    shielded = _champion(
        "shielded",
        abilities=(
            Ability(
                slot="W",
                name="Synthetic Shield",
                cooldown_class=CooldownClass.MEDIUM,
                effects=(
                    Effect(type=EffectType.SHIELD_FROM_STORED, magnitude=3),
                    Effect(type=EffectType.CONVERT_SHIELD_TO_HEAL, magnitude=2),
                ),
                tactical_uses=frozenset({TacticalUse.SUSTAIN}),
            ),
        ),
    )
    brawler = _champion(
        "brawler",
        abilities=(
            Ability(
                slot="Q",
                name="Synthetic Brawl",
                cooldown_class=CooldownClass.SHORT,
                effects=(Effect(type=EffectType.DAMAGE, magnitude=3, damage_type=DamageType.PHYSICAL),),
                tactical_uses=frozenset({TacticalUse.TRADE_EXTEND}),
            ),
        ),
    )
    engine = RuleEngine()
    key = "shielded:W:shield_from_stored"

    own = _causal_index(engine.build_trace(shielded, brawler, (Phase.EARLY_LANE,)), "shielded")
    facing = _causal_index(engine.build_trace(brawler, shielded, (Phase.EARLY_LANE,)), "brawler")

    assert key in own and key in facing
    assert own[key].delta == facing[key].delta
    assert own[key].polarity == Polarity.PRO
    assert facing[key].polarity == Polarity.CONTRA


def test_pull_toward_engage_is_double_edged_and_scoreless_for_both_owners():
    """La regla de pull debe ser generalizable (campeones sintéticos, sin
    nombrar el par real) y no puede inclinarse: quién gana al cerrar la
    distancia es justamente lo que el resto del análisis intenta
    establecer."""

    puller = _champion(
        "puller",
        axes={Axis.ALL_IN: 4, Axis.MOBILITY: 0},
        abilities=(
            Ability(
                slot="E",
                name="Synthetic Pull",
                cooldown_class=CooldownClass.MEDIUM,
                effects=(
                    Effect(type=EffectType.DISPLACE_ENEMY, magnitude=3, displacement_vector="toward_self"),
                ),
                tactical_uses=frozenset({TacticalUse.SETUP_COMBO}),
            ),
        ),
    )
    duelist = _champion("duelist", axes={Axis.ALL_IN: 4, Axis.MOBILITY: 0})
    engine = RuleEngine()

    entries = _entries(engine.build_trace(puller, duelist, (Phase.EARLY_LANE,)), "G18")
    assert len(entries) == 1
    assert entries[0].polarity == Polarity.CONDITIONAL
    assert entries[0].support == Support.CONDITIONED
    assert "doble filo" in entries[0].text

    # Sin una amenaza de corta distancia enfrente, la regla no dispara:
    # la conclusión depende de la estructura, no del nombre del campeón.
    ranged = _champion("ranged", axes={Axis.ALL_IN: 0, Axis.MOBILITY: 3})
    assert not _entries(engine.build_trace(puller, ranged, (Phase.EARLY_LANE,)), "G18")


def test_knockback_does_not_trigger_the_pull_rule():
    """Un desplazamiento que ALEJA no concede acceso: la dirección importa
    y por eso se representa explícitamente en el KB."""

    knocker = _champion(
        "knocker",
        abilities=(
            Ability(
                slot="E",
                name="Synthetic Knockback",
                cooldown_class=CooldownClass.MEDIUM,
                effects=(Effect(type=EffectType.DISPLACE_ENEMY, magnitude=3, displacement_vector="away"),),
                tactical_uses=frozenset({TacticalUse.SETUP_COMBO}),
            ),
        ),
    )
    duelist = _champion("duelist", axes={Axis.ALL_IN: 4, Axis.MOBILITY: 0})
    assert not _entries(RuleEngine().build_trace(knocker, duelist, (Phase.EARLY_LANE,)), "G18")


def test_score_antisymmetry_follows_from_reciprocity(champions):
    """Consecuencia medible del invariante: si toda causa compartida pesa
    igual con signo opuesto y los hechos propios del candidato no
    puntúan, los dos GlobalScore quedan antisimétricos respecto de 50.

    NO es una afirmación sobre probabilidades: sumar 100 no reparte una
    victoria. Y NO es un requisito permanente — el día que un hecho propio
    del candidato mueva el score (p. ej. si su exigencia de ejecución
    dejara de ser `CONDITIONAL`), este test debe ACTUALIZARSE para medir
    la asimetría esperada, no borrarse.
    """

    from lol_reasoner.domain.query import MatchupQuery
    from lol_reasoner.recommend import recommend

    forward = recommend(
        MatchupQuery(enemy_id="mordekaiser", candidate_ids=("darius",)), champions
    ).recommendations["darius"]
    backward = recommend(
        MatchupQuery(enemy_id="darius", candidate_ids=("mordekaiser",)), champions
    ).recommendations["mordekaiser"]

    engine = RuleEngine()
    trace = engine.build_trace(champions["darius"], champions["mordekaiser"], ALL_PHASES)
    own_scoring = [
        e
        for e in trace.deduped_for_scoring("darius")
        if e.category in _CANDIDATE_OWN_FACTS and e.polarity != Polarity.CONDITIONAL
    ]
    assert not own_scoring, (
        "un hecho propio del candidato empezó a puntuar: actualizar la expectativa de antisimetría"
    )
    assert abs((forward.global_score - 50.0) + (backward.global_score - 50.0)) < 0.05
