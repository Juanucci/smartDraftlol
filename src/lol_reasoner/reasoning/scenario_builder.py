"""Constructor perezoso y GENÉRICO de escenarios (v1.7).

Ensambla un `CombatState` a partir de mappings YA decididos por quien
llama — nunca decide por sí mismo qué declarar, nunca rellena un campo
`unknown` con el mejor caso, nunca genera combinaciones globales de
campeones × niveles × estados × ramas
(docs/design/v1.7-sequence-state-design.md §B.3/B.7). No nombra un
campeón ni una mecánica concreta: la instancia real (Darius/Mordekaiser)
vive en `reasoning/sequences/registry.py`, que decide exactamente qué
niveles/habilidades/stacks/`ActionContext` declarar para cada secuencia y
llama a la función de acá para ensamblarlos en un `CombatState`.
"""

from __future__ import annotations

from collections.abc import Mapping

from lol_reasoner.domain.combat_state import (
    AbilityState,
    ActionContext,
    ActorState,
    CombatState,
    SharedContext,
    StackState,
)


def build_scenario_baseline(
    *,
    candidate_level: int | None = None,
    candidate_abilities: Mapping[str, AbilityState] | None = None,
    candidate_stacks: Mapping[str, StackState] | None = None,
    enemy_level: int | None = None,
    enemy_abilities: Mapping[str, AbilityState] | None = None,
    enemy_stacks: Mapping[str, StackState] | None = None,
    action_contexts: Mapping[str, ActionContext] | None = None,
) -> CombatState:
    """Ensambla el `CombatState` con EXACTAMENTE los campos recibidos —
    nada más. Un mapping omitido (`None`) queda vacío (clave ausente:
    "esta secuencia no necesita/declara esta mecánica para este actor"),
    nunca se completa con un supuesto. Quien llama decide, por secuencia,
    qué es lo mínimo necesario (§B3) — esta función no tiene opinión sobre
    eso, solo construye el `CombatState` resultante."""

    return CombatState(
        candidate=ActorState(
            level=candidate_level,
            abilities=candidate_abilities or {},
            stacks=candidate_stacks or {},
        ),
        enemy=ActorState(
            level=enemy_level,
            abilities=enemy_abilities or {},
            stacks=enemy_stacks or {},
        ),
        shared=SharedContext(action_contexts=action_contexts or {}),
    )
