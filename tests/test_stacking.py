"""Tests de StackRaceRule: comparación estructural de umbral, recompensa
y comportamiento contrafactual — hitos 1.5 y 1.6.

Hito 1.6: la comparación de "quién llega primero" ya no se afirma con
PRO/CONTRA (eso sobreafirmaba certeza sobre un orden temporal que la
fórmula no puede predecir): pasa a `CONDITIONAL` siempre, y lo que
cambia con los datos es el CONTENIDO (qué lado requiere menos
aplicaciones, si aparece la cláusula de riesgo por acelerador rival),
no la polaridad.
"""

from __future__ import annotations

import copy
from importlib import resources

import yaml

from lol_reasoner.domain.enums import ALL_PHASES, ConditionKind, Phase, Polarity
from lol_reasoner.knowledge.loader import load_champion_from_dict
from lol_reasoner.reasoning.engine import RuleEngine
from lol_reasoner.reasoning.rules.stacking import applications_needed, ramp_speed_rank, reward_magnitude


def _raw_champion_dict(champion_id: str) -> dict:
    path = resources.files("lol_reasoner.knowledge.champions").joinpath(f"{champion_id}.yaml")
    with resources.as_file(path) as p:
        return yaml.safe_load(p.read_text(encoding="utf-8"))


def _threshold_entry(trace, phase=Phase.EARLY_LANE):
    return next(e for e in trace.for_phase(phase) if e.rule_id == "G12" and "aplicaciones válidas" in e.text)


def test_stack_race_registers_the_three_vs_five_tension(darius, mordekaiser):
    trace = RuleEngine().build_trace(darius, mordekaiser, ALL_PHASES)
    entry = _threshold_entry(trace)

    hemorrhage = next(m for m in darius.stacking_mechanics if m.id == "hemorrhage")
    darkness_rise = next(m for m in mordekaiser.stacking_mechanics if m.id == "darkness_rise")
    assert applications_needed(hemorrhage) == 5
    assert applications_needed(darkness_rise) == 3

    cited_values = {p.value for p in entry.premises}
    assert 5 in cited_values
    assert 3 in cited_values

    # La comparación estructural es CONDITIONAL/STRATEGIC: no afirma
    # quién activa primero en el tiempo real (ver docstring de
    # StackRaceRule), solo cita el hecho estructural.
    assert entry.polarity == Polarity.CONDITIONAL
    assert entry.condition_kind == ConditionKind.STRATEGIC
    assert "no es una predicción de quién activa primero" in entry.text or "orden estructural" in entry.text


def test_first_threshold_entry_never_asserts_pro_or_contra(darius, mordekaiser):
    """Punto 6 del hito 1.6: separar "umbral menor" de "probabilidad real
    de activarlo primero" — la entrada nunca debe mover GlobalScore por
    sí sola (CONDITIONAL = signo 0 en la convención de scoring)."""

    trace_d = RuleEngine().build_trace(darius, mordekaiser, ALL_PHASES)
    trace_m = RuleEngine().build_trace(mordekaiser, darius, ALL_PHASES)
    for trace in (trace_d, trace_m):
        for e in trace.entries:
            if e.rule_id == "G12" and "aplicaciones válidas" in e.text:
                assert e.polarity == Polarity.CONDITIONAL


def test_crippling_strike_appears_in_both_directions_with_correct_effects(darius, mordekaiser):
    """Punto 3/5 del hito 1.6: AUTO_ATTACK_RESET y SLOW de Crippling
    Strike deben citarse en ambas direcciones, sin un delta aparte por
    el slow (misma cadena causal)."""

    trace_d = RuleEngine().build_trace(darius, mordekaiser, (Phase.EARLY_LANE,))
    trace_m = RuleEngine().build_trace(mordekaiser, darius, (Phase.EARLY_LANE,))

    entry_d = _threshold_entry(trace_d)
    entry_m = _threshold_entry(trace_m)

    for entry, direction in ((entry_d, "darius candidato"), (entry_m, "mordekaiser candidato")):
        paths = {p.path for p in entry.premises}
        assert any("auto_attack_reset" in p for p in paths), f"falta AUTO_ATTACK_RESET en {direction}"
        assert any("slow" in p for p in paths), f"falta SLOW en {direction}"
        assert "Crippling Strike" in entry.text
        assert "conservar contacto" in entry.text

    # Cuando Mordekaiser es candidato, el texto debe leerse como riesgo
    # explícito: Darius mantiene el intercambio pese a activar su propia
    # mecánica con menos impactos.
    assert "facilitan que Darius mantenga el intercambio" in entry_m.text
    assert "continúe acumulando Hemorrhage" in entry_m.text

    # No hay un segundo RuleEffect por el slow: sigue siendo UNA sola
    # entrada de "aplicaciones válidas" por fase, no dos.
    slow_only_entries = [
        e for e in trace_d.for_phase(Phase.EARLY_LANE)
        if e.rule_id == "G12" and e.id != entry_d.id and "Crippling Strike" in e.text
    ]
    assert not slow_only_entries


