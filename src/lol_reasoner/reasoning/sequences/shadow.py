"""Punto mínimo de orquestación para evaluar la primera secuencia real en
shadow mode (v1.7).

Nunca toca `RuleEngine`, `scoring/*`, reglas atómicas, ni ningún resultado
público: construye un `ScenarioOutcome` puramente interno y, si se le pasa
una `ReasoningTrace`, lo adjunta a `trace.shadow_sequence_outcomes` —
NUNCA a `trace.entries`. Quien quiera comparar "shadow OFF" vs "shadow ON"
simplemente decide si llama o no a `evaluate_apprehend_followup_shadow`
después de construir la traza con el motor real, sin cambiar una sola
línea de cómo se construye esa traza.

**Selección de rama SIEMPRE explícita** (microfix de esta ronda, §4):
`selected_alternative_id` no tiene default — pasar `None` es la forma
explícita de pedir "todavía no se declaró qué follow-up ocurre" (evalúa
solo `family.opening`, sin rama, sin `causal_components`); ninguna función
de este módulo elige "q" ni ninguna otra alternativa por su cuenta.
"""

from __future__ import annotations

from lol_reasoner.domain.champion import Champion
from lol_reasoner.domain.combat_state import CombatState
from lol_reasoner.domain.enums import Factor, Provenance
from lol_reasoner.reasoning.sequences.evaluator import evaluate_sequence_prefix
from lol_reasoner.reasoning.sequences.generic_sequences import GenericSequenceSpec
from lol_reasoner.reasoning.sequences.registry import (
    DARIUS_ID,
    ApprehendFollowupRegistration,
    BidirectionalTradeRegistration,
    build_apprehend_followup_baseline,
    build_apprehend_followup_registration,
    build_bidirectional_trade_baseline,
    build_bidirectional_trade_registration,
    is_darius_mordekaiser_matchup,
)
from lol_reasoner.reasoning.sequences.sequence import (
    AlternativeGroup,
    CausalComponent,
    Evaluation,
    ScenarioOutcome,
    StateDelta,
    TradeOutcome,
)
from lol_reasoner.reasoning.sequences.steps import ActorRole
from lol_reasoner.reasoning.trace import ReasoningTrace, ShadowSequenceRecord

# Placeholder deliberado, NO calibrado — ver "decisiones no especificadas"
# en la entrega de esta ronda. Nunca llega a scoring (shadow mode, §B7):
# existe solo para demostrar que el evaluador puede completar la cadena y
# producir un CausalComponent real cuando la ejecución está confirmada.
_SHADOW_CAUSAL_COMPONENT_PLACEHOLDER_DELTA = 1.0


def _resolve_darius_role(candidate: Champion, enemy: Champion) -> ActorRole:
    return ActorRole.CANDIDATE if candidate.id == DARIUS_ID else ActorRole.ENEMY


def _build_outcome_from_spec(
    *,
    spec: GenericSequenceSpec,
    baseline: CombatState,
    branch_selection: AlternativeGroup | None,
    causal_components: tuple[CausalComponent, ...],
    evaluation: Evaluation,
) -> ScenarioOutcome:
    step_results, final_state = evaluate_sequence_prefix(spec.step_specs, baseline)
    trade_outcome = TradeOutcome(state_delta=StateDelta(before=baseline, after=final_state), evaluation=evaluation)
    return ScenarioOutcome(
        sequence=spec.sequence,
        step_results=step_results,
        trade_outcome=trade_outcome,
        branch_selection=branch_selection,
        causal_components=causal_components,
    )


def _shadow_causal_component(spec: GenericSequenceSpec, *, sequence_id: str) -> CausalComponent:
    """UN `CausalComponent` shadow-only a partir del `EffectIdentity` que
    consume el ÚLTIMO paso de `spec` (el follow-up que efectivamente
    aplica el stack). `polarity=None`: no se firma una dirección — esta
    ronda no decide favorecidos, solo demuestra que la cadena puede
    completarse y producir un componente representable."""

    consumed = spec.sequence.steps[-1].consumes[0]
    return CausalComponent(
        factor=Factor.STACKING_PAYOFF,
        delta=_SHADOW_CAUSAL_COMPONENT_PLACEHOLDER_DELTA,
        provenance=Provenance.DERIVED,
        fact_ref=consumed.fact_ref,
        sequence_id=sequence_id,
    )


