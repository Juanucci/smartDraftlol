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

from lol_reasoner.domain.combat_state import CombatState, combat_state_to_primitive
from lol_reasoner.domain.enums import Factor, Polarity, Provenance, Support
from lol_reasoner.reasoning.sequences.steps import (
    _SUPPORT_PRIORITY,
    ActorRole,
    EffectIdentity,
    PreconditionStatus,
    SequenceStep,
    _effect_identity_to_primitive,
    _require_nonempty_string,
    _sequence_step_to_primitive,
    resolve_step_support,
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

    **`alternative_id`** (cierre de Etapa 2, §A2): si esta secuencia es UNA
    alternativa dentro de un `AlternativeGroup` (p. ej. "autoataque" vs "Q"
    como follow-up de un mismo punto de decisión), declara EXACTAMENTE cuál
    — nunca solo el grupo entero sin decir cuál de sus miembros es esta
    secuencia. `alternative_group` y `alternative_id` se declaran juntos o
    ninguno de los dos, y `alternative_id` debe pertenecer a
    `alternative_group.alternative_ids`. Esto es lo que permite que
    `ScenarioOutcome` compruebe, más adelante, que la selección de rama que
    recibe coincide exactamente con la alternativa que esta secuencia
    representa — no solo con el grupo.
    """

    sequence_id: str
    steps: tuple[SequenceStep, ...]
    alternative_group: AlternativeGroup | None = None
    alternative_id: str | None = None
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
        if (self.alternative_group is None) != (self.alternative_id is None):
            raise ValueError(
                "InteractionSequence.alternative_group y alternative_id deben declararse "
                f"juntos o ninguno de los dos (alternative_group={self.alternative_group!r}, "
                f"alternative_id={self.alternative_id!r})"
            )
        if self.alternative_id is not None:
            _require_nonempty_string(self.alternative_id, field_name="InteractionSequence.alternative_id")
            if self.alternative_id not in self.alternative_group.alternative_ids:  # type: ignore[union-attr]
                raise ValueError(
                    f"InteractionSequence.alternative_id={self.alternative_id!r} no pertenece a "
                    f"alternative_group.alternative_ids={self.alternative_group.alternative_ids!r}"  # type: ignore[union-attr]
                )

        derived = frozenset(identity for step in self.steps for identity in step.consumes)
        object.__setattr__(self, "covers_causes", derived)


# ---------------------------------------------------------------------------
# Estado de EJECUCIÓN — distinto del soporte (§ microfix "distinguish
# projected and executed sequence state")
# ---------------------------------------------------------------------------
#
# `Support` (STRUCTURAL/CONDITIONED/AMBIGUOUS) responde "¿cuánta certeza
# respalda esta inclinación?" — un eje de CALIBRACIÓN heredado de
# domain.enums, pensado para scoring. `ExecutionStatus` responde una
# pregunta DISTINTA y más simple, que scoring nunca necesitó hasta que
# hubo una secuencia real evaluando precondiciones de ejecución: "¿lo que
# describe este StepResult/ScenarioOutcome ya ocurrió, es una proyección
# bajo hipótesis, o quedó bloqueado?" Sin este eje, `progress=COMPLETED`
# (la cadena terminó de evaluarse) se confundía con "el StateDelta.after
# es un hecho confirmado" — dos preguntas distintas: una secuencia puede
# completar su evaluación entera y, a la vez, no tener ninguna garantía de
# que lo que proyectó haya ocurrido de verdad.
#
# Contrato mínimo elegido: `execution_status` no duplica `CombatState` ni
# introduce un segundo motor — es un rotulado DERIVADO de la MISMA
# evidencia (`precondition_statuses`) que ya produce `effective_support`,
# adjunto a `StepResult`/`ScenarioOutcome` (y por lo tanto visible junto a
# `TradeOutcome.state_delta` en la serialización). El `StateDelta.after`
# de un outcome con `execution_status=HYPOTHETICAL` sigue siendo el mismo
# tipo `CombatState` de siempre — lo que cambia es que el consumidor ahora
# puede leer, en el mismo outcome, que ese "after" es una PROYECCIÓN bajo
# hipótesis y no una mutación confirmada.


class ExecutionStatus(str, Enum):
    """Certeza de EJECUCIÓN de un paso/cadena — derivada exclusivamente de
    `precondition_statuses` (la misma entrada que ya resuelve
    `effective_support`), nunca un dato de entrada independiente: no hay
    manera de que quede desalineada con las precondiciones que dice
    describir.

    - `CONFIRMED`: ninguna precondición `UNKNOWN` ni `UNSATISFIED` — lo
      que el paso/cadena describe es un hecho, no una hipótesis.
    - `HYPOTHETICAL`: sin `UNSATISFIED`, pero con alguna `UNKNOWN` — el
      paso se evaluó y no está bloqueado, pero su resultado (y el
      `StateDelta` que produce) es una PROYECCIÓN bajo una hipótesis de
      ejecución, no una mutación confirmada.
    - `BLOCKED`: alguna precondición `UNSATISFIED` — no se produjo
      transición (mismo caso que `effective_support is None`).
    """

    CONFIRMED = "confirmed"
    HYPOTHETICAL = "hypothetical"
    BLOCKED = "blocked"


# Prioridad EXPLÍCITA para el eslabón más débil de este eje — nunca el
# orden de declaración accidental del enum (mismo principio que
# `_SUPPORT_PRIORITY`).
_EXECUTION_STATUS_PRIORITY: dict[ExecutionStatus, int] = {
    ExecutionStatus.BLOCKED: 0,
    ExecutionStatus.HYPOTHETICAL: 1,
    ExecutionStatus.CONFIRMED: 2,
}


def execution_status_of(precondition_statuses: tuple[PreconditionStatus, ...]) -> ExecutionStatus:
    """Deriva el `ExecutionStatus` de UN paso a partir de sus
    `precondition_statuses` — función pura, misma entrada que
    `resolve_step_support`, ningún dato adicional."""

    if any(status is PreconditionStatus.UNSATISFIED for status in precondition_statuses):
        return ExecutionStatus.BLOCKED
    if any(status is PreconditionStatus.UNKNOWN for status in precondition_statuses):
        return ExecutionStatus.HYPOTHETICAL
    return ExecutionStatus.CONFIRMED


def chain_execution_status(step_results: Iterable["StepResult"]) -> ExecutionStatus:
    """`ExecutionStatus` de una CADENA de pasos: el de su eslabón más
    débil (`BLOCKED` domina sobre `HYPOTHETICAL`, que domina sobre
    `CONFIRMED`) — nunca un promedio, misma filosofía que `chain_support`.
    """

    results = tuple(step_results)
    if not results:
        raise ValueError("chain_execution_status requiere al menos un StepResult")
    for result in results:
        if not isinstance(result, StepResult):
            raise TypeError(f"chain_execution_status: cada elemento debe ser StepResult, no {result!r}")
    return min((result.execution_status for result in results), key=lambda status: _EXECUTION_STATUS_PRIORITY[status])


# ---------------------------------------------------------------------------
# Resultado de un paso evaluado + soporte de la cadena (eslabón más débil)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StepResult:
    """Resultado de haber evaluado UN paso.

    **Una única fuente de verdad para el soporte** (cierre de Etapa 2,
    §A4): `declared_support` es el ÚNICO dato de entrada — la certeza que
    tendría este paso SI todas sus precondiciones se sostuvieran (lo que
    una regla/hecho mecánico declararía en el mejor caso). `effective_support`
    NUNCA es un dato de entrada — es `field(init=False)`, y se DERIVA en
    `__post_init__` con la misma función pura `resolve_step_support` que ya
    aplicaba esta regla (§B.5): imposible pasarlo por `__init__` (lanza
    `TypeError`, igual que `InteractionSequence.covers_causes`), e
    imposible que quede contradictorio con `precondition_statuses` — no hay
    dos fuentes de verdad que puedan desalinearse, solo una función que
    siempre las resuelve de la misma manera:
    - alguna precondición `UNSATISFIED` -> `effective_support = None`
      (paso bloqueado, sin nivel de soporte);
    - alguna precondición `UNKNOWN` sin bloqueo -> como mucho `CONDITIONED`,
      nunca `STRUCTURAL`;
    - sin `UNKNOWN` ni `UNSATISFIED` -> `effective_support = declared_support`.
    """

    step_id: str
    precondition_statuses: tuple[PreconditionStatus, ...]
    declared_support: Support
    effective_support: Support | None = field(init=False, default=None)
    execution_status: "ExecutionStatus" = field(init=False, default=None)  # type: ignore[assignment]

    def __post_init__(self) -> None:
        _require_nonempty_string(self.step_id, field_name="StepResult.step_id")

        if not isinstance(self.precondition_statuses, tuple):
            raise TypeError(
                f"StepResult.precondition_statuses debe ser tuple, no "
                f"{type(self.precondition_statuses).__name__}"
            )

        # `resolve_step_support` valida tanto `declared_support` como cada
        # `precondition_statuses[]` (TypeError si el tipo no corresponde) y
        # es la ÚNICA lógica que decide effective_support — StepResult no
        # duplica esa decisión, solo la invoca y la fija.
        effective = resolve_step_support(
            declared_support=self.declared_support, precondition_statuses=self.precondition_statuses
        )
        object.__setattr__(self, "effective_support", effective)
        object.__setattr__(self, "execution_status", execution_status_of(self.precondition_statuses))


def chain_support(step_results: Iterable[StepResult]) -> Support | None:
    """Soporte de una CADENA de pasos ya evaluados: el de su eslabón más
    débil (por `effective_support`, la única fuente de verdad — nunca
    `declared_support`), nunca un promedio. Si algún paso está bloqueado
    (`effective_support is None`), toda la cadena queda bloqueada. Usa la
    misma prioridad explícita que `resolve_step_support` — nunca el orden
    de declaración accidental de `Support`.
    """

    results = tuple(step_results)
    if not results:
        raise ValueError("chain_support requiere al menos un StepResult")
    for result in results:
        if not isinstance(result, StepResult):
            raise TypeError(f"chain_support: cada elemento debe ser StepResult, no {result!r}")

    if any(result.effective_support is None for result in results):
        return None
    return min(
        (result.effective_support for result in results), key=lambda support: _SUPPORT_PRIORITY[support]
    )


# ---------------------------------------------------------------------------
# Progreso de una secuencia evaluada: prefijo ordenado, nunca arbitrario
# ---------------------------------------------------------------------------


class SequenceProgress(str, Enum):
    """Clasificación explícita de cuánto de una `InteractionSequence` fue
    efectivamente evaluado (cierre de Etapa 2, §A1) — ninguna de las cuatro
    situaciones se superpone con otra:

    - `NOT_STARTED`: `step_results` vacío. Estructuralmente indistinguible
      de "bloqueada antes del primer paso" o de un resultado `UNRESOLVED`
      declarado en `TradeOutcome` — ninguno de los dos produce un
      `StepResult`, así que no hay dato acá para diferenciarlos; esa
      distinción, si hace falta, la lleva `TradeOutcome.evaluation`.
    - `BLOCKED`: el último `StepResult` está bloqueado
      (`effective_support is None`) — incluso si su cantidad coincide con
      el total de pasos, un bloqueo nunca es una finalización exitosa.
    - `COMPLETED`: la cantidad de resultados iguala la cantidad de pasos de
      la secuencia, y el último no está bloqueado.
    - `PARTIAL`: cualquier prefijo no vacío que no sea ni `BLOCKED` ni
      `COMPLETED`.
    """

    NOT_STARTED = "not_started"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    COMPLETED = "completed"


def sequence_progress(
    *, sequence: InteractionSequence, step_results: tuple[StepResult, ...]
) -> SequenceProgress:
    """Clasifica el progreso de `step_results` para `sequence` — asume que
    `step_results` ya es un prefijo válido y ordenado de `sequence.steps`
    (esa validación estructural vive en `ScenarioOutcome.__post_init__`,
    que es quien llama a esta función)."""

    if not step_results:
        return SequenceProgress.NOT_STARTED
    if step_results[-1].effective_support is None:
        return SequenceProgress.BLOCKED
    if len(step_results) == len(sequence.steps):
        return SequenceProgress.COMPLETED
    return SequenceProgress.PARTIAL


def require_sequence_progress(
    *, sequence: InteractionSequence, step_results: tuple[StepResult, ...], expected: SequenceProgress
) -> None:
    """Guarda pura para un motor/builder futuro que necesite AFIRMAR en qué
    estado de avance espera encontrar una secuencia evaluada (p. ej. "esto
    debería estar completo") y fallar explícitamente si no lo está — en vez
    de asumir en silencio el mejor caso. No es un campo de `ScenarioOutcome`
    (que deriva `progress` sin intervención del caller, ver
    `sequence_progress`): es una verificación externa opcional, para quien
    la necesite."""

    actual = sequence_progress(sequence=sequence, step_results=step_results)
    if actual is not expected:
        raise ValueError(
            f"Se esperaba progreso {expected.value!r} para la secuencia "
            f"{sequence.sequence_id!r}, pero es {actual.value!r} "
            f"({len(step_results)}/{len(sequence.steps)} pasos evaluados)"
        )


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
    exista una `Evaluation`. `KILL` exige declarar quién murió, en
    `killed_actors`; `NONE` (conocido: no hubo muerte) y `UNKNOWN` (no se
    evaluó) exigen `killed_actors` vacío.

    **Ambos actores muertos es un caso válido** (cierre de Etapa 2, §A3):
    `killed_actors` es una colección inmutable, no un único actor opcional
    — permite representar `()`, `(CANDIDATE,)`, `(ENEMY,)` o
    `(CANDIDATE, ENEMY)` sin ambigüedad, sin repetir un actor, y sin
    admitir ningún `ActorRole` que no sea `CANDIDATE`/`ENEMY`. No hay
    respawn, bounty, asistencia, torre ni causa temporal de la muerte acá
    — solo esta distinción de tres estados con 0/1/2 actores.
    """

    kind: TerminalEventKind = TerminalEventKind.UNKNOWN
    killed_actors: tuple[ActorRole, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, TerminalEventKind):
            raise TypeError(
                f"TerminalEvent.kind debe ser TerminalEventKind, no {self.kind!r} "
                f"({type(self.kind).__name__})"
            )
        if not isinstance(self.killed_actors, tuple):
            raise TypeError(
                f"TerminalEvent.killed_actors debe ser tuple, no {type(self.killed_actors).__name__}"
            )
        for actor in self.killed_actors:
            if not isinstance(actor, ActorRole):
                raise TypeError(
                    f"TerminalEvent.killed_actors[] debe ser ActorRole, no {actor!r} "
                    f"({type(actor).__name__})"
                )
        if len(set(self.killed_actors)) != len(self.killed_actors):
            raise ValueError(f"TerminalEvent.killed_actors no puede repetir un actor: {self.killed_actors!r}")

        if self.kind is TerminalEventKind.KILL:
            if not self.killed_actors:
                raise ValueError("TerminalEvent.kind == KILL exige al menos un actor en killed_actors")
        elif self.killed_actors:
            raise ValueError(
                f"TerminalEvent.kind == {self.kind.value!r} no admite killed_actors (recibido "
                f"{self.killed_actors!r}) — solo KILL declara quién murió"
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
    escenario: sus resultados por paso (un PREFIJO ordenado, nunca un
    subconjunto arbitrario — ver `progress`), el soporte agregado de la
    cadena (derivado, `field(init=False)` — nunca declarado a mano), el
    `TradeOutcome` si corresponde, la selección de rama si la secuencia
    pertenece a un `AlternativeGroup`, y los `CausalComponent` que
    produjo, si los produjo.

    **`step_results` debe ser un prefijo ordenado** (cierre de Etapa 2,
    §A1): si `sequence.steps` es `[p1, p2, p3]`, los únicos
    `step_results` válidos son `[]`, `[p1]`, `[p1, p2]` o `[p1, p2, p3]`
    — nunca `[p2]`, `[p1, p3]` ni `[p2, p1]`. Un paso bloqueado
    (`effective_support is None`) debe ser el ÚLTIMO de la lista: no puede
    haber un resultado posterior a un bloqueo. `progress` (derivado, ver
    `SequenceProgress`/`sequence_progress`) clasifica el resultado en
    `NOT_STARTED`/`PARTIAL`/`BLOCKED`/`COMPLETED`.

    **Coherencia secuencia ↔ selección de rama** (cierre de Etapa 2, §A2):
    si `sequence` pertenece a un `AlternativeGroup` (`sequence.alternative_group`
    no `None`), una `branch_selection` ajena (grupo distinto) es inválida,
    y una secuencia SIN grupo no puede recibir ninguna `branch_selection`
    (`ValueError` en ambos casos — no son solo restricciones de
    `causal_components`). Cuando el grupo coincide, `causal_components` solo
    se admite si `branch_selection.selected_id` coincide EXACTAMENTE con
    `sequence.alternative_id` — la alternativa de esta secuencia; una
    alternativa distinta seleccionada, una selección ausente, o una
    selección irresuelta (`selected_id=None`) nunca producen componentes
    puntuables para esta secuencia.

    Invariantes reforzadas en construcción (diseño §B.10):
    - una rama bloqueada (`support is None`) no puede tener
      `causal_components`;
    - una alternativa no confirmada como la seleccionada (ver arriba)
      tampoco puede tenerlos;
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
    progress: SequenceProgress = field(init=False, default=None)  # type: ignore[assignment]
    execution_status: ExecutionStatus | None = field(init=False, default=None)

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

        # --- §A1: step_results debe ser EXACTAMENTE un prefijo ordenado de
        # sequence.steps — nunca un subconjunto arbitrario ni un orden
        # distinto al declarado por la propia secuencia.
        declared_step_ids = [step.step_id for step in self.sequence.steps]
        declared_step_id_set = set(declared_step_ids)
        result_step_ids = [result.step_id for result in self.step_results]

        seen_result_ids: set[str] = set()
        for step_id in result_step_ids:
            if step_id not in declared_step_id_set:
                raise ValueError(
                    f"ScenarioOutcome.step_results referencia step_id={step_id!r}, que no "
                    f"pertenece a sequence.steps de {self.sequence.sequence_id!r}"
                )
            if step_id in seen_result_ids:
                raise ValueError(f"ScenarioOutcome.step_results tiene step_id repetido: {step_id!r}")
            seen_result_ids.add(step_id)

        expected_prefix = declared_step_ids[: len(result_step_ids)]
        if result_step_ids != expected_prefix:
            raise ValueError(
                "ScenarioOutcome.step_results debe formar exactamente el prefijo ordenado "
                f"{expected_prefix!r} de sequence.steps (derivado del orden declarado en la "
                f"secuencia, no del orden del caller) — recibido {result_step_ids!r}"
            )

        for index, result in enumerate(self.step_results):
            is_last = index == len(self.step_results) - 1
            if result.effective_support is None and not is_last:
                raise ValueError(
                    f"ScenarioOutcome.step_results tiene un StepResult bloqueado "
                    f"({result.step_id!r}) que no es el último — no puede haber resultados "
                    "posteriores a un paso bloqueado"
                )

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
        object.__setattr__(
            self, "progress", sequence_progress(sequence=self.sequence, step_results=self.step_results)
        )
        object.__setattr__(
            self,
            "execution_status",
            chain_execution_status(self.step_results) if self.step_results else None,
        )

        # --- §A2: coherencia secuencia <-> selección de rama. Estructural
        # (siempre se rechaza), independiente de si hay causal_components.
        sequence_group = self.sequence.alternative_group
        sequence_alt_id = self.sequence.alternative_id
        selection_confirms_this_alternative = True
        if sequence_group is None:
            if self.branch_selection is not None:
                raise ValueError(
                    f"ScenarioOutcome.branch_selection fue provista pero la secuencia "
                    f"{self.sequence.sequence_id!r} no pertenece a ningún AlternativeGroup — "
                    "no se admite una selección de rama ajena"
                )
        else:
            if self.branch_selection is None:
                selection_confirms_this_alternative = False
            else:
                if self.branch_selection.group_id != sequence_group.group_id:
                    raise ValueError(
                        f"ScenarioOutcome.branch_selection.group_id="
                        f"{self.branch_selection.group_id!r} no coincide con "
                        f"sequence.alternative_group.group_id={sequence_group.group_id!r}"
                    )
                selection_confirms_this_alternative = self.branch_selection.selected_id == sequence_alt_id

        blocked = resolved_support is None
        if blocked and self.causal_components:
            raise ValueError(
                "ScenarioOutcome bloqueado (support=None) no puede tener causal_components"
            )
        if not selection_confirms_this_alternative and self.causal_components:
            raise ValueError(
                "ScenarioOutcome no puede tener causal_components: la selección de rama no "
                f"confirma la alternativa de esta secuencia (alternative_id={sequence_alt_id!r}, "
                f"branch_selection={self.branch_selection!r}) — una alternativa no seleccionada, "
                "ausente o irresuelta nunca produce componentes puntuables"
            )
        if self.trade_outcome is not None and self.trade_outcome.evaluation in _UNSIGNED_EVALUATIONS:
            if any(component.polarity is not None for component in self.causal_components):
                raise ValueError(
                    f"ScenarioOutcome con evaluation={self.trade_outcome.evaluation!r} no puede "
                    "tener CausalComponent con polaridad firmada — solo CANDIDATE_FAVORED/"
                    "ENEMY_FAVORED pueden tener componentes firmados"
                )


# ---------------------------------------------------------------------------
# Frontera de serialización explícita (cierre de Etapa 2, §A6)
# ---------------------------------------------------------------------------
#
# Misma razón que `domain.combat_state.combat_state_to_primitive`:
# `dataclasses.asdict()` no sabe copiar los `MappingProxyType` internos de
# un `CombatState` (que `StateDelta` referencia), así que tampoco puede
# usarse sobre ningún tipo de este módulo que lo contenga transitivamente.
# Esta es la única frontera aprobada para convertir un `ScenarioOutcome` (o
# una `InteractionSequence` suelta) a datos primitivos JSON-compatibles —
# pura, no muta nada, construye colecciones NUEVAS (nunca expone la tupla o
# el frozenset original), y con orden determinista incluso para
# `covers_causes` (un `frozenset`, cuyo orden de iteración no está
# garantizado entre procesos — se ordena explícitamente antes de listar).
# API pública deliberadamente pequeña: dos funciones (`sequence_to_primitive`,
# `scenario_outcome_to_primitive`); el resto son helpers privados por tipo.


def _step_result_to_primitive(result: StepResult) -> dict[str, object]:
    return {
        "step_id": result.step_id,
        "precondition_statuses": [status.value for status in result.precondition_statuses],
        "declared_support": result.declared_support.value,
        "effective_support": result.effective_support.value if result.effective_support is not None else None,
        "execution_status": result.execution_status.value,
    }


def _alternative_group_to_primitive(group: AlternativeGroup) -> dict[str, object]:
    return {
        "group_id": group.group_id,
        "alternative_ids": list(group.alternative_ids),
        "selected_id": group.selected_id,
    }


def _terminal_event_to_primitive(event: TerminalEvent) -> dict[str, object]:
    return {
        "kind": event.kind.value,
        "killed_actors": [actor.value for actor in event.killed_actors],
    }


def _state_delta_to_primitive(delta: StateDelta) -> dict[str, object]:
    # Reutiliza combat_state_to_primitive — nunca reimplementa la
    # conversión de CombatState acá (requisito explícito de §A6).
    return {
        "before": combat_state_to_primitive(delta.before),
        "after": combat_state_to_primitive(delta.after),
    }


def _trade_outcome_to_primitive(trade: TradeOutcome) -> dict[str, object]:
    return {
        "state_delta": _state_delta_to_primitive(trade.state_delta),
        "evaluation": trade.evaluation.value,
        "terminal_event": _terminal_event_to_primitive(trade.terminal_event),
    }


def _causal_component_to_primitive(component: CausalComponent) -> dict[str, object]:
    return {
        "factor": component.factor.value,
        "delta": component.delta,
        "provenance": component.provenance.value,
        "fact_ref": component.fact_ref,
        "sequence_id": component.sequence_id,
        "polarity": component.polarity.value if component.polarity is not None else None,
    }


def _sorted_covers_causes_to_primitive(covers_causes: frozenset[EffectIdentity]) -> list[dict[str, object]]:
    primitives = [_effect_identity_to_primitive(identity) for identity in covers_causes]
    # Orden determinista explícito: un frozenset no promete orden estable
    # de iteración entre procesos (hashing de strings puede variar).
    primitives.sort(key=lambda item: (item["fact_ref"], item["causal_role"], item["component"]))
    return primitives


def sequence_to_primitive(sequence: InteractionSequence) -> dict[str, object]:
    """Convierte UNA `InteractionSequence` (sin resultados de evaluación)
    a datos primitivos JSON-compatibles. No muta `sequence` ni expone
    ninguna referencia mutable hacia sus tuplas/frozenset internos."""

    if not isinstance(sequence, InteractionSequence):
        raise TypeError(
            f"sequence_to_primitive espera una InteractionSequence, no {sequence!r} "
            f"({type(sequence).__name__})"
        )
    return {
        "sequence_id": sequence.sequence_id,
        "steps": [_sequence_step_to_primitive(step) for step in sequence.steps],
        "alternative_group": (
            _alternative_group_to_primitive(sequence.alternative_group)
            if sequence.alternative_group is not None
            else None
        ),
        "alternative_id": sequence.alternative_id,
        "covers_causes": _sorted_covers_causes_to_primitive(sequence.covers_causes),
    }


def scenario_outcome_to_primitive(outcome: ScenarioOutcome) -> dict[str, object]:
    """Convierte un `ScenarioOutcome` completo a datos primitivos
    JSON-compatibles (`dict`/`list`/`str`/`int`/`float`/`bool`/`None`).

    Esta es la frontera de serialización aprobada para el diagnóstico
    shadow de una secuencia (una etapa futura, no esta). **No usar
    `dataclasses.asdict()`** sobre `ScenarioOutcome` ni sobre ningún tipo
    que contenga, transitivamente, un `CombatState` — no sabe copiar sus
    `MappingProxyType` internos. No implementa deserialización ni
    persistencia en disco.
    """

    if not isinstance(outcome, ScenarioOutcome):
        raise TypeError(
            f"scenario_outcome_to_primitive espera un ScenarioOutcome, no {outcome!r} "
            f"({type(outcome).__name__})"
        )
    return {
        "sequence": sequence_to_primitive(outcome.sequence),
        "step_results": [_step_result_to_primitive(result) for result in outcome.step_results],
        "progress": outcome.progress.value,
        "support": outcome.support.value if outcome.support is not None else None,
        "execution_status": outcome.execution_status.value if outcome.execution_status is not None else None,
        "trade_outcome": (
            _trade_outcome_to_primitive(outcome.trade_outcome) if outcome.trade_outcome is not None else None
        ),
        "branch_selection": (
            _alternative_group_to_primitive(outcome.branch_selection)
            if outcome.branch_selection is not None
            else None
        ),
        "causal_components": [
            _causal_component_to_primitive(component) for component in outcome.causal_components
        ],
    }
