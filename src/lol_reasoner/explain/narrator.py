"""Narrator: convierte una `ReasoningTrace` en texto, sin inventar nada.

Regla dura: cada `ReasonItem` que produce este módulo lleva el `id` del
`TraceEntry` del que salió. No hay generación de texto libre desconectada
del cálculo — es lo que hace verificable (tests/test_trace_integrity.py)
que "la explicación coincide con los factores que realmente modificaron
el score".

v1.6.1:
  * Razones y riesgos se ordenan por APORTE EFECTIVO (delta amortiguado
    por certeza y procedencia, y ponderado por fase y factor), no por
    delta crudo. Antes, una entrada podía encabezar la explicación por
    tener el número más grande aunque su aporte real al score fuera
    menor que el de otra.
  * `build_phase_notes` muestra por separado la vista cruda (auditoría)
    y las contribuciones efectivas (deduplicadas y ponderadas).
  * `build_lean` cierra la explicación con una síntesis: hacia dónde se
    inclina, con cuánta intensidad, con qué confianza, por qué factores y
    qué la revertiría. El motor deja de refugiarse en una lista de
    condiciones cuando la evidencia alcanza para inclinarse.
"""

from __future__ import annotations

from collections import defaultdict

from lol_reasoner.domain.enums import ALL_PHASES, ConditionKind, Phase, Polarity, Provenance
from lol_reasoner.domain.result import Lean, PhaseNote, ReasonItem
from lol_reasoner.reasoning.trace import ReasoningTrace
from lol_reasoner.scoring.global_score import signed_contribution
from lol_reasoner.scoring.weights import Weights

_MAX_ITEMS = 8

# Umbrales de |aporte total| para describir la intensidad de la
# inclinación. Heurísticos y declarados como tales: son cortes de
# vocabulario para no publicar un número crudo como si significara algo
# preciso, no una escala calibrada.
_INTENSITY_MARKED = 0.30
_INTENSITY_MODERATE = 0.12
_INTENSITY_SLIGHT = 0.03


def _dedup_by_text_strongest(entries: list, weights: Weights) -> list:
    """Colapsa entradas con el mismo texto (típico de una interacción de kit
    que es constante a través de varias fases) quedándose con la de mayor
    aporte efectivo. El id resultante sigue siendo una entrada real de la
    traza con ese texto."""

    best_by_text: dict[str, object] = {}
    for e in entries:
        current = best_by_text.get(e.text)
        if current is None or abs(signed_contribution(e, weights)) > abs(signed_contribution(current, weights)):
            best_by_text[e.text] = e
    return sorted(best_by_text.values(), key=lambda e: abs(signed_contribution(e, weights)), reverse=True)


def build_reasons(trace: ReasoningTrace, *, subject_id: str, weights: Weights) -> tuple[ReasonItem, ...]:
    """Deduplica primero por `causal_key` (misma fuente mecánica citada
    por distintas reglas o en distintas fases) y luego por texto — para
    que el usuario no lea "dos razones" que son un solo hecho."""

    deduped = [
        e
        for e in trace.deduped_for_scoring(subject_id)
        if e.polarity == Polarity.PRO and signed_contribution(e, weights) != 0.0
    ]
    entries = _dedup_by_text_strongest(deduped, weights)
    return tuple(ReasonItem(text=e.text, entry_id=e.id) for e in entries[:_MAX_ITEMS])


def build_risks(trace: ReasoningTrace, *, subject_id: str, weights: Weights) -> tuple[ReasonItem, ...]:
    deduped = [
        e
        for e in trace.deduped_for_scoring(subject_id)
        if e.polarity == Polarity.CONTRA and signed_contribution(e, weights) != 0.0
    ]
    entries = _dedup_by_text_strongest(deduped, weights)
    return tuple(ReasonItem(text=e.text, entry_id=e.id) for e in entries[:_MAX_ITEMS])


def build_editorial_priors(trace: ReasoningTrace, *, subject_id: str) -> tuple[ReasonItem, ...]:
    """Priors editoriales: se muestran SIEMPRE, en su propio canal, y
    nunca mezclados con la evidencia derivada del kit.

    Aportan cero al score (v1.6.1): un eje 0..4 escrito a mano no puede
    decidir un veredicto mecánico. Pero ocultarlos sería peor que
    puntuarlos — el lector tiene derecho a ver qué se cargó a mano y qué
    dedujo el motor."""

    entries = [
        e for e in trace.deduped_for_scoring(subject_id) if e.provenance == Provenance.EDITORIAL_PRIOR
    ]
    return tuple(ReasonItem(text=e.text, entry_id=e.id) for e in entries[:_MAX_ITEMS])


