"""Guardrail: las reglas generales no pueden nombrar campeones, y las
excepciones específicas están acotadas y justificadas.

Sin este test, nada impide que alguien "resuelva" el motor escribiendo
`if candidate.id == "darius" and enemy.id == "mordekaiser": ...` dentro
de una regla "general". Este test falla si eso ocurre.
"""

from __future__ import annotations

import ast
import inspect

from lol_reasoner.knowledge.loader import load_all_champions
from lol_reasoner.reasoning.rules import general
from lol_reasoner.reasoning.rules.specific import MAX_SPECIFIC_INTERACTIONS, SPECIFIC_INTERACTIONS


def _all_champion_identifiers() -> set[str]:
    champions = load_all_champions()
    names: set[str] = set()
    for champ in champions.values():
        names.add(champ.id)
        names.add(champ.id.lower())
        names.add(champ.id.capitalize())
        names.add(champ.name)
        names.add(champ.name.lower())
    return names


def _string_literals(module) -> set[str]:
    source = inspect.getsource(module)
    tree = ast.parse(source)
    literals: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            literals.add(node.value)
    return literals


def test_general_rules_module_has_no_champion_literals():
    forbidden = _all_champion_identifiers()
    literals = _string_literals(general)
    hit = forbidden & literals
    assert not hit, f"reasoning/rules/general.py contiene literales de campeón: {hit}"


def test_general_rules_do_not_branch_on_champion_id():
    """Ninguna regla general puede comparar `.id` de un campeón: eso sería una
    tabla A-vs-B disfrazada de regla general. Leer `.name` para armar texto
    legible (p. ej. f"{ctx.candidate.name} tiene...") sí está permitido: no
    afecta ninguna decisión de control de flujo ni de score."""

    source = inspect.getsource(general)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for side in [node.left, *node.comparators]:
                if isinstance(side, ast.Attribute) and side.attr == "id":
                    raise AssertionError("una regla general compara `.id` de un campeón (tabla A-vs-B disfrazada)")


def test_specific_interactions_capped():
    assert len(SPECIFIC_INTERACTIONS) <= MAX_SPECIFIC_INTERACTIONS


def test_specific_interactions_have_justification_and_condition():
    for interaction in SPECIFIC_INTERACTIONS:
        assert interaction.justification and interaction.justification.strip(), interaction.id
        assert interaction.condition and interaction.condition.strip(), interaction.id
        # debe referenciar habilidades concretas, no solo campeones
        assert interaction.candidate_ability_slot
        assert interaction.enemy_ability_slot


def test_specific_interactions_reference_real_abilities():
    champions = load_all_champions()
    for interaction in SPECIFIC_INTERACTIONS:
        cand = champions[interaction.candidate_champion]
        enemy = champions[interaction.enemy_champion]
        assert any(a.slot == interaction.candidate_ability_slot for a in cand.abilities), interaction.id
        assert any(a.slot == interaction.enemy_ability_slot for a in enemy.abilities), interaction.id
