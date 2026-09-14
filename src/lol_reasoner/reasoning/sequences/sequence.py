"""Secuencia, resultado de trade y resultado de escenario (v1.7, Etapa 2).

Tipos genéricos e inmutables para representar UNA secuencia de pasos, su
grupo de exclusión mutua (si pertenece a uno), el resultado no binario de
un trade, y el resultado agregado de haber evaluado una secuencia contra
un escenario — sin implementar todavía la secuencia concreta, el motor de
transición, el generador de escenarios, ni ninguna integración con
scoring/`RuleEngine`/`ReasoningTrace` (docs/design/v1.7-sequence-state-design.md
§B.6/B.8/B.9/K).

**Deterministas, sin probabilidades, sin pesos nuevos**: `covers_causes` se
DERIVA de los `EffectIdentity` realmente consumidos por los pasos — nunca
se declara a mano como una lista libre (§B.3). Ninguna `Evaluation` se
calcula automáticamente a partir de un `StateDelta`: se declara con la
evidencia que exista, nunca se rellena con el mejor caso.

**Reutiliza vocabulario existente** en vez de duplicarlo: `Support`,
`Provenance`, `Factor` y `Polarity` vienen de `domain.enums` — este módulo
no declara ningún enum paralelo con el mismo significado.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum

from lol_reasoner.domain.combat_state import CombatState
from lol_reasoner.domain.enums import Factor, Polarity, Provenance, Support
from lol_reasoner.reasoning.sequences.steps import (
    _SUPPORT_PRIORITY,
    ActorRole,
    EffectIdentity,
    PreconditionStatus,
    SequenceStep,
    _require_nonempty_string,
)

# ---------------------------------------------------------------------------
# Grupo de exclusión mutua entre alternativas de un mismo punto de decisión
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AlternativeGroup:
    """Alternativas mutuamente excluyentes de un mismo punto de decisión
    (diseño §B.9). Como mucho una puede estar seleccionada — nunca dos: la
    estructura lo hace irrepresentable (`selected_id` es un único campo
    opcional, no un conjunto). `selected_id = None` es la representación
    explícita de "todavía condicional/irresuelto" — no una tercera
    alternativa encubierta.
    """

    group_id: str
    alternative_ids: tuple[str, ...]
    selected_id: str | None = None

    def __post_init__(self) -> None:
        _require_nonempty_string(self.group_id, field_name="AlternativeGroup.group_id")
        if not isinstance(self.alternative_ids, tuple):
            raise TypeError(
                f"AlternativeGroup.alternative_ids debe ser tuple, no "
                f"{type(self.alternative_ids).__name__}"
            )
        if not self.alternative_ids:
            raise ValueError("AlternativeGroup.alternative_ids no puede estar vacío")
        for alt in self.alternative_ids:
            _require_nonempty_string(alt, field_name="AlternativeGroup.alternative_ids[]")
        if len(set(self.alternative_ids)) != len(self.alternative_ids):
            raise ValueError(
                f"AlternativeGroup.alternative_ids tiene IDs repetidos: {self.alternative_ids!r}"
            )
        if self.selected_id is not None:
            if not isinstance(self.selected_id, str):
                raise TypeError(
                    f"AlternativeGroup.selected_id debe ser str o None, no "
                    f"{self.selected_id!r} ({type(self.selected_id).__name__})"
                )
            if self.selected_id not in self.alternative_ids:
                raise ValueError(
                    f"AlternativeGroup.selected_id={self.selected_id!r} no pertenece a "
                    f"alternative_ids={self.alternative_ids!r}"
                )


# ---------------------------------------------------------------------------
# InteractionSequence — covers_causes derivado, nunca declarado a mano
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class InteractionSequence:
    """Secuencia ordenada de pasos, con identidad estable y cobertura
    causal DERIVADA (nunca proporcionada como lista libre — `covers_causes`
    ni siquiera es un parámetro del constructor: `field(init=False)`).

    Una secuencia vacía es inválida (no representa ninguna interacción).
    Los `step_id` de sus pasos no se repiten. La derivación de
    `covers_causes` es determinista: mismo conjunto de pasos, mismo
    resultado (comparación por igualdad de conjunto, no por orden de
    iteración — un `frozenset` no promete orden estable entre procesos,
    pero sí contenido idéntico).

    No hay competencia entre secuencias en esta ronda: qué secuencia (si
    alguna) se selecciona para cubrir una causa dada, y que esa selección
    no dependa de "cuál tiene más precondiciones" ni del orden de
    registro, es un contrato de un mecanismo de selección futuro — este
    tipo solo representa UNA secuencia ya construida.
    """

    sequence_id: str
    steps: tuple[SequenceStep, ...]
    alternative_group: AlternativeGroup | None = None
    covers_causes: frozenset[EffectIdentity] = field(init=False, default=None)  # type: ignore[assignment]

    def __post_init__(self) -> None:
        _require_nonempty_string(self.sequence_id, field_name="InteractionSequence.sequence_id")

        if not isinstance(self.steps, tuple):
            raise TypeError(f"InteractionSequence.steps debe ser tuple, no {type(self.steps).__name__}")
        if not self.steps:
            raise ValueError("InteractionSequence.steps no puede estar vacío — una secuencia vacía es inválida")
        for step in self.steps:
            if not isinstance(step, SequenceStep):
                raise TypeError(
                    f"InteractionSequence.steps[] debe ser SequenceStep, no {step!r} "
                    f"({type(step).__name__})"
                )
        step_ids = [step.step_id for step in self.steps]
        if len(set(step_ids)) != len(step_ids):
            raise ValueError(f"InteractionSequence.steps tiene step_id repetidos: {step_ids!r}")

        if self.alternative_group is not None and not isinstance(self.alternative_group, AlternativeGroup):
            raise TypeError(
                f"InteractionSequence.alternative_group debe ser AlternativeGroup o None, no "
                f"{self.alternative_group!r} ({type(self.alternative_group).__name__})"
            )

        derived = frozenset(identity for step in self.steps for identity in step.consumes)
        object.__setattr__(self, "covers_causes", derived)


# ---------------------------------------------------------------------------
# Resultado de un paso evaluado + soporte de la cadena (eslabón más débil)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StepResult:
    """Resultado de haber evaluado UN paso: sus precondiciones ya
    resueltas a `PreconditionStatus`, y el `Support` resultante.

    Invariantes reforzadas en el propio tipo (no solo por convención de
    quien lo construye, ver `resolve_step_support` para la función pura
    que produce valores coherentes con estas reglas):
    - alguna precondición `UNSATISFIED` bloquea el paso -> `support` debe
      ser `None` (no hay soporte de una rama bloqueada);
    - sin precondiciones `UNSATISFIED`, el paso no está bloqueado ->
      `support` debe ser un `Support` real, nunca `None`;
    - alguna precondición `UNKNOWN` nunca permite `Support.STRUCTURAL`.
    """

    step_id: str
    precondition_statuses: tuple[PreconditionStatus, ...]
    support: Support | None

    def __post_init__(self) -> None:
        _require_nonempty_string(self.step_id, field_name="StepResult.step_id")

        if not isinstance(self.precondition_statuses, tuple):
            raise TypeError(
                f"StepResult.precondition_statuses debe ser tuple, no "
                f"{type(self.precondition_statuses).__name__}"
            )
        for status in self.precondition_statuses:
            if not isinstance(status, PreconditionStatus):
                raise TypeError(
                    f"StepResult.precondition_statuses[] debe ser PreconditionStatus, no "
                    f"{status!r} ({type(status).__name__})"
                )

        blocked = any(status is PreconditionStatus.UNSATISFIED for status in self.precondition_statuses)

        if self.support is not None and not isinstance(self.support, Support):
            raise TypeError(
                f"StepResult.support debe ser Support o None, no {self.support!r} "
                f"({type(self.support).__name__})"
            )

        if blocked and self.support is not None:
            raise ValueError(
                "StepResult con una precondición UNSATISFIED está bloqueado — no puede "
                f"declarar support (recibido {self.support!r})"
            )
        if not blocked and self.support is None:
            raise ValueError(
                "StepResult sin ninguna precondición UNSATISFIED no está bloqueado — debe "
                "declarar un Support real, no None"
            )

        has_unknown = any(status is PreconditionStatus.UNKNOWN for status in self.precondition_statuses)
        if has_unknown and self.support is Support.STRUCTURAL:
            raise ValueError(
                "StepResult con una precondición UNKNOWN no puede declarar Support.STRUCTURAL"
            )


def chain_support(step_results: Iterable[StepResult]) -> Support | None:
    """Soporte de una CADENA de pasos ya evaluados: el de su eslabón más
    débil, nunca un promedio. Si algún paso está bloqueado (`support is
    None`), toda la cadena queda bloqueada. Usa la misma prioridad
    explícita que `resolve_step_support` — nunca el orden de declaración
    accidental de `Support`.
    """

    results = tuple(step_results)
    if not results:
        raise ValueError("chain_support requiere al menos un StepResult")
    for result in results:
        if not isinstance(result, StepResult):
            raise TypeError(f"chain_support: cada elemento debe ser StepResult, no {result!r}")

    if any(result.support is None for result in results):
        return None
    return min((result.support for result in results), key=lambda support: _SUPPORT_PRIORITY[support])


# ---------------------------------------------------------------------------
# Resultado de un trade: no binario (diseño §B.8)
# ---------------------------------------------------------------------------


class Evaluation(str, Enum):
    """Lectura de un `StateDelta` — nunca una polaridad forzada. Distinta
    de `Polarity` (que solo conoce pro/contra/conditional): esta necesita
    además distinguir un resultado sin ganador claro (`NEUTRAL`) de uno
    que directamente no llegó a evaluarse (`UNRESOLVED`)."""

    CANDIDATE_FAVORED = "candidate_favored"
    ENEMY_FAVORED = "enemy_favored"
    NEUTRAL = "neutral"
    CONDITIONAL = "conditional"
    UNRESOLVED = "unresolved"


class TerminalEventKind(str, Enum):
    UNKNOWN = "unknown"
    NONE = "none"
    KILL = "kill"


@dataclass(frozen=True, slots=True)
class TerminalEvent:
    """Evento terminal opcional de un trade — nunca un requisito para que
    exista una `Evaluation`. `KILL` exige declarar qué actor murió; `NONE`
    (conocido: no hubo muerte) y `UNKNOWN` (no se evaluó) no admiten
    actor. No hay respawn, bounty ni ninguna otra simulación de muerte acá
    — solo esta distinción de tres estados."""

    kind: TerminalEventKind = TerminalEventKind.UNKNOWN
    actor: ActorRole | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, TerminalEventKind):
            raise TypeError(
                f"TerminalEvent.kind debe ser TerminalEventKind, no {self.kind!r} "
                f"({type(self.kind).__name__})"
            )
        if self.actor is not None and not isinstance(self.actor, ActorRole):
            raise TypeError(
                f"TerminalEvent.actor debe ser ActorRole o None, no {self.actor!r} "
                f"({type(self.actor).__name__})"
            )
        if self.kind is TerminalEventKind.KILL:
            if self.actor is None:
                raise ValueError("TerminalEvent.kind == KILL exige declarar `actor`")
        elif self.actor is not None:
            raise ValueError(
                f"TerminalEvent.kind == {self.kind.value!r} no admite `actor` (recibido "
                f"{self.actor!r}) — solo KILL declara quién murió"
            )


@dataclass(frozen=True, slots=True)
class StateDelta:
    """Cambio de estado auditable de un trade/secuencia: el `CombatState`
    anterior y el posterior, completos — no un resumen con pérdida. `K`
    (contrato de scoring) y un narrador futuro pueden comparar campo a
    campo sin que este tipo tenga que anticipar cuáles importan.

    No hashable: delega en `CombatState`, que tampoco lo es (contiene
    mappings congelados)."""

    before: CombatState
    after: CombatState

    __hash__ = None  # type: ignore[assignment]  # CombatState no es hashable

    def __post_init__(self) -> None:
        if not isinstance(self.before, CombatState):
            raise TypeError(
                f"StateDelta.before debe ser CombatState, no {self.before!r} "
                f"({type(self.before).__name__})"
            )
        if not isinstance(self.after, CombatState):
            raise TypeError(
                f"StateDelta.after debe ser CombatState, no {self.after!r} "
                f"({type(self.after).__name__})"
            )


@dataclass(frozen=True, slots=True)
class TradeOutcome:
    """Resultado no binario de un trade (diseño §B.8): el cambio de
    estado, cómo se lee ese cambio, y un evento terminal opcional. Ninguna
    `Evaluation` se calcula automáticamente acá — se declara con la
    evidencia que exista; una futura etapa decide con qué evidencia basta.
    """

    state_delta: StateDelta
    evaluation: Evaluation
    terminal_event: TerminalEvent = field(default_factory=TerminalEvent)

    __hash__ = None  # type: ignore[assignment]  # contiene un StateDelta no hashable

    def __post_init__(self) -> None:
        if not isinstance(self.state_delta, StateDelta):
            raise TypeError(
                f"TradeOutcome.state_delta debe ser StateDelta, no {self.state_delta!r} "
                f"({type(self.state_delta).__name__})"
            )
        if not isinstance(self.evaluation, Evaluation):
            raise TypeError(
                f"TradeOutcome.evaluation debe ser Evaluation, no {self.evaluation!r} "
                f"({type(self.evaluation).__name__})"
            )
        if not isinstance(self.terminal_event, TerminalEvent):
            raise TypeError(
                f"TradeOutcome.terminal_event debe ser TerminalEvent, no {self.terminal_event!r} "
                f"({type(self.terminal_event).__name__})"
            )


# ---------------------------------------------------------------------------
# Componentes causales — representación, sin envío al scorer todavía
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CausalComponent:
    """Un componente causal individual dentro de una secuencia — puede
    haber varios por secuencia, cada uno con su propio `factor`/`delta`
    originales, nunca fusionados entre sí ni reinventados por estar
    "envueltos" dentro de una secuencia (diseño §B.11). Reutiliza
    `Factor`/`Provenance`/`Polarity` de `domain.enums` — no declara
    vocabulario paralelo.

    Esta etapa solo REPRESENTA el componente; no lo envía a
    `scoring`/`RuleEffect` (eso es K, ya existente y sin cambios)."""

    factor: Factor
    delta: float
    provenance: Provenance
    fact_ref: str  # referencia al hecho mecánico concreto que originó este componente
    sequence_id: str  # referencia común a la secuencia que lo produjo
    polarity: Polarity | None = None  # solo cuando corresponde una dirección firmada

    def __post_init__(self) -> None:
        if not isinstance(self.factor, Factor):
            raise TypeError(
                f"CausalComponent.factor debe ser Factor, no {self.factor!r} ({type(self.factor).__name__})"
            )
        if isinstance(self.delta, bool) or not isinstance(self.delta, (int, float)):
            raise TypeError(
                f"CausalComponent.delta debe ser un número real, no {self.delta!r} "
                f"({type(self.delta).__name__})"
            )
        if not isinstance(self.provenance, Provenance):
            raise TypeError(
                f"CausalComponent.provenance debe ser Provenance, no {self.provenance!r} "
                f"({type(self.provenance).__name__})"
            )
        _require_nonempty_string(self.fact_ref, field_name="CausalComponent.fact_ref")
        _require_nonempty_string(self.sequence_id, field_name="CausalComponent.sequence_id")
        if self.polarity is not None and not isinstance(self.polarity, Polarity):
            raise TypeError(
                f"CausalComponent.polarity debe ser Polarity o None, no {self.polarity!r} "
                f"({type(self.polarity).__name__})"
            )


# ---------------------------------------------------------------------------
# ScenarioOutcome — enlace genérico, sin emitir RuleEffect ni tocar el score
# ---------------------------------------------------------------------------

_UNSIGNED_EVALUATIONS = (Evaluation.NEUTRAL, Evaluation.CONDITIONAL, Evaluation.UNRESOLVED)


@dataclass(frozen=True, slots=True)
class ScenarioOutcome:
    """Resultado de haber evaluado una `InteractionSequence` contra un
    escenario: sus resultados por paso, el soporte agregado de la cadena
    (derivado, `field(init=False)` — nunca declarado a mano), el
    `TradeOutcome` si corresponde, la selección de rama si la secuencia
    pertenece a un `AlternativeGroup`, y los `CausalComponent` que
    produjo, si los produjo.

    Invariantes reforzadas en construcción (diseño §B.10):
    - una rama bloqueada (`support is None`) no puede tener
      `causal_components`;
    - una selección de rama irresuelta (`branch_selection.selected_id is
      None`) tampoco puede tenerlos;
    - solo `Evaluation.CANDIDATE_FAVORED`/`ENEMY_FAVORED` pueden tener
      `CausalComponent` con `polarity` firmada — `NEUTRAL`/`CONDITIONAL`/
      `UNRESOLVED` nunca fuerzan una polaridad.

    No emite `RuleEffect` ni modifica `MatchupScore` — eso pertenece al
    contrato K, ya existente, sin cambios en esta ronda."""

    sequence: InteractionSequence
    step_results: tuple[StepResult, ...]
    trade_outcome: TradeOutcome | None = None
    branch_selection: AlternativeGroup | None = None
    causal_components: tuple[CausalComponent, ...] = field(default_factory=tuple)
    support: Support | None = field(init=False, default=None)

    __hash__ = None  # type: ignore[assignment]  # puede contener un TradeOutcome no hashable

    def __post_init__(self) -> None:
        if not isinstance(self.sequence, InteractionSequence):
            raise TypeError(
                f"ScenarioOutcome.sequence debe ser InteractionSequence, no {self.sequence!r} "
                f"({type(self.sequence).__name__})"
            )
        if not isinstance(self.step_results, tuple):
            raise TypeError(
                f"ScenarioOutcome.step_results debe ser tuple, no {type(self.step_results).__name__}"
            )
        for result in self.step_results:
            if not isinstance(result, StepResult):
                raise TypeError(
                    f"ScenarioOutcome.step_results[] debe ser StepResult, no {result!r} "
                    f"({type(result).__name__})"
                )
        declared_step_ids = {step.step_id for step in self.sequence.steps}
        seen_result_ids: set[str] = set()
        for result in self.step_results:
            if result.step_id not in declared_step_ids:
                raise ValueError(
                    f"ScenarioOutcome.step_results referencia step_id={result.step_id!r}, "
                    f"que no pertenece a sequence.steps de {self.sequence.sequence_id!r}"
                )
            if result.step_id in seen_result_ids:
                raise ValueError(
                    f"ScenarioOutcome.step_results tiene step_id repetido: {result.step_id!r}"
                )
            seen_result_ids.add(result.step_id)

        if self.trade_outcome is not None and not isinstance(self.trade_outcome, TradeOutcome):
            raise TypeError(
                f"ScenarioOutcome.trade_outcome debe ser TradeOutcome o None, no "
                f"{self.trade_outcome!r} ({type(self.trade_outcome).__name__})"
            )
        if self.branch_selection is not None and not isinstance(self.branch_selection, AlternativeGroup):
            raise TypeError(
                f"ScenarioOutcome.branch_selection debe ser AlternativeGroup o None, no "
                f"{self.branch_selection!r} ({type(self.branch_selection).__name__})"
            )
        if not isinstance(self.causal_components, tuple):
            raise TypeError(
                f"ScenarioOutcome.causal_components debe ser tuple, no "
                f"{type(self.causal_components).__name__}"
            )
        for component in self.causal_components:
            if not isinstance(component, CausalComponent):
                raise TypeError(
                    f"ScenarioOutcome.causal_components[] debe ser CausalComponent, no "
                    f"{component!r} ({type(component).__name__})"
                )

        resolved_support = chain_support(self.step_results) if self.step_results else None
        object.__setattr__(self, "support", resolved_support)

        blocked = resolved_support is None
        if blocked and self.causal_components:
            raise ValueError(
                "ScenarioOutcome bloqueado (support=None) no puede tener causal_components"
            )
        if (
            self.branch_selection is not None
            and self.branch_selection.selected_id is None
            and self.causal_components
        ):
            raise ValueError(
                "ScenarioOutcome con branch_selection irresuelta (selected_id=None) no puede "
                "tener causal_components"
            )
        if self.trade_outcome is not None and self.trade_outcome.evaluation in _UNSIGNED_EVALUATIONS:
            if any(component.polarity is not None for component in self.causal_components):
                raise ValueError(
                    f"ScenarioOutcome con evaluation={self.trade_outcome.evaluation!r} no puede "
                    "tener CausalComponent con polaridad firmada — solo CANDIDATE_FAVORED/"
                    "ENEMY_FAVORED pueden tener componentes firmados"
                )
