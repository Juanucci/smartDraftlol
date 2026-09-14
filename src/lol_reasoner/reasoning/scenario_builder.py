"""Constructor perezoso de escenarios (v1.7, primera secuencia real).

Construye ÚNICAMENTE el `CombatState` que UNA secuencia concreta necesita
para evaluarse — nunca combinaciones globales de campeones × niveles ×
estados × ramas, nunca hereda estado de otro escenario, nunca rellena un
campo `unknown` con el mejor caso (docs/design/v1.7-sequence-state-design.md
§B.3/B.7). Genérico en el MECANISMO (no lee nombres de campeón: cada
parámetro es una referencia ya resuelta por quien llama); la instancia
concreta Darius-Mordekaiser vive en `reasoning/sequences/registry.py`.
"""

from __future__ import annotations

from lol_reasoner.domain.combat_state import (
    AbilityAvailability,
    AbilityState,
    ActionContext,
    ActorState,
    CombatState,
    RangeStatus,
    SharedContext,
    StackState,
    StackWindow,
)
from lol_reasoner.reasoning.sequences.steps import ActorRole


def build_apprehend_followup_baseline(
    *,
    performer_role: ActorRole,
    performer_level: int,
    control_action_ref: str,
    control_ability_slot: str,
    followup_action_refs: tuple[str, ...],
    followup_ability_slots: tuple[str | None, ...],
    stack_reference: str,
) -> CombatState:
    """Escenario mínimo para la secuencia de apertura control->follow-up:
    declara SOLO lo que esta secuencia usa.

    - Nivel del actor que ejecuta (`performer_role`) — declarado
      explícitamente, nunca inferido.
    - Disponibilidad de la habilidad de control y de cada follow-up con
      `ability_slot` (rank=1, `READY`) — una declaración explícita de
      partida, igual de explícita que el catálogo de invalidadores
      `absent` del baseline documentado en §B.7 ("objetivo legal,
      contexto normal"), no un default silencioso.
    - `ActionContext` de CADA acción relevante (control + cada
      follow-up), con `range_status: UNKNOWN` — deliberado: si el
      contacto efectivamente conecta es una cuestión de EJECUCIÓN, no un
      hecho estructural que este baseline pueda asumir (§B6); declararlo
      `UNKNOWN` (clave presente, valor no observado) es lo que limita el
      soporte de la secuencia a como mucho `CONDITIONED` — nunca a
      `STRUCTURAL` por un supuesto de acierto perfecto.
    - Stack inicial de la mecánica que el follow-up alimenta, en el actor
      que la RECIBE: cero conocido (`count=0`), sin ventana declarada
      (`UNKNOWN`) — un conocido distinto de "aún no observado".

    Nada más se declara: ni nivel, ni stacks, ni habilidades del actor
    receptor (que no las necesita para esta secuencia) — ver
    `test_scenario_builder.py` para la prueba estructural de ausencia de
    producto cartesiano.
    """

    if not isinstance(performer_role, ActorRole):
        raise TypeError(f"performer_role debe ser ActorRole, no {performer_role!r}")

    abilities: dict[str, AbilityState] = {
        control_ability_slot: AbilityState(rank=1, availability=AbilityAvailability.READY)
    }
    for slot in followup_ability_slots:
        if slot is not None:
            abilities[slot] = AbilityState(rank=1, availability=AbilityAvailability.READY)

    performer = ActorState(level=performer_level, abilities=abilities)
    receiver = ActorState(stacks={stack_reference: StackState(count=0, window=StackWindow.UNKNOWN)})

    action_contexts = {
        control_action_ref: ActionContext(action_ref=control_action_ref, range_status=RangeStatus.UNKNOWN)
    }
    for action_ref in followup_action_refs:
        action_contexts[action_ref] = ActionContext(action_ref=action_ref, range_status=RangeStatus.UNKNOWN)

    shared = SharedContext(action_contexts=action_contexts)

    if performer_role is ActorRole.CANDIDATE:
        return CombatState(candidate=performer, enemy=receiver, shared=shared)
    return CombatState(candidate=receiver, enemy=performer, shared=shared)