def build_uncalibrated_observations(
    trace: ReasoningTrace, *, subject_id: str, weights: Weights
) -> tuple[ReasonItem, ...]:
    """Hechos estructurales reales, con dirección clara, cuyo impacto
    relativo esta V0 no puede cuantificar todavía (p. ej. la penetración
    de cada lado). No son ambiguos ni condicionales: son ciertos y no
    puntúan. Merecen un canal propio para no desaparecer del análisis ni
    confundirse con una ventaja cuantificada."""

    entries = [
        e
        for e in trace.deduped_for_scoring(subject_id)
        if e.provenance == Provenance.DERIVED
        and e.polarity in (Polarity.PRO, Polarity.CONTRA)
        and signed_contribution(e, weights) == 0.0
    ]
    return tuple(ReasonItem(text=e.text, entry_id=e.id) for e in entries[:_MAX_ITEMS])


def build_conditions(trace: ReasoningTrace) -> tuple[ReasonItem, ...]:
    """Toda entrada con `condition` no vacío, sin importar su polaridad.

    Una condición puede acompañar tanto a una ventaja (PRO) como a un
    riesgo (CONTRA) o a un efecto puramente condicional: lo que importa
    acá es que exprese bajo qué circunstancia se sostiene o se invierte.
    """

    entries = [e for e in trace.entries if e.condition]
    seen: set[str] = set()
    items: list[ReasonItem] = []
    for e in entries:
        if e.condition in seen:
            continue
        seen.add(e.condition)
        items.append(ReasonItem(text=e.condition, entry_id=e.id))
    return tuple(items[:_MAX_ITEMS])


def build_missing_info(trace: ReasoningTrace) -> tuple[ReasonItem, ...]:
    entries = [e for e in trace.entries if e.invalidated_if]
    seen: set[str] = set()
    items: list[ReasonItem] = []
    for e in entries:
        if e.invalidated_if in seen:
            continue
        seen.add(e.invalidated_if)
        items.append(ReasonItem(text=e.invalidated_if, entry_id=e.id))
    return tuple(items)


def build_phase_notes(trace: ReasoningTrace, *, subject_id: str, weights: Weights) -> dict[str, PhaseNote]:
    """Dos vistas por fase, etiquetadas (ver `PhaseNote`): la cruda, que
    incluye repeticiones y entradas sin score, y la efectiva, que es lo
    que esa fase realmente aportó al GlobalScore."""

    causal_ids = {id(e) for e in trace.deduped_for_scoring(subject_id)}
    notes: dict[str, PhaseNote] = {}
    for phase in ALL_PHASES:
        entries = trace.for_phase(phase)
        raw_net: dict[str, float] = defaultdict(float)
        sign = {Polarity.PRO: 1.0, Polarity.CONTRA: -1.0, Polarity.CONDITIONAL: 0.0}
        for e in entries:
            raw_net[e.factor.value] += sign[e.polarity] * e.delta

        effective: dict[str, float] = defaultdict(float)
        for e in entries:
            if id(e) not in causal_ids:
                continue  # duplicado de una causa ya contada en otra fase
            contribution = signed_contribution(e, weights)
            if contribution:
                effective[e.factor.value] += round(contribution, 4)

        n_pro = sum(1 for e in entries if e.polarity == Polarity.PRO)
        n_contra = sum(1 for e in entries if e.polarity == Polarity.CONTRA)
        n_cond = sum(1 for e in entries if e.polarity == Polarity.CONDITIONAL)
        n_effective = sum(1 for e in entries if id(e) in causal_ids and signed_contribution(e, weights))

        if not entries:
            summary = "Sin factores mecánicos registrados en esta fase para este candidato."
        else:
            parts = []
            if n_pro:
                parts.append(f"{n_pro} a favor")
            if n_contra:
                parts.append(f"{n_contra} en contra")
            if n_cond:
                parts.append(f"{n_cond} condicional(es)")
            summary = (
                "Registradas en esta fase (vista cruda, con repeticiones de una misma causa): "
                + ", ".join(parts)
                + f". Causas NUEVAS que esta fase desbloquea y aportan al score: {n_effective}. "
                "Cero causas nuevas no significa que las interacciones anteriores dejen de existir: "
                "significa que esta fase no agregó ninguna que no estuviera ya contada."
            )

        notes[phase.value] = PhaseNote(
            phase=phase.value,
            raw_entry_count=len(entries),
            new_scoring_causes=n_effective,
            raw_net_delta_by_factor=dict(raw_net),
            effective_contributions_by_factor=dict(effective),
            summary=summary,
            entry_ids=tuple(e.id for e in entries),
        )
    return notes