def build_apprehend_followup_outcome(
    registration: ApprehendFollowupRegistration,
    *,
    selected_alternative_id: str | None,
    baseline: CombatState | None = None,
    emit_shadow_causal_component: bool = False,
) -> ScenarioOutcome:
    """Evalúa la familia Apprehend-followup para UNA decisión explícita:

    - `selected_alternative_id` es un id real (`"aa"`/`"q"`) -> evalúa
      ESA alternativa completa (control + follow-up), con
      `branch_selection` confirmándola.
    - `selected_alternative_id is None` -> NO se elige ninguna: evalúa
      solo `registration.family.opening` (el paso de control, sin rama).
      `branch_selection` queda `None` (la propia secuencia no pertenece a
      ningún `AlternativeGroup`) y no hay `causal_components`.

    `baseline` por defecto se construye con todo en `UNKNOWN` (§B6); un
    caller puede pasar uno propio (p. ej. con las conexiones confirmadas)
    para demostrar una cadena completamente satisfecha.

    `emit_shadow_causal_component=True` adjunta UN `CausalComponent`
    shadow-only derivado del follow-up seleccionado — nunca automático,
    nunca cuando no hay alternativa seleccionada."""

    if selected_alternative_id is None:
        spec = registration.family.opening
        resolved_baseline = baseline if baseline is not None else build_apprehend_followup_baseline(registration)
        return _build_outcome_from_spec(
            spec=spec,
            baseline=resolved_baseline,
            branch_selection=None,
            causal_components=(),
            evaluation=Evaluation.UNRESOLVED,
        )

    spec = registration.spec_for(selected_alternative_id)
    resolved_baseline = baseline if baseline is not None else build_apprehend_followup_baseline(registration)

    group = spec.sequence.alternative_group
    assert group is not None  # toda alternativa de esta familia pertenece a un grupo
    branch_selection = AlternativeGroup(
        group_id=group.group_id, alternative_ids=group.alternative_ids, selected_id=selected_alternative_id
    )

    causal_components: tuple[CausalComponent, ...] = ()
    if emit_shadow_causal_component:
        causal_components = (_shadow_causal_component(spec, sequence_id=spec.sequence.sequence_id),)

    return _build_outcome_from_spec(
        spec=spec,
        baseline=resolved_baseline,
        branch_selection=branch_selection,
        causal_components=causal_components,
        # El acierto del follow-up no está garantizado por defecto (§B6);
        # incluso cuando `baseline` confirma la ejecución, esta ronda no
        # infiere un favorecido de UNA sola aplicación de stack — nunca se
        # fuerza una conclusión por el solo hecho de completar la cadena.
        evaluation=Evaluation.CONDITIONAL,
    )


def evaluate_apprehend_followup_shadow(
    *,
    candidate: Champion,
    enemy: Champion,
    selected_alternative_id: str | None,
    baseline: CombatState | None = None,
    emit_shadow_causal_component: bool = False,
    trace: ReasoningTrace | None = None,
) -> ScenarioOutcome | None:
    """Evalúa en shadow mode la familia Apprehend->follow-up para el
    matchup Darius-Mordekaiser, en la orientación que corresponda según
    quién sea `candidate`/`enemy`. Devuelve `None` (no construye nada)
    para cualquier otro matchup.

    Si se pasa `trace`, adjunta el resultado a
    `trace.shadow_sequence_outcomes` — nunca a `trace.entries` ni a
    ningún otro campo que scoring/narrador lean."""

    if not is_darius_mordekaiser_matchup(candidate, enemy):
        return None

    darius = candidate if candidate.id == DARIUS_ID else enemy
    darius_role = _resolve_darius_role(candidate, enemy)

    registration = build_apprehend_followup_registration(darius=darius, darius_role=darius_role)
    outcome = build_apprehend_followup_outcome(
        registration,
        selected_alternative_id=selected_alternative_id,
        baseline=baseline,
        emit_shadow_causal_component=emit_shadow_causal_component,
    )

    if trace is not None:
        record = ShadowSequenceRecord(
            matchup_id=f"{DARIUS_ID}_vs_mordekaiser",
            sequence_id=outcome.sequence.sequence_id,
            outcome=outcome,
        )
        trace.add_shadow_sequence_outcome(record)

    return outcome


