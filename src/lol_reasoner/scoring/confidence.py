"""Cálculo de confianza — v1.6.1.

Cuatro señales que antes se mezclaban de a dos, cada una con su propia
pregunta y su propio consumidor:

  1. **Confianza epistémica** (`score`): cuánto sabe el motor sobre este
     matchup. Sube con cobertura de categorías mecánicas distintas dentro
     del universo APLICABLE a este par (unión con la traza espejo, no el
     registro global: incorporar reglas o campeones nuevos no debe hacer
     caer la confianza de un matchup ya evaluado). Baja con información
     faltante. Una traza vacía da 0.
  2. **Volatilidad estratégica compartida** (`volatility_score`): cuánto
     depende el resultado de decisiones y circunstancias que están
     presentes en las DOS direcciones de la consulta — la geometría del
     duelo, el ritmo del intercambio, la carrera de acumulaciones. No
     pueden desaparecer al invertir candidato y enemigo.
  3. **Exigencia propia del candidato** (`execution_condition_count`):
     condiciones `EXECUTION`, que dependen de la habilidad del jugador.
     Alimenta `required_skill` en PersonalScore; NO es volatilidad del
     matchup y sí puede ser asimétrica, porque depende del kit.
  4. **Información faltante** (`missing_info_count`): huecos declarados.

Tres correcciones concretas de v1.6.1:

  * Las contradicciones se cuentan sobre la VISTA CAUSAL deduplicada. En
    el hito 1.6 se contaban sobre la traza cruda: la misma tensión
    repetida en tres fases valía tres contradicciones, y la volatilidad
    de una dirección daba 0.833 contra 0.333 de la inversa por ese solo
    efecto.
  * Una condición `STRATEGIC` cuenta sin importar la polaridad de su
    entrada. Antes solo se miraban entradas `CONDITIONAL`, así que las
    condiciones colgadas de un PRO o un CONTRA se descartaban en
    silencio — justo las que v1.6.1 empezó a producir al permitir que una
    ventaja condicionada incline el score.
  * La penalización por información faltante ya no satura: antes 5 y 7
    huecos penalizaban exactamente igual.

`ConditionKind.EXECUTION` no participa de la volatilidad: se reporta
aparte, como exigencia del candidato.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from lol_reasoner.domain.enums import ConditionKind, ConfidenceLevel, Factor, Phase, Polarity
from lol_reasoner.reasoning.rules.registry import ALL_CATEGORIES
from lol_reasoner.reasoning.trace import ReasoningTrace, TraceEntry

# Umbral de "magnitud comparable": si el lado menor es al menos esta
# fracción del lado mayor, se considera contradicción real y no ruido.
_CONTRADICTION_RATIO_THRESHOLD = 0.4


# Techo duro de la confianza del veredicto mientras la base de conocimiento
# no esté auditada contra un parche y los pesos no estén calibrados. No es
# una fórmula: es una declaración de que, en esas condiciones, ninguna
# cobertura de categorías puede justificar una confianza ALTA sobre la
# conclusión. Se levanta cuando esas dos cosas cambien, no antes.
_UNAUDITED_KB_CEILING = ConfidenceLevel.MEDIA
_CEILING_REASONS = (
    "el conocimiento mecánico no está auditado contra ningún parche",
    "los pesos y deltas no están calibrados contra datos",
)


@dataclass(frozen=True, slots=True)
class ConfidenceResult:
    # Cobertura EPISTÉMICA INTERNA del candidato: cuántas categorías
    # mecánicas aplicables llegó a tocar su traza. Responde "¿cuánto miró
    # el motor?", NO "¿cuán seguro está del veredicto?" — son preguntas
    # distintas y confundirlas fue el problema que motivó separarlas.
    candidate_knowledge_coverage_level: ConfidenceLevel
    candidate_knowledge_coverage_score: float
    # Confianza sobre la CONCLUSIÓN del matchup. Es simétrica por
    # construcción: "A tiene ventaja sobre B" es la misma afirmación se
    # consulte desde donde se consulte, así que no puede cambiar al
    # invertir candidate/enemy.
    shared_matchup_confidence: ConfidenceLevel
    shared_matchup_confidence_reasons: tuple[str, ...]
    coverage_ratio: float
    categories_hit: frozenset[str]
    applicable_categories_count: int
    missing_info_count: int
    shared_strategic_volatility_level: ConfidenceLevel
    shared_strategic_volatility_score: float  # 0..1
    contradiction_count: int
    strategic_condition_count: int
    shared_strategic_count: int
    execution_condition_count: int
    explanation: tuple[str, ...]


def _causal_id(entry: TraceEntry) -> str:
    """Identidad causal para comparar contra la traza espejo: el
    `causal_key` cuando existe, y si no la categoría (que es lo más
    específico que queda)."""

    return entry.causal_key or f"category:{entry.category}"


def _contradictions_per_phase_factor(entries: list[TraceEntry]) -> dict[tuple[Phase, Factor], tuple[float, float]]:
    """Para cada (fase, factor), (suma de deltas PRO, suma de deltas CONTRA)
    — agrupado por fase para no mezclar una ventaja de early con una
    desventaja de late como si fueran simultáneas. Recibe la vista causal
    deduplicada, no la traza cruda."""

    pos: dict[tuple[Phase, Factor], float] = defaultdict(float)
    neg: dict[tuple[Phase, Factor], float] = defaultdict(float)
    for e in entries:
        key = (e.phase, e.factor)
        if e.polarity == Polarity.PRO:
            pos[key] += e.delta
        elif e.polarity == Polarity.CONTRA:
            neg[key] += e.delta
    keys = set(pos) | set(neg)
    return {k: (pos.get(k, 0.0), neg.get(k, 0.0)) for k in keys}


def _level_from_score(score: float) -> ConfidenceLevel:
    if score >= 0.62:
        return ConfidenceLevel.ALTA
    if score >= 0.35:
        return ConfidenceLevel.MEDIA
    return ConfidenceLevel.BAJA


def compute_confidence(trace: ReasoningTrace, mirror_trace: ReasoningTrace) -> ConfidenceResult:
    """`mirror_trace`: la MISMA consulta con candidato/enemigo invertidos.
    Se usa para dos cosas, y para ninguna otra: determinar qué categorías
    eran aplicables a este matchup (denominador de cobertura) y saber qué
    tensiones estratégicas están presentes en ambas direcciones. Su
    contenido nunca se expone ni se mezcla con el resultado del
    candidato."""

    causal_entries = trace.deduped_for_scoring(trace.candidate_id)

    applicable_categories = ALL_CATEGORIES & (trace.categories() | mirror_trace.categories())
    total_categories = len(applicable_categories)
    categories_hit = trace.categories() & applicable_categories
    coverage_ratio = (len(categories_hit) / total_categories) if total_categories else 0.0

    missing_info_count = len({e.invalidated_if for e in trace.entries if e.invalidated_if})

    # --- Epistemia: cobertura menos huecos declarados. Sin saturación
    # temprana: 7 huecos deben penalizar más que 5. Traza vacía => 0. ---
    missing_penalty = 0.35 * (missing_info_count / (missing_info_count + 3)) if missing_info_count else 0.0
    epistemic_score = max(0.0, min(1.0, coverage_ratio - missing_penalty))
    level = _level_from_score(epistemic_score)

    # --- Contradicción: sobre la vista causal, no sobre la traza cruda. ---
    contradiction_count = 0
    for pos_sum, neg_sum in _contradictions_per_phase_factor(causal_entries).values():
        if pos_sum <= 0 or neg_sum <= 0:
            continue
        if min(pos_sum, neg_sum) / max(pos_sum, neg_sum) >= _CONTRADICTION_RATIO_THRESHOLD:
            contradiction_count += 1

    # --- Condiciones STRATEGIC: cualquiera sea la polaridad de la entrada. ---
    strategic = {
        e.condition: _causal_id(e)
        for e in causal_entries
        if e.condition and e.condition_kind == ConditionKind.STRATEGIC
    }
    strategic_condition_count = len(strategic)

    # Compartidas = su causa también aparece en la dirección inversa. Una
    # tensión estratégica del par no puede evaporarse al invertir la
    # consulta; una que dependa del kit del candidato, sí puede.
    mirror_causal_ids = {_causal_id(e) for e in mirror_trace.deduped_for_scoring(mirror_trace.candidate_id)}
    shared_strategic_count = sum(1 for causal in strategic.values() if causal in mirror_causal_ids)

    # --- Exigencia propia del candidato: se reporta, no se mezcla. ---
    execution_conditions = {
        e.condition
        for e in causal_entries
        if e.condition and e.condition_kind == ConditionKind.EXECUTION
    }

    volatility_score = max(
        0.0,
        min(1.0, 0.5 * min(1.0, contradiction_count / 3) + 0.5 * min(1.0, shared_strategic_count / 6)),
    )
    volatility_level = _level_from_score(volatility_score)

    # --- Confianza sobre la conclusión, no sobre cuánto miramos. ---
    # Se construye solo con señales simétricas (volatilidad estratégica
    # compartida) y bajo un techo declarado: mientras la KB no esté
    # auditada y los pesos no estén calibrados, ALTA no es defendible por
    # mucha cobertura que haya. No hay fórmula nueva: es un techo y un
    # descenso por volatilidad.
    ceiling_reasons = list(_CEILING_REASONS)
    if volatility_level == ConfidenceLevel.ALTA:
        matchup_confidence = ConfidenceLevel.BAJA
        ceiling_reasons.append(
            "la conclusión depende fuertemente de condiciones estratégicas compartidas (volatilidad alta)"
        )
    else:
        matchup_confidence = _UNAUDITED_KB_CEILING

    explanation = (
        f"Cobertura epistémica interna del candidato: {len(categories_hit)}/{total_categories} categorías "
        f"mecánicas aplicables. Mide cuánto miró el motor, NO cuán seguro está del veredicto.",
        f"Información faltante distinta señalada por el motor: {missing_info_count}.",
        f"Contradicciones PRO/CONTRA en un mismo (fase, factor), ya deduplicadas por causa: {contradiction_count} "
        "(alimenta volatilidad, no cobertura).",
        f"Condiciones estratégicas distintas: {strategic_condition_count}, de las cuales {shared_strategic_count} "
        "también aparecen al invertir la consulta (tensión compartida del matchup).",
        f"Condiciones de ejecución propias del candidato: {len(execution_conditions)} "
        "(alimentan PersonalScore, no la confianza del matchup).",
        f"Confianza sobre la conclusión: {matchup_confidence.value.upper()} — " + "; ".join(ceiling_reasons) + ".",
    )

    return ConfidenceResult(
        candidate_knowledge_coverage_level=level,
        candidate_knowledge_coverage_score=round(epistemic_score, 3),
        shared_matchup_confidence=matchup_confidence,
        shared_matchup_confidence_reasons=tuple(ceiling_reasons),
        coverage_ratio=round(coverage_ratio, 3),
        categories_hit=frozenset(categories_hit),
        applicable_categories_count=total_categories,
        missing_info_count=missing_info_count,
        shared_strategic_volatility_level=volatility_level,
        shared_strategic_volatility_score=round(volatility_score, 3),
        contradiction_count=contradiction_count,
        strategic_condition_count=strategic_condition_count,
        shared_strategic_count=shared_strategic_count,
        execution_condition_count=len(execution_conditions),
        explanation=explanation,
    )