def _intensity(total: float) -> str:
    magnitude = abs(total)
    if magnitude >= _INTENSITY_MARKED:
        return "marcada"
    if magnitude >= _INTENSITY_MODERATE:
        return "moderada"
    if magnitude >= _INTENSITY_SLIGHT:
        return "leve"
    return "nula"


def build_lean(
    trace: ReasoningTrace,
    *,
    subject_id: str,
    candidate_name: str,
    enemy_name: str,
    weights: Weights,
    factor_breakdown: dict[str, float],
    matchup_confidence: str,
    volatility: str,
) -> Lean:
    """Síntesis final derivada de la vista causal, SIEMPRE redactada desde
    la perspectiva del candidato evaluado.

    Antes decía "el análisis se inclina hacia Darius" aunque la consulta
    fuera sobre Mordekaiser: correcto pero desorientador, porque el sujeto
    de la consulta era el otro. Y las condiciones se anunciaban con un
    pronombre ambiguo ("qué podría reducirla o invertirla") que no decía a
    quién beneficiaba cada una. Ahora se separan con sujeto explícito.

    No introduce ningún número propio: reusa exactamente las
    contribuciones que forman el MatchupScore.
    """

    total = sum(factor_breakdown.values())
    intensity = _intensity(total)
    if intensity == "nula":
        direction = "even"
    elif total > 0:
        direction = "favors_candidate"
    else:
        direction = "favors_enemy"

    ranked = sorted(factor_breakdown.items(), key=lambda kv: abs(kv[1]), reverse=True)
    main_factors = tuple(f"{name} ({value:+.3f})" for name, value in ranked[:3] if value)

    favored, other = (None, None)
    if direction == "favors_candidate":
        favored, other = candidate_name, enemy_name
    elif direction == "favors_enemy":
        favored, other = enemy_name, candidate_name

    # Las condiciones estratégicas se reparten por a quién beneficiaría que
    # se cumplan: las que cuelgan de la evidencia que sostiene la ventaja
    # la reducirían; las que cuelgan de la evidencia contraria mejorarían
    # la posición del otro lado.
    favored_is_candidate = direction == "favors_candidate"
    against_favored: list[str] = []
    favoring_other: list[str] = []
    seen: set[str] = set()
    for entry in sorted(
        trace.deduped_for_scoring(subject_id),
        key=lambda e: abs(signed_contribution(e, weights)),
        reverse=True,
    ):
        if not entry.condition or entry.condition in seen:
            continue
        if entry.condition_kind != ConditionKind.STRATEGIC:
            continue
        contribution = signed_contribution(entry, weights)
        if contribution == 0:
            continue
        seen.add(entry.condition)
        supports_candidate = contribution > 0
        bucket = against_favored if supports_candidate == favored_is_candidate else favoring_other
        if len(bucket) < 3:
            bucket.append(entry.condition)

    if direction == "even":
        summary = (
            f"El análisis no encuentra una inclinación neta entre {candidate_name} y {enemy_name} con lo que "
            f"esta V0 modela: la evidencia mecánica a favor y en contra se compensa."
        )
    elif favored_is_candidate:
        summary = (
            f"El análisis se inclina levemente a favor de {candidate_name} y en contra de {enemy_name}."
            if intensity == "leve"
            else f"El análisis se inclina de forma {intensity} a favor de {candidate_name} y en contra de {enemy_name}."
        )
    else:
        summary = (
            f"El análisis se inclina levemente en contra de {candidate_name} y a favor de {enemy_name}."
            if intensity == "leve"
            else f"El análisis se inclina de forma {intensity} en contra de {candidate_name} y a favor de {enemy_name}."
        )
    summary += (
        f" Confianza sobre esta conclusión: {matchup_confidence.upper()}; estabilidad: volatilidad "
        f"{volatility.upper()}."
    )

    return Lean(
        direction=direction,
        intensity=intensity,
        matchup_confidence=matchup_confidence,
        volatility=volatility,
        main_factors=main_factors,
        conditions_against_favored=tuple(against_favored),
        conditions_favoring_other=tuple(favoring_other),
        favored_name=favored,
        other_name=other,
        summary=summary,
    )
