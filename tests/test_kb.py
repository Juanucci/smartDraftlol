"""La base de conocimiento carga y valida correctamente — schema v2."""

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
        assert champ.knowledge_version == "0.2.0"


def test_tags_are_empty_in_this_milestone(champions):
    """Tag está deliberadamente vacío: ver domain/enums.py."""

    for champ in champions.values():
        assert champ.tags == frozenset()


def _minimal_valid_dict() -> dict:
    return {
        "schema_version": 2,
        "id": "test_champ",
        "name": "Test Champ",
        "archetype": "test",
        "damage_profile": {"physical": 1.0, "magic": 0.0, "true": 0.0},
        "axes": {a.value: 2 for a in Axis},
        "casting_resource": "mana",
        "trade_patterns": ["extended_trade"],
        "tags": [],
        "abilities": [
            {"slot": "P", "name": "P", "cooldown_class": "short", "effects": [{"type": "slow", "magnitude": 1}]},
            {"slot": "Q", "name": "Q", "cooldown_class": "medium", "effects": [{"type": "slow", "magnitude": 1}]},
            {"slot": "W", "name": "W", "cooldown_class": "medium", "effects": [{"type": "slow", "magnitude": 1}]},
            {"slot": "E", "name": "E", "cooldown_class": "medium", "effects": [{"type": "slow", "magnitude": 1}]},
            {
                "slot": "R",
                "name": "R",
                "cooldown_class": "long",
                "available_from": "level_6",
                "effects": [{"type": "slow", "magnitude": 1}],
            },
        ],
        "stacking_mechanics": [],
        "spikes": [],
        "knowledge_version": "0.1.0",
    }


def test_schema_requires_schema_version_2():
    data = _minimal_valid_dict()
    data["schema_version"] = 1
    with pytest.raises(KnowledgeError, match="schema_version"):
        load_champion_from_dict(data, source="<test>")


def test_schema_rejects_legacy_top_level_keys():
    data = _minimal_valid_dict()
    data["trade_pattern"] = "extended_trade"  # v1 singular
    with pytest.raises(KnowledgeError, match="schema v1"):
        load_champion_from_dict(data, source="<test>")


def test_schema_rejects_legacy_strengths_vulnerabilities():
    data = _minimal_valid_dict()
    data["strengths"] = ["algo"]
    with pytest.raises(KnowledgeError, match="schema v1"):
        load_champion_from_dict(data, source="<test>")


def test_schema_rejects_legacy_ability_kind():
    data = _minimal_valid_dict()
    data["abilities"][0]["kind"] = "stacking_dot"
    with pytest.raises(KnowledgeError, match="schema v1"):
        load_champion_from_dict(data, source="<test>")


def test_schema_rejects_legacy_ability_counters():
    data = _minimal_valid_dict()
    data["abilities"][0]["counters"] = []
    with pytest.raises(KnowledgeError, match="schema v1"):
        load_champion_from_dict(data, source="<test>")


def test_schema_requires_all_five_slots():
    data = _minimal_valid_dict()
    data["abilities"] = data["abilities"][:4]  # falta R
    with pytest.raises(KnowledgeError, match="slots"):
        load_champion_from_dict(data, source="<test>")


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


def test_schema_rejects_unknown_effect_type():
    data = _minimal_valid_dict()
    data["abilities"][0]["effects"][0]["type"] = "not_a_real_type"
    with pytest.raises(KnowledgeError, match="effect.type"):
        load_champion_from_dict(data, source="<test>")


def test_schema_rejects_feeds_stack_referencing_unknown_mechanic():
    data = _minimal_valid_dict()
    data["abilities"][1]["effects"][0] = {"type": "stack_application", "magnitude": 1, "feeds_stack": "nope"}
    with pytest.raises(KnowledgeError, match="feeds_stack"):
        load_champion_from_dict(data, source="<test>")


def test_schema_rejects_applied_by_without_matching_effect():
    data = _minimal_valid_dict()
    data["stacking_mechanics"] = [
        {
            "id": "mystack",
            "name": "My Stack",
            "threshold": 3,
            "stacks_per_application": 1,
            "applied_by": ["Q"],  # Q no tiene ningún efecto stack_application feeds_stack=mystack
            "reward_name": "Reward",
        }
    ]
    with pytest.raises(KnowledgeError, match="applied_by"):
        load_champion_from_dict(data, source="<test>")


def test_minimal_valid_dict_loads_successfully():
    champ = load_champion_from_dict(_minimal_valid_dict(), source="<test>")
    assert champ.id == "test_champ"
    assert {a.slot for a in champ.abilities} == {"P", "Q", "W", "E", "R"}


def test_mutating_a_copy_does_not_affect_the_loaded_fixture(darius):
    data = _minimal_valid_dict()
    data["id"] = "darius"
    mutated = copy.deepcopy(data)
    mutated["axes"]["mobility"] = 4
    load_champion_from_dict(mutated, source="<test>")
    assert darius.axis(Axis.MOBILITY) == 0  # el fixture de sesión no fue tocado
