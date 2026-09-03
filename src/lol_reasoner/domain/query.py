"""Consulta de entrada al motor.

V0: sin `patch` ni `side`. Todavía no modelamos mapa, composición, jungla
ni condiciones externas al 1v1 de lane, y no auditamos el conocimiento
contra ningún parche concreto (ver README).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from lol_reasoner.domain.enums import Phase


@dataclass(frozen=True, slots=True)
class MatchupQuery:
    enemy_id: str
    candidate_ids: tuple[str, ...] | None = None  # None => todos los demás campeones cargados
    mastery: dict[str, int] = field(default_factory=dict)  # candidate_id -> 0..100
    phases: tuple[Phase, ...] | None = None  # None => todas las fases modeladas
