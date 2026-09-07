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
    Axis,
    CooldownClass,
    DamageType,
    EffectType,
    Phase,
    Polarity,
    ResourceType,
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


def test_scaling_sidelane_reciprocity_same_fact_opposite_polarity():
    a = _champion("a", axes={Axis.SCALING: 4})
    b = _champion("b", axes={Axis.SCALING: 1})
    engine = RuleEngine()

    trace_a_candidate = engine.build_trace(a, b, (Phase.SIDE_LANE_LATE,))
    trace_b_candidate = engine.build_trace(b, a, (Phase.SIDE_LANE_LATE,))

    entry_a = _entries(trace_a_candidate, "G07")[0]
    entry_b = _entries(trace_b_candidate, "G07")[0]

    assert set(entry_a.premises) == set(entry_b.premises)
    assert entry_a.polarity == Polarity.PRO
    assert entry_b.polarity == Polarity.CONTRA


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


def test_poke_vs_sustain_is_deliberately_not_mirrored(darius, mordekaiser):
    """`PokeVsSustainRule` (G02) NO describe un único hecho con dueño
    ambiguo: "mi poke me cura" y "el sustain rival licua mi poke" son dos
    preguntas independientes sobre herramientas propias. No se le exige
    reciprocidad de espejo — este test confirma que las entradas citan
    hechos distintos (no una es el complemento numérico de la otra) en
    cada dirección, como documenta su docstring."""

    trace_d = RuleEngine().build_trace(darius, mordekaiser, (Phase.EARLY_LANE,))
    trace_m = RuleEngine().build_trace(mordekaiser, darius, (Phase.EARLY_LANE,))

    categories_d = {(e.category, e.polarity) for e in _entries(trace_d, "G02")}
    categories_m = {(e.category, e.polarity) for e in _entries(trace_m, "G02")}

    # Darius-candidato: su propio poke con heal (PRO). Mordekaiser no
    # tiene una habilidad de poke con heal propio en este kit, así que no
    # hay un PRO complementario "espejado" del lado de Mordekaiser-candidato.
    poke_pro = ("poke_vs_sustain", Polarity.PRO)
    assert poke_pro in categories_d
    assert poke_pro not in categories_m
