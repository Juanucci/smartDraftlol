"""Tests contrafactuales: mutar una propiedad del YAML en memoria debe
cambiar el resultado de forma coherente y explicable, y dejar evidencia
en la traza. Esto demuestra que el motor razona a partir de las
propiedades declaradas y no repite una tabla de resultados precargada.

(Ver también tests/test_stacking.py::test_counterfactual_lowering_darius_threshold_flips_the_first_threshold_entry
para el contrafactual sobre el umbral de una StackingMechanic.)
"""

from __future__ import annotations

import copy
from importlib import resources

import yaml

from lol_reasoner.domain.query import MatchupQuery
from lol_reasoner.knowledge.loader import load_champion_from_dict
from lol_reasoner.recommend import recommend


def _raw_champion_dict(champion_id: str) -> dict:
    path = resources.files("lol_reasoner.knowledge.champions").joinpath(f"{champion_id}.yaml")
    with resources.as_file(path) as p:
        return yaml.safe_load(p.read_text(encoding="utf-8"))


def test_removing_darius_q_heal_effect_reduces_mordekaiser_disadvantage():
    """PokeVsSustainRule (G02) da un PRO a Darius-candidato por el heal
    condicional de Decimate. Si esa curación no existiera, esa ventaja
    debería desaparecer y su GlobalScore como candidato contra Mordekaiser
    debería bajar."""

    original = _raw_champion_dict("darius")
    mutated = copy.deepcopy(original)
    for ability in mutated["abilities"]:
        if ability["slot"] == "Q":
            ability["effects"] = [e for e in ability["effects"] if e["type"] != "heal"]

    darius_original = load_champion_from_dict(original, source="<original>")
    darius_mutated = load_champion_from_dict(mutated, source="<counterfactual>")
    mordekaiser = load_champion_from_dict(_raw_champion_dict("mordekaiser"), source="<mordekaiser>")

    query = MatchupQuery(enemy_id="mordekaiser", candidate_ids=("darius",))
    rec_before = recommend(query, {"darius": darius_original, "mordekaiser": mordekaiser}).recommendations["darius"]
    rec_after = recommend(query, {"darius": darius_mutated, "mordekaiser": mordekaiser}).recommendations["darius"]

    assert rec_after.global_score < rec_before.global_score

    before_texts = " | ".join(r.text for r in rec_before.reasons)
    after_texts = " | ".join(r.text for r in rec_after.reasons)
    assert "también lo cura al conectar" in before_texts
    assert "también lo cura al conectar" not in after_texts

    heal_entries_before = [e for e in rec_before.trace_entries if e["rule_id"] == "G02" and "también lo cura" in e["text"]]
    heal_entries_after = [e for e in rec_after.trace_entries if e["rule_id"] == "G02" and "también lo cura" in e["text"]]
    assert heal_entries_before
    assert not heal_entries_after


def test_shrinking_mordekaiser_shield_magnitude_reduces_the_mitigation_penalty():
    """DamageTypeAndShieldRule (fusionada con la ex-G04 en el hito 1.6)
    escala su CONTRA `damage_mitigation` con la magnitud del escudo de
    Indestructible. Bajarla debería reducir (no eliminar) la
    penalización que sufre Darius como candidato."""

    original = _raw_champion_dict("mordekaiser")
    mutated = copy.deepcopy(original)
    for ability in mutated["abilities"]:
        if ability["slot"] == "W":
            for effect in ability["effects"]:
                if effect["type"] == "shield_from_stored":
                    effect["magnitude"] = 1  # antes: 3

    mordekaiser_original = load_champion_from_dict(original, source="<original>")
    mordekaiser_mutated = load_champion_from_dict(mutated, source="<counterfactual>")
    darius = load_champion_from_dict(_raw_champion_dict("darius"), source="<darius>")

    def _run(enemy):
        query = MatchupQuery(enemy_id="mordekaiser", candidate_ids=("darius",))
        return recommend(query, {"darius": darius, "mordekaiser": enemy}).recommendations["darius"]

    rec_before = _run(mordekaiser_original)
    rec_after = _run(mordekaiser_mutated)

    assert rec_after.global_score > rec_before.global_score  # menos escudo => menos mitigación => mejor para Darius

    mitigation_before = next(e for e in rec_before.trace_entries if e["category"] == "damage_mitigation" and e["phase"] == "early_lane")
    mitigation_after = next(e for e in rec_after.trace_entries if e["category"] == "damage_mitigation" and e["phase"] == "early_lane")
    assert mitigation_after["delta"] < mitigation_before["delta"]


def test_raising_candidate_execution_demand_lowers_personal_score_at_low_mastery():
    """Subir execution_demand de Mordekaiser debería exigir más required_skill
    y, con mastery bajo, penalizar más su PersonalScore — sin tocar el
    GlobalScore de otro candidato ni requerir ninguna tabla precargada."""

    original = _raw_champion_dict("mordekaiser")
    mutated = copy.deepcopy(original)
    mutated["axes"]["execution_demand"] = 4  # antes era 2

    mordekaiser_original = load_champion_from_dict(original, source="<original>")
    mordekaiser_mutated = load_champion_from_dict(mutated, source="<counterfactual>")
    darius = load_champion_from_dict(_raw_champion_dict("darius"), source="<darius>")

    def _run(candidate):
        query = MatchupQuery(enemy_id="darius", candidate_ids=("mordekaiser",), mastery={"mordekaiser": 10})
        champs = {"darius": darius, "mordekaiser": candidate}
        return recommend(query, champs).recommendations["mordekaiser"]

    rec_before = _run(mordekaiser_original)
    rec_after = _run(mordekaiser_mutated)

    assert rec_after.personal_score < rec_before.personal_score
    # Hito 1.6: `ExecutionDemandBaselineRule` (G10) fue eliminada y ya no
    # existe ningún `Factor.EXECUTION_DEMAND` — GlobalScore mide
    # adecuación mecánica asumiendo ejecución competente, punto. El eje
    # `execution_demand` solo alimenta `required_skill` (PersonalScore,
    # ver scoring/personal_score.py), nunca el GlobalScore de nadie: se
    # verifica explícitamente acá, no solo se infiere del docstring.
    assert rec_after.global_score == rec_before.global_score


def test_removing_mordekaiser_r_available_from_level_6_effects_present_before_level_6_disappear():
    """Contrafactual estructural: si Realm of Death (R) se declarara
    disponible desde early_lane (mutación deliberadamente incorrecta,
    solo para probar que el motor reacciona), las entradas de
    IsolationRule deberían aparecer ya en early_lane."""

    original = _raw_champion_dict("mordekaiser")
    mutated = copy.deepcopy(original)
    for ability in mutated["abilities"]:
        if ability["slot"] == "R":
            ability["available_from"] = "early_lane"

    mordekaiser_original = load_champion_from_dict(original, source="<original>")
    mordekaiser_mutated = load_champion_from_dict(mutated, source="<counterfactual>")
    darius = load_champion_from_dict(_raw_champion_dict("darius"), source="<darius>")

    from lol_reasoner.domain.enums import Phase
    from lol_reasoner.reasoning.engine import RuleEngine

    trace_before = RuleEngine().build_trace(darius, mordekaiser_original, (Phase.EARLY_LANE,))
    trace_after = RuleEngine().build_trace(darius, mordekaiser_mutated, (Phase.EARLY_LANE,))

    isolation_categories = {"isolation_stat_steal", "isolation_arena"}
    assert not ({e.category for e in trace_before.entries} & isolation_categories)
    assert {e.category for e in trace_after.entries} & isolation_categories
