"""Tests del hito 1.5, puntos 12 y 15: la tensión de acumulación
(StackRaceRule) y su comportamiento contrafactual."""

from __future__ import annotations

import copy
from importlib import resources

import yaml

from lol_reasoner.domain.enums import ALL_PHASES, Phase, Polarity
from lol_reasoner.knowledge.loader import load_champion_from_dict
from lol_reasoner.reasoning.engine import RuleEngine
from lol_reasoner.reasoning.rules.stacking import applications_needed, ramp_speed_rank, reward_magnitude


def _raw_champion_dict(champion_id: str) -> dict:
    path = resources.files("lol_reasoner.knowledge.champions").joinpath(f"{champion_id}.yaml")
    with resources.as_file(path) as p:
        return yaml.safe_load(p.read_text(encoding="utf-8"))


def test_stack_race_registers_the_three_vs_five_tension(darius, mordekaiser):
    trace = RuleEngine().build_trace(darius, mordekaiser, ALL_PHASES)
    first_threshold_entries = [
        e for e in trace.for_phase(Phase.EARLY_LANE) if e.rule_id == "G12" and "aplicaciones válidas" in e.text
    ]
    assert first_threshold_entries, "debe existir una entrada de G12 comparando umbrales"
    entry = first_threshold_entries[0]

    hemorrhage = next(m for m in darius.stacking_mechanics if m.id == "hemorrhage")
    darkness_rise = next(m for m in mordekaiser.stacking_mechanics if m.id == "darkness_rise")
    assert applications_needed(hemorrhage) == 5
    assert applications_needed(darkness_rise) == 3

    cited_values = {p.value for p in entry.premises}
    assert 5 in cited_values
    assert 3 in cited_values
    # Mordekaiser (3) llega antes que Darius (5): la entrada de Darius-candidato debe ser CONTRA
    assert entry.polarity == Polarity.CONTRA


def test_mordekaiser_reaches_threshold_before_darius_by_rank(darius, mordekaiser):
    hemorrhage = next(m for m in darius.stacking_mechanics if m.id == "hemorrhage")
    darkness_rise = next(m for m in mordekaiser.stacking_mechanics if m.id == "darkness_rise")
    assert ramp_speed_rank(mordekaiser, darkness_rise, Phase.EARLY_LANE) > ramp_speed_rank(darius, hemorrhage, Phase.EARLY_LANE)


def test_reward_magnitude_is_phase_gated(darius):
    hemorrhage = next(m for m in darius.stacking_mechanics if m.id == "hemorrhage")
    before = reward_magnitude(darius, hemorrhage, Phase.EARLY_LANE)
    after = reward_magnitude(darius, hemorrhage, Phase.LEVEL_6)
    assert after > before, "la amplificación sobre R solo debe contar desde que R está disponible"


def test_counterfactual_lowering_darius_threshold_flips_the_first_threshold_entry():
    """Mutar en memoria el umbral de Hemorrhage (5 -> 2) debe invertir
    quién llega primero, y dejar evidencia coherente en la traza."""

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

    entry_before = next(e for e in trace_before.entries if e.rule_id == "G12" and "aplicaciones válidas" in e.text)
    entry_after = next(e for e in trace_after.entries if e.rule_id == "G12" and "aplicaciones válidas" in e.text)

    assert entry_before.polarity == Polarity.CONTRA  # Darius llega después (5 aplicaciones)
    assert entry_after.polarity == Polarity.PRO  # con umbral 2, Darius llega antes que Mordekaiser (3)
    assert "2 aplicaciones" in entry_after.text or "aplicaciones válidas desde" in entry_after.text