def test_mordekaiser_reaches_threshold_before_darius_by_rank(darius, mordekaiser):
    hemorrhage = next(m for m in darius.stacking_mechanics if m.id == "hemorrhage")
    darkness_rise = next(m for m in mordekaiser.stacking_mechanics if m.id == "darkness_rise")
    assert ramp_speed_rank(mordekaiser, darkness_rise, Phase.EARLY_LANE) > ramp_speed_rank(darius, hemorrhage, Phase.EARLY_LANE)


def test_reward_magnitude_is_phase_gated(darius):
    hemorrhage = next(m for m in darius.stacking_mechanics if m.id == "hemorrhage")
    before = reward_magnitude(darius, hemorrhage, Phase.EARLY_LANE)
    after = reward_magnitude(darius, hemorrhage, Phase.LEVEL_6)
    assert after > before, "la amplificación sobre R solo debe contar desde que R está disponible"


def test_reward_magnitude_ignores_cooldown_reset_in_pure_1v1(darius):
    """Punto 7 del hito 1.6: el reset de Noxian Guillotine no debe
    perpetuar la amenaza en una consulta de un único enemigo."""

    hemorrhage = next(m for m in darius.stacking_mechanics if m.id == "hemorrhage")
    magnitude = reward_magnitude(darius, hemorrhage, Phase.LEVEL_6)
    # Con COOLDOWN_RESET excluido: EMPOWER_SELF(4) + AMPLIFY_ABILITY reward(3) + AMPLIFY_ABILITY propio de R(2) = 9
    assert magnitude == 9


def test_reward_magnitude_text_does_not_mention_perpetuating_threat(darius, mordekaiser):
    trace = RuleEngine().build_trace(darius, mordekaiser, ALL_PHASES)
    for e in trace.entries:
        if e.rule_id == "G12":
            assert "perpetúa" not in e.text
            assert "evento único" not in e.text


def test_counterfactual_lowering_darius_threshold_changes_cited_values():
    """Mutar en memoria el umbral de Hemorrhage (5 -> 2) debe cambiar los
    valores citados en la traza de forma coherente. La polaridad ya NO
    es la señal (siempre CONDITIONAL, hito 1.6): lo que debe cambiar es
    el contenido — el propio umbral citado y el ranking estructural."""

    original = _raw_champion_dict("darius")
    mutated = copy.deepcopy(original)
    for mechanic in mutated["stacking_mechanics"]:
        if mechanic["id"] == "hemorrhage":
            mechanic["threshold"] = 2

    darius_original = load_champion_from_dict(original, source="<original>")
    darius_mutated = load_champion_from_dict(mutated, source="<counterfactual>")
    mordekaiser = load_champion_from_dict(_raw_champion_dict("mordekaiser"), source="<mordekaiser>")

    trace_before = RuleEngine().build_trace(darius_original, mordekaiser, (Phase.EARLY_LANE,))
    trace_after = RuleEngine().build_trace(darius_mutated, mordekaiser, (Phase.EARLY_LANE,))

    entry_before = _threshold_entry(trace_before)
    entry_after = _threshold_entry(trace_after)

    assert entry_before.polarity == Polarity.CONDITIONAL
    assert entry_after.polarity == Polarity.CONDITIONAL  # nunca cambia: ver test_first_threshold_entry_never_asserts_pro_or_contra

    values_before = {p.value for p in entry_before.premises}
    values_after = {p.value for p in entry_after.premises}
    assert 5 in values_before and 2 not in values_before
    assert 2 in values_after and 5 not in values_after
    assert "5 aplicaciones válidas" in entry_before.text
    assert "2 aplicaciones válidas" in entry_after.text

    hemorrhage_mutated = next(m for m in darius_mutated.stacking_mechanics if m.id == "hemorrhage")
    darkness_rise = next(m for m in mordekaiser.stacking_mechanics if m.id == "darkness_rise")
    # Con umbral 2, Darius (candidato) queda con rango estructural mayor
    # que Mordekaiser (antes era al revés con umbral 5).
    assert ramp_speed_rank(darius_mutated, hemorrhage_mutated, Phase.EARLY_LANE) > ramp_speed_rank(mordekaiser, darkness_rise, Phase.EARLY_LANE)
