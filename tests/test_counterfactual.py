"""Tests contrafactuales: mutar una propiedad del YAML en memoria debe
cambiar el resultado de forma coherente y explicable, y dejar evidencia
en la traza. Esto es lo que demuestra que el motor razona a partir de
las propiedades declaradas y no repite una tabla de resultados
precargada: si repitiera respuestas fijas, mutar el YAML no cambiaría
nada.
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


def test_removing_darius_vulnerable_tags_reduces_mordekaiser_advantage():
    """Indestructible (Mordekaiser.W) niega los tags auto_attack_reliant y
    sustained_dps_reliant de Darius (G04). Si Darius no tuviera esos tags,
    esa ventaja mecánica para Mordekaiser debería desaparecer y su
    GlobalScore como candidato contra Darius debería bajar."""

    original = _raw_champion_dict("darius")
    mutated = copy.deepcopy(original)
    mutated["tags"] = [t for t in mutated["tags"] if t not in ("auto_attack_reliant", "sustained_dps_reliant")]

    darius_original = load_champion_from_dict(original, source="<original>")
    darius_mutated = load_champion_from_dict(mutated, source="<counterfactual>")
    mordekaiser = load_champion_from_dict(_raw_champion_dict("mordekaiser"), source="<mordekaiser>")

    query = MatchupQuery(enemy_id="darius", candidate_ids=("mordekaiser",))
    rec_before = recommend(query, {"darius": darius_original, "mordekaiser": mordekaiser}).recommendations["mordekaiser"]
    rec_after = recommend(query, {"darius": darius_mutated, "mordekaiser": mordekaiser}).recommendations["mordekaiser"]

    assert rec_after.global_score < rec_before.global_score

    before_texts = " | ".join(r.text for r in rec_before.reasons)
    after_texts = " | ".join(r.text for r in rec_after.reasons)
    assert "Indestructible" in before_texts and "niega el patrón" in before_texts
    assert "Indestructible" not in after_texts or "niega el patrón" not in after_texts

    # y la traza cruda también perdió la entrada correspondiente (evidencia directa)
    before_ids = {e["id"] for e in rec_before.trace_entries}
    after_ids = {e["id"] for e in rec_after.trace_entries}
    assert "G04#early_lane#1" in before_ids
    assert "G04#early_lane#1" not in after_ids


def test_lowering_enemy_durability_removes_true_damage_value_rule():
    """G03 (el daño verdadero conserva valor) solo dispara si la
    durabilidad del rival es >= 3. Bajar Mordekaiser.durability por
    debajo de ese umbral debería hacer desaparecer esa ventaja para
    Darius y bajar su GlobalScore."""

    original = _raw_champion_dict("mordekaiser")
    mutated = copy.deepcopy(original)
    mutated["axes"]["durability"] = 1

    mordekaiser_original = load_champion_from_dict(original, source="<original>")
    mordekaiser_mutated = load_champion_from_dict(mutated, source="<counterfactual>")
    darius = load_champion_from_dict(_raw_champion_dict("darius"), source="<darius>")

    def _run(enemy):
        query = MatchupQuery(enemy_id="mordekaiser", candidate_ids=("darius",))
        champs = {"darius": darius, "mordekaiser": enemy}
        return recommend(query, champs).recommendations["darius"]

    rec_before = _run(mordekaiser_original)
    rec_after = _run(mordekaiser_mutated)

    assert rec_after.global_score < rec_before.global_score

    before_ids = {e["id"] for e in rec_before.trace_entries}
    after_ids = {e["id"] for e in rec_after.trace_entries}
    g03_ids_before = {i for i in before_ids if i.startswith("G03#")}
    g03_ids_after = {i for i in after_ids if i.startswith("G03#")}
    assert g03_ids_before  # el hecho estaba presente en el escenario original
    assert not g03_ids_after  # y desaparece tras la mutación, con evidencia trazable


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