# ---------------------------------------------------------------------------
# Trade bidireccional mínimo
# ---------------------------------------------------------------------------


def build_bidirectional_trade_outcome(
    registration: BidirectionalTradeRegistration,
    *,
    selected_alternative_id: str | None,
    baseline: CombatState | None = None,
) -> ScenarioOutcome:
    """Igual que `build_apprehend_followup_outcome`, para la familia
    extendida con la respuesta de Mordekaiser. `causal_components` queda
    siempre vacío acá: el trade bidireccional es puramente diagnóstico en
    esta ronda (§B7), sin variante "confirmada" que reclame un componente.
    """

    if selected_alternative_id is None:
        spec = registration.family.opening
        resolved_baseline = (
            baseline if baseline is not None else build_bidirectional_trade_baseline(registration)
        )
        return _build_outcome_from_spec(
            spec=spec,
            baseline=resolved_baseline,
            branch_selection=None,
            causal_components=(),
            evaluation=Evaluation.UNRESOLVED,
        )

    spec = registration.spec_for(selected_alternative_id)
    resolved_baseline = baseline if baseline is not None else build_bidirectional_trade_baseline(registration)

    group = spec.sequence.alternative_group
    assert group is not None
    branch_selection = AlternativeGroup(
        group_id=group.group_id, alternative_ids=group.alternative_ids, selected_id=selected_alternative_id
    )

    return _build_outcome_from_spec(
        spec=spec,
        baseline=resolved_baseline,
        branch_selection=branch_selection,
        causal_components=(),
        # Trade no necesariamente letal, sin ganador forzado (§5 del
        # trade): CONDITIONAL es la lectura honesta mientras el contacto
        # y la respuesta sigan sin confirmarse por defecto.
        evaluation=Evaluation.CONDITIONAL,
    )


def evaluate_bidirectional_trade_shadow(
    *,
    candidate: Champion,
    enemy: Champion,
    selected_alternative_id: str | None,
    baseline: CombatState | None = None,
    trace: ReasoningTrace | None = None,
) -> ScenarioOutcome | None:
    """Evalúa en shadow mode el trade bidireccional mínimo
    (Apprehend->follow-up->respuesta de Mordekaiser) para el matchup
    Darius-Mordekaiser, en la orientación que corresponda. Devuelve `None`
    para cualquier otro matchup. Mismo canal shadow que
    `evaluate_apprehend_followup_shadow` — nunca `trace.entries`."""

    if not is_darius_mordekaiser_matchup(candidate, enemy):
        return None

    darius = candidate if candidate.id == DARIUS_ID else enemy
    mordekaiser = enemy if candidate.id == DARIUS_ID else candidate
    darius_role = _resolve_darius_role(candidate, enemy)

    registration = build_bidirectional_trade_registration(darius=darius, mordekaiser=mordekaiser, darius_role=darius_role)
    outcome = build_bidirectional_trade_outcome(
        registration, selected_alternative_id=selected_alternative_id, baseline=baseline
    )

    if trace is not None:
        record = ShadowSequenceRecord(
            matchup_id=f"{DARIUS_ID}_vs_mordekaiser",
            sequence_id=outcome.sequence.sequence_id,
            outcome=outcome,
        )
        trace.add_shadow_sequence_outcome(record)

    return outcome
