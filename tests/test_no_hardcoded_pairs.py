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
from lol_reasoner.reasoning.rules import general, stacking
from lol_reasoner.reasoning.rules.specific import MAX_SPECIFIC_INTERACTIONS, SPECIFIC_INTERACTIONS

_GENERAL_MODULES = (general, stacking)


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
    for module in _GENERAL_MODULES:
        literals = _string_literals(module)
        hit = forbidden & literals
        assert not hit, f"{module.__name__} contiene literales de campeón: {hit}"


_CHAMPION_LIKE_NAMES = {"candidate", "enemy"}


def _is_champion_id_access(node: ast.AST) -> bool:
    """True si `node` es `<algo>.id` donde `<algo>` es un campeón
    (`ctx.candidate`/`ctx.enemy`/una variable `candidate`/`enemy`), no
    cualquier otro objeto con un `.id` propio (p. ej. una
    `StackingMechanic.id`, que es un identificador de mecánica, no de
    campeón)."""

    if not (isinstance(node, ast.Attribute) and node.attr == "id"):
        return False
    base = node.value
    if isinstance(base, ast.Attribute):
        return base.attr in _CHAMPION_LIKE_NAMES
    if isinstance(base, ast.Name):
        return base.id in _CHAMPION_LIKE_NAMES
    return False


def test_general_rules_do_not_branch_on_champion_id():
    """Ninguna regla general puede comparar `.id` de un campeón: eso sería una
    tabla A-vs-B disfrazada de regla general. Leer `.name` para armar texto
    legible (p. ej. f"{ctx.candidate.name} tiene...") sí está permitido: no
    afecta ninguna decisión de control de flujo ni de score. Comparar el
    `.id` de otro tipo de objeto (p. ej. `StackingMechanic.id`) tampoco es
    lo que este guardrail prohíbe."""

    for module in _GENERAL_MODULES:
        tree = ast.parse(inspect.getsource(module))
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare):
                for side in [node.left, *node.comparators]:
                    if _is_champion_id_access(side):
                        raise AssertionError(f"{module.__name__} compara `.id` de un campeón (tabla A-vs-B disfrazada)")


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
