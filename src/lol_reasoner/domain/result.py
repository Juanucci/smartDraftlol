"""Formas de salida del motor.

Los dos GlobalScore de las consultas inversas (A contra B, y B contra A)
son hoy ANTISIMÉTRICOS respecto de 50 —suman 100— y eso NO los convierte
en probabilidades complementarias. La antisimetría es una consecuencia
mecánica del invariante de reciprocidad de v1.6.1: toda causa compartida
aparece en las dos direcciones con la misma magnitud y polaridad opuesta,
y los únicos hechos asimétricos (los del kit del propio candidato, como
su exigencia de ejecución) hoy no puntúan. En cuanto un hecho propio del
candidato mueva el score, dejarán de sumar 100 exactamente. Cada número
sigue siendo un índice de adecuación mecánica del candidato evaluado, no
un margen de victoria ni una probabilidad.

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
    """Dos vistas de la misma fase, explícitamente separadas (v1.6.1).

    Antes había un solo conteo, calculado sobre la traza CRUDA y sin
    ponderar, mostrado junto a un GlobalScore que sí estaba deduplicado y
    ponderado: dos números incompatibles en la misma pantalla, sin nada
    que dijera cuál era cuál.

      * `raw_*`: todo lo que la fase registró, incluidas repeticiones de
        una misma causa y entradas que no puntúan. Es la vista de
        auditoría.
      * `effective_contributions_by_factor`: lo que esa fase realmente
        aportó al GlobalScore — deduplicado por `causal_key` y ponderado
        por fase, factor, certeza y procedencia.
    """

    phase: str
    raw_entry_count: int
    # Causas NUEVAS que esta fase desbloquea y que aportan al score. Cero
    # aportes nuevos no significa que las interacciones anteriores dejen
    # de existir: significa que esta fase no agregó ninguna causa que no
    # estuviera ya contada antes (ver v1.6.1 §13.15).
    new_scoring_causes: int
    raw_net_delta_by_factor: dict[str, float]
    effective_contributions_by_factor: dict[str, float]
    summary: str
    entry_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Confidence:
    """Cuatro señales distintas, deliberadamente NO fusionadas en un número:

      * `candidate_knowledge_coverage_*`: cuánto miró el motor para ESTE
        candidato. Puede diferir entre las dos direcciones de la consulta.
      * `shared_matchup_confidence`: cuánta certeza hay sobre la
        conclusión. "A tiene ventaja sobre B" es la misma afirmación se
        consulte desde donde se consulte, así que este valor NO cambia al
        invertir candidate/enemy.
      * `shared_strategic_volatility_*`: cuánto depende el resultado de
        circunstancias presentes en las dos direcciones.
      * `execution_condition_count`: exigencia propia del candidato, que
        va a PersonalScore y no a la confianza del matchup.

    Una cobertura ALTA no implica un veredicto confiable: son preguntas
    distintas, y confundirlas fue exactamente el problema que esta
    separación corrige."""

    # Cobertura epistémica INTERNA del candidato: cuánto miró el motor.
    # NO es la certeza del veredicto (ver `shared_matchup_confidence`).
    candidate_knowledge_coverage_level: str
    candidate_knowledge_coverage_score: float
    # Confianza sobre la conclusión del matchup. Simétrica al invertir la
    # consulta, y con techo MEDIA mientras la KB no esté auditada y los
    # pesos no estén calibrados.
    shared_matchup_confidence: str
    shared_matchup_confidence_reasons: tuple[str, ...]
    coverage_ratio: float
    categories_hit: tuple[str, ...]  # numerador de la cobertura, auditable
    applicable_categories_count: int  # denominador (unión con la traza espejo)
    missing_info_count: int
    shared_strategic_volatility_level: str
    shared_strategic_volatility_score: float  # 0..1
    contradiction_count: int
    strategic_condition_count: int
    shared_strategic_count: int  # tensiones presentes también al invertir la consulta
    execution_condition_count: int  # exigencia propia del candidato (va a PersonalScore)
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
class Lean:
    """La síntesis que el motor debe entregar cuando hay evidencia
    suficiente, en vez de terminar en una lista de condiciones (v1.6.1).

    No es un número nuevo ni una probabilidad: se deriva de la misma
    vista causal que el GlobalScore. `direction` dice hacia dónde se
    inclina el análisis, `intensity` cuán marcada es esa inclinación en
    categorías discretas, y `main_factors`/`reversal_conditions` explican
    de qué depende y qué la reduciría o la daría vuelta.
    """

    direction: str  # "favors_candidate" | "even" | "favors_enemy"
    intensity: str  # "marcada" | "moderada" | "leve" | "nula"
    matchup_confidence: str  # ConfidenceLevel.value — certeza del veredicto
    volatility: str  # ConfidenceLevel.value — estabilidad de la conclusión
    main_factors: tuple[str, ...]
    # Condiciones con SUJETO EXPLÍCITO: qué reduciría la ventaja estimada
    # de quien la tiene, y qué mejoraría la posición del otro.
    conditions_against_favored: tuple[str, ...]
    conditions_favoring_other: tuple[str, ...]
    favored_name: str | None
    other_name: str | None
    summary: str


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
    # Evidencia mecánica DERIVADA que mueve el score.
    reasons: tuple[ReasonItem, ...]
    risks: tuple[ReasonItem, ...]
    # Valoraciones manuales del YAML: visibles, etiquetadas, sin score.
    editorial_priors: tuple[ReasonItem, ...]
    # Hechos estructurales ciertos cuyo impacto relativo no está calibrado.
    uncalibrated_observations: tuple[ReasonItem, ...]
    conditions: tuple[ReasonItem, ...]
    missing_info: tuple[ReasonItem, ...]
    lean: Lean
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
    # None con un solo candidato: no hubo comparación que ganar (v1.6.1).
    # Antes se rellenaban igual y la salida decía "Mejor pick" sobre el
    # único candidato evaluado, como si hubiera superado a alguien.
    best_global: str | None
    best_personal: str | None
    recommendations: dict[str, Recommendation] = field(default_factory=dict)
