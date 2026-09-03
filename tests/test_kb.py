"""La base de conocimiento carga y valida correctamente."""

from __future__ import annotations

import copy

import pytest

from lol_reasoner.domain.enums import Axis
from lol_reasoner.knowledge.loader import load_champion_from_dict
from lol_reasoner.knowledge.schema import KnowledgeError


def test_loads_exactly_darius_and_mordekaiser(champions):
    assert set(champions) == {"darius", "mordekaiser"}


def test_champion_axes_are_in_range(champions):
    for champ in champions.values():
        for axis in Axis:
            value = champ.axis(axis)
            assert 0 <= value <= 4, f"{champ.id}.{axis.value}={value} fuera de rango"


def test_knowledge_version_is_internal_not_a_patch(champions):
    for champ in champions.values():
        # Formato semver simple; no debe parecerse a un número de parche de LoL (p.ej. "14.3").
        assert champ.knowledge_version == "0.1.0"


def _minimal_valid_dict() -> dict:
    return {
        "id": "test_champ",
        "name": "Test Champ",
        "archetype": "test",
        "damage_profile": {"physical": 1.0, "magic": 0.0, "true": 0.0},
        "axes": {a.value: 2 for a in Axis},
        "trade_pattern": "extended_trade",
        "tags": [],
        "abilities": [
            {"slot": "Q", "name": "Test Q", "kind": "stacking_dot", "cooldown_class": "short"},
        ],
        "spikes": [],
        "strengths": [],
        "vulnerabilities": [],
        "knowledge_version": "0.1.0",
    }


def test_schema_rejects_missing_axis():
    data = _minimal_valid_dict()
    del data["axes"]["mobility"]
    with pytest.raises(KnowledgeError, match="mobility"):
        load_champion_from_dict(data, source="<test>")


def test_schema_rejects_axis_out_of_range():
    data = _minimal_valid_dict()
    data["axes"]["mobility"] = 7
    with pytest.raises(KnowledgeError):
        load_champion_from_dict(data, source="<test>")


def test_schema_rejects_unknown_tag():
    data = _minimal_valid_dict()
    data["tags"] = ["not_a_real_tag"]
    with pytest.raises(KnowledgeError, match="tags desconocidos"):
        load_champion_from_dict(data, source="<test>")


def test_schema_rejects_damage_profile_not_summing_to_one():
    data = _minimal_valid_dict()
    data["damage_profile"] = {"physical": 0.1, "magic": 0.1, "true": 0.1}
    with pytest.raises(KnowledgeError, match="damage_profile"):
        load_champion_from_dict(data, source="<test>")


def test_schema_rejects_unknown_ability_kind():
    data = _minimal_valid_dict()
    data["abilities"][0]["kind"] = "not_a_real_kind"
    with pytest.raises(KnowledgeError, match="kind"):
        load_champion_from_dict(data, source="<test>")


def test_minimal_valid_dict_loads_successfully():
    champ = load_champion_from_dict(_minimal_valid_dict(), source="<test>")
    assert champ.id == "test_champ"


def test_mutating_a_copy_does_not_affect_the_loaded_fixture(darius):
    data = _minimal_valid_dict()
    data["id"] = "darius"
    mutated = copy.deepcopy(data)
    mutated["axes"]["mobility"] = 4
    load_champion_from_dict(mutated, source="<test>")
    assert darius.axis(Axis.MOBILITY) == 1  # el fixture de sesión no fue tocado
