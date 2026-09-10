"""Estado táctico de un escenario (v1.7, Etapa 1).

Tipos puros para representar el `CombatState` documentado en
`docs/design/v1.7-sequence-state-design.md` §B.2/B.8: nivel exacto,
banda de vida, recurso, stacks tipados, reservas, disponibilidad de
habilidades por actor, y contexto compartido (oleada + un `ActionContext`
por acción, con su propio rango/aislamiento/invalidadores).

**Alcance de esta etapa**: solo el modelo tipado y sus invariantes de
construcción. Ningún motor de transiciones, ninguna secuencia concreta,
ningún generador de escenarios y ningún nombre de campeón/habilidad/
matchup vive acá — eso es responsabilidad de rondas de implementación
posteriores (ver el documento de diseño, secciones B.7/B.9/C en adelante).

**Vocabulario nuevo, deliberadamente separado de `domain.enums`**: los
enums de este módulo describen el estado *dinámico* de un escenario
hipotético, no el kit *estático* de un campeón (eso es lo que ya cubre
`domain.enums`/`domain.champion`). Mezclarlos confundiría "qué puede hacer
este campeón" con "qué está pasando ahora mismo en este escenario".

**Regla de las tres/cuatro lecturas, aplicada en todo este módulo**
(diseño §B.2, "Regla general para todo campo de `ActorState`"):
para un campo `dict[id, valor]` (`stacks`, `reserves`,
`abilities_available`, `invalidators`): clave ausente = la mecánica no
existe para este actor/acción; clave presente con el miembro `UNKNOWN` del
enum correspondiente = existe, pero no se declaró su estado en este
escenario; clave presente con cualquier otro miembro = estado conocido,
incluido el extremo "vacío" (p. ej. `ReserveBand.NONE`), que es un
conocido distinto de `UNKNOWN`. Para un campo escalar (`level`,
`health_band`, ...) no hay caso de "clave ausente" porque todo actor
siempre tiene alguno de esos campos; solo hay conocido vs. `UNKNOWN`
(o `None` para `level`, el único campo genuinamente numérico — ver más
abajo por qué no comparte el patrón de enum).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

MIN_LEVEL = 1
MAX_LEVEL = 18


class HealthBand(str, Enum):
    """Banda de vida cualitativa de un actor (diseño §B.2).

    Tres bandas reales alcanzan: `FULL` (a tope), `HIGH` (tomó daño, sigue
    cómodo), `LOW` (daño suficiente para cambiar el cálculo de riesgo de
    un all-in). No hay una cuarta banda "parcial": un escenario que
    necesite distinguir dos actores con daño desigual usa `HIGH` para el
    que está mejor y `LOW` para el que está peor, no un término nuevo.
    """

    UNKNOWN = "unknown"
    FULL = "full"
    HIGH = "high"
    LOW = "low"


class ResourceKind(str, Enum):
    """Qué tipo de recurso gasta un actor para lanzar habilidades."""

    UNKNOWN = "unknown"
    MANA = "mana"
    ENERGY = "energy"
    SECONDARY_BAR = "secondary_bar"
    RESOURCELESS = "resourceless"


class ResourceBand(str, Enum):
    """Cuánto de ese recurso está disponible, cualitativamente."""

    UNKNOWN = "unknown"
    FULL = "full"
    PARTIAL = "partial"
    NONE = "none"


class ReserveBand(str, Enum):
    """Nivel de un recurso *acumulado* (banked), distinto de `resource`:

    `resource` es lo que se gasta para lanzar (maná, energía, o nada);
    una reserva es cualquier acumulado que un kit pueda convertir en otra
    cosa (un escudo, una carga especial). Un actor sin ese tipo de
    mecánica no puebla ninguna entrada — no existe un `ReserveBand` "no
    aplica": la ausencia de la clave ya lo dice.
    """

    UNKNOWN = "unknown"
    NONE = "none"
    PARTIAL = "partial"
    NEAR_MAX = "near_max"


class AbilityAvailability(str, Enum):
    """Disponibilidad de una habilidad en un momento del estado.

    Describe un instante, no un cronómetro: no hay forma de derivar
    cuánto falta para que algo en `ON_COOLDOWN` vuelva a `READY` a partir
    de este solo valor (ver diseño §B.5, recuperación dentro de una
    secuencia — eso es contrato para una ronda de implementación futura,
    no algo que este tipo calcule).
    """

    UNKNOWN = "unknown"
    READY = "ready"
    ON_COOLDOWN = "on_cooldown"


class StackWindow(str, Enum):
    """Vigencia del conjunto de cargas actual de una mecánica de stacking.

    Deliberadamente sin un tercer valor "refreshed": un refresco es el
    *evento* de aplicar durante una ventana ya `ACTIVE`, no un estado
    nuevo en el que quede el conjunto — ver `StackState`.
    """

    UNKNOWN = "unknown"
    ACTIVE = "active"
    EXPIRED = "expired"


class RewardState(str, Enum):
    """Si la recompensa por cruzar el umbral de una mecánica de stacking
    está activa ahora — pregunta distinta de `StackWindow` (diseño §B.2:
    "¿el conjunto de cargas sigue vigente?" vs. "¿la recompensa por cruzar
    el umbral está activa ahora?")."""

    UNKNOWN = "unknown"
    INACTIVE = "inactive"
    ACTIVE = "active"


class RangeStatus(str, Enum):
    """Si una acción concreta está en rango de su objetivo. Vive en
    `ActionContext`, no en el actor: dos acciones del mismo actor pueden
    tener `RangeStatus` distinto al mismo tiempo."""

    UNKNOWN = "unknown"
    IN_RANGE = "in_range"
    OUT_OF_RANGE = "out_of_range"


class IsolationStatus(str, Enum):
    """Si una acción concreta impacta solo al objetivo (`ISOLATED`) o
    también a terceros (`CONTESTED`, p. ej. minions). Es una propiedad de
    la acción, no del estado de oleada — `SharedContext.wave_state` no
    determina este valor por sí solo (diseño §B.2)."""

    UNKNOWN = "unknown"
    ISOLATED = "isolated"
    CONTESTED = "contested"


class InvalidatorStatus(str, Enum):
    """Tri-estado de un invalidador dinámico para una acción concreta.

    La ausencia de declaración es `UNKNOWN`, nunca se infiere `ABSENT`
    (diseño §B.4): un escenario que quiera afirmar "no hay invalidadores"
    debe declarar `ABSENT` explícitamente para cada entrada conocida, eso
    nunca es el comportamiento por defecto de este tipo.
    """

    UNKNOWN = "unknown"
    PRESENT = "present"
    ABSENT = "absent"


class WaveStateKind(str, Enum):
    UNKNOWN = "unknown"
    ABSENT = "absent"
    PRESENT_NEUTRAL = "present_neutral"
    PUSHING = "pushing"


class PushDirection(str, Enum):
    """Hacia qué lado avanza la oleada cuando `WaveState.state` es
    `PUSHING`. Usa los mismos roles `candidate`/`enemy` que `CombatState`
    — nunca "self", que es ambiguo sin decir de qué actor (diseño §B.2)."""

    UNKNOWN = "unknown"
    CANDIDATE = "candidate"
    ENEMY = "enemy"


@dataclass(frozen=True, slots=True)
class StackState:
    """Estado de una mecánica de acumulación genérica (Hemorrhage,
    Darkness Rise, o cualquier mecánica futura con la misma forma:
    cantidad + ventana de vigencia + recompensa por umbral).

    `count=None` es "desconocido"; `count=0` es un conocido válido y
    distinto ("cero cargas, mecánica activa pero sin aplicar todavía", o
    "expiró"). Aplicación, refresco, activación de recompensa, expiración
    y reaplicación tras expirar son EVENTOS de una secuencia futura, no
    valores de este tipo — este tipo solo representa el estado resultante
    en un instante dado.
    """

    count: int | None = None
    window: StackWindow = StackWindow.UNKNOWN
    reward_state: RewardState = RewardState.UNKNOWN

    def __post_init__(self) -> None:
        if self.count is not None and self.count < 0:
            raise ValueError(f"StackState.count no puede ser negativo: {self.count!r}")
        if self.window is StackWindow.EXPIRED and self.count != 0:
            raise ValueError(
                "StackState con window=EXPIRED debe tener count=0 — un conjunto "
                "expirado no puede conservar un conteo residual "
                f"(recibido count={self.count!r}); ver diseño §B.2 (StackState)"
            )


@dataclass(frozen=True, slots=True)
class WaveState:
    """Estado de oleada cualitativo y direccional (`SharedContext`, no por
    actor). No determina por sí solo rango, aislamiento ni ganador de
    ninguna acción — eso vive en cada `ActionContext` (diseño §B.2)."""

    state: WaveStateKind = WaveStateKind.UNKNOWN
    pushing_toward: PushDirection = PushDirection.UNKNOWN


@dataclass(frozen=True, slots=True)
class ActionContext:
    """Rango, aislamiento e invalidadores de UNA acción/habilidad concreta.

    Nunca un campo global del escenario: dos acciones del mismo par de
    actores pueden estar en rango distinto y con aislamiento distinto al
    mismo tiempo (diseño §B.2/A3) — por eso este tipo se indexa por
    `action_ref` dentro de `SharedContext.action_contexts`, en vez de
    vivir como un campo suelto de `ActorState` o `CombatState`.
    """

    action_ref: str
    range_status: RangeStatus = RangeStatus.UNKNOWN
    target_isolation: IsolationStatus = IsolationStatus.UNKNOWN
    invalidators: dict[str, InvalidatorStatus] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.action_ref:
            raise ValueError("ActionContext.action_ref no puede ser una cadena vacía")


@dataclass(frozen=True, slots=True)
class ActorState:
    """Estado táctico de un actor (candidato o enemigo) en un escenario.

    Genérico por diseño: ningún campo nombra un campeón, una habilidad ni
    una mecánica concreta. `stacks`/`reserves`/`abilities_available` son
    `dict`s poblados por quien construye el escenario según el kit real
    que esté modelando — este tipo no sabe qué kit es.
    """

    level: int | None = None
    health_band: HealthBand = HealthBand.UNKNOWN
    resource_type: ResourceKind = ResourceKind.UNKNOWN
    resource_band: ResourceBand = ResourceBand.UNKNOWN
    stacks: dict[str, StackState] = field(default_factory=dict)
    reserves: dict[str, ReserveBand] = field(default_factory=dict)
    abilities_available: dict[str, AbilityAvailability] = field(default_factory=dict)
    extension: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.level is not None and not (MIN_LEVEL <= self.level <= MAX_LEVEL):
            raise ValueError(
                f"ActorState.level debe ser None (desconocido) o un entero entre "
                f"{MIN_LEVEL} y {MAX_LEVEL}; recibido {self.level!r}"
            )


@dataclass(frozen=True, slots=True)
class SharedContext:
    """Lo que no es propiedad de un solo actor: oleada y el contexto de
    cada acción concreta (diseño §B.2). Una sola copia por escenario —
    nunca duplicado dentro de cada `ActorState`."""

    wave_state: WaveState = field(default_factory=WaveState)
    action_contexts: dict[str, ActionContext] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CombatState:
    """Estado completo de un escenario: un actor candidato, un actor
    enemigo, y el contexto compartido entre ambos.

    `candidate`/`enemy` reutilizan los mismos roles que ya usa
    `ReasoningContext.candidate_abilities()/enemy_abilities()` en el
    motor existente — no `self`/`other`, que son relativos a quién lee el
    estado.
    """

    candidate: ActorState
    enemy: ActorState
    shared: SharedContext = field(default_factory=SharedContext)
