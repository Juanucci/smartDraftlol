"""Formas de salida del motor.

Todos los campos de texto (`reasons`, `risks`, `conditions`,
`missing_info`) son `ReasonItem`: texto + el id del `TraceEntry` que lo
respalda. Ningún string llega acá sin ese id. `phase_notes` resume,
fase por fase, qué entradas movieron el score en esa fase — de ahí sale
"cómo cambia el matchup en nivel 6 / primera progresión / side lane".

Nota deliberada de alcance: los scores son un índice de adecuación
mecánica de esta V0, no una probabilidad de victoria ni un winrate.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from lol_reasoner.domain.enums import ConfidenceLevel, Phase


@dataclass(frozen=True, slots=True)
class ReasonItem:
    text: str
    entry_id: str


@dataclass(frozen=True, slots=True)
class PhaseNote:
    phase: str
    net_delta_by_factor: dict[str, float]
    summary: str
    entry_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Confidence:
    """Dos números independientes (hito 1.6): un matchup puede estar bien
    comprendido (epistemia alta) y seguir siendo muy condicional
    (volatilidad alta) al mismo tiempo."""

    level: str  # ConfidenceLevel.value — epistémico
    score: float  # 0..1, heurístico — no es una probabilidad
    coverage_ratio: float
    missing_info_count: int
    volatility_level: str  # ConfidenceLevel.value
    volatility_score: float  # 0..1
    contradiction_count: int
    strategic_condition_count: int
    explanation: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PersonalScoreBreakdown:
    """Explica PersonalScore sin pasar por TraceEntry falsos. Ver
    scoring/personal_score.py."""

    mastery: int | None
    required_skill: float
    execution_condition_count: int
    gap: float
    adjustment: float


@dataclass(frozen=True, slots=True)
class Recommendation:
    candidate_id: str
    candidate_name: str
    global_score: float
    personal_score: float
    mastery: int | None
    personal_breakdown: PersonalScoreBreakdown | None
    factor_breakdown: dict[str, float]
    confidence: Confidence
    reasons: tuple[ReasonItem, ...]
    risks: tuple[ReasonItem, ...]
    conditions: tuple[ReasonItem, ...]
    missing_info: tuple[ReasonItem, ...]
    phase_notes: dict[str, PhaseNote]
    trace_entries: tuple[dict, ...]  # TraceEntry serializado (para inspección / JSON)


@dataclass(frozen=True, slots=True)
class RecommendationSet:
    enemy_id: str
    enemy_name: str
    candidate_ids: tuple[str, ...]
    knowledge_version: str
    ranking_global: tuple[str, ...]
    ranking_personal: tuple[str, ...]
    best_global: str
    best_personal: str
    recommendations: dict[str, Recommendation] = field(default_factory=dict)
