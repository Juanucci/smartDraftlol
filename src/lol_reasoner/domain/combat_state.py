"""Estado táctico de un escenario (v1.7, Etapa 1 — endurecida).

Tipos puros para representar el `CombatState` documentado en
`docs/design/v1.7-sequence-state-design.md` §B.2/B.5/B.8: nivel exacto,
banda de vida, recurso, stacks tipados, reservas, rango y aprendizaje de
habilidades por actor, y contexto compartido (oleada + un `ActionContext`
por acción, con su propio rango/aislamiento/invalidadores).

**Alcance de esta etapa**: solo el modelo tipado, sus invariantes de
construcción y su inmutabilidad. Ningún motor de transiciones, ninguna
secuencia concreta, ningún generador de escenarios y ningún nombre de
campeón/habilidad/matchup vive acá.

**Contrato de snapshot inmutable** (diseño §B.5): un `CombatState` es una
fotografía de un instante. Un paso futuro de una secuencia consumirá un
snapshot y producirá uno NUEVO con sus postcondiciones — nunca modifica
in-place el que recibió. Los snapshots anteriores quedan intactos para
auditoría y para calcular un `StateDelta` contra ellos. Esta etapa no
implementa esa producción de snapshots nuevos (no hay motor de
transiciones todavía); lo que sí implementa es la garantía necesaria para
que sea posible: cada mapping interno se congela en la frontera de
construcción (`MappingProxyType` sobre una copia), así que ni siquiera un
error de programación puede mutar retroactivamente un snapshot ya
entregado a una traza.

**Por qué `MappingProxyType` y no otra cosa**: es de la biblioteca
estándar (`types.MappingProxyType`, sin dependencias nuevas), envuelve una
copia del mapping recibido (corta el aliasing con el `dict` externo — una
mutación posterior de ese `dict` por quien llamó al constructor no afecta
al snapshot ya construido) y bloquea asignación/borrado de ítems a través
del propio objeto de dominio. **No se afirma que sea hashable** — delega
en el mapping que envuelve (un `dict`), que tampoco lo es. Los tipos de
este módulo que contienen (directa o transitivamente) un mapping declaran
`__hash__ = None` explícitamente en vez de dejar que `hash()` falle tarde
y en silencio en tiempo de ejecución.

**Vocabulario nuevo, deliberadamente separado de `domain.enums`**: los
enums de este módulo describen el estado *dinámico* de un escenario
hipotético, no el kit *estático* de un campeón (eso ya lo cubre
`domain.enums`/`domain.champion`). Mezclarlos confundiría "qué puede hacer
este campeón" con "qué está pasando ahora mismo en este escenario".

**Regla de las tres/cuatro lecturas**, aplicada en todo este módulo
(diseño §B.2): para un campo `Mapping[id, valor]` (`stacks`, `reserves`,
`abilities`, `invalidators`): clave ausente = la mecánica no existe para
este actor/acción; clave presente con el miembro `UNKNOWN` del enum
correspondiente = existe, pero no se declaró su estado en este escenario;
clave presente con cualquier otro miembro = estado conocido, incluido el
extremo "vacío" (p. ej. `ReserveBand.NONE`), que es un conocido distinto
de `UNKNOWN`. Para un campo escalar (`level`, `health_band`, ...) no hay
caso de "clave ausente"; solo conocido vs. `UNKNOWN` (o `None` para
`level`, el único campo genuinamente numérico).

**Validación real, no solo anotaciones**: las anotaciones de tipo de
Python no validan nada en runtime. Cada campo que declara un enum o un
`int` se valida explícitamente en `__post_init__` — un `str` crudo en un
campo de enum, o un `bool`/`float`/`str` en un campo numérico, se
rechazan con `TypeError`, no se aceptan silenciosamente porque "parecen"
compatibles.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType

MIN_LEVEL = 1
MAX_LEVEL = 18


# ---------------------------------------------------------------------------
# Validación explícita (no delegada al type checker)
# ---------------------------------------------------------------------------


def _is_strict_int(value: object) -> bool:
    """True solo para `int` reales — `bool` es subclase de `int` en Python
    pero no debe colarse donde se pide un entero de dominio."""

    return isinstance(value, int) and not isinstance(value, bool)


def _require_optional_nonnegative_int(value: object, *, field_name: str) -> None:
    if value is None:
        return
    if not _is_strict_int(value):
        raise TypeError(
            f"{field_name} debe ser None (desconocido) o un int real, no "
            f"{value!r} ({type(value).__name__})"
        )
    if value < 0:
        raise ValueError(f"{field_name} no puede ser negativo: {value!r}")


def _require_optional_int_in_range(value: object, *, field_name: str, minimum: int, maximum: int) -> None:
    if value is None:
        return
    if not _is_strict_int(value):
        raise TypeError(
            f"{field_name} debe ser None (desconocido) o un int real, no "
            f"{value!r} ({type(value).__name__})"
        )
    if not (minimum <= value <= maximum):
        raise ValueError(
            f"{field_name} debe ser None o un entero entre {minimum} y {maximum}; "
            f"recibido {value!r}"
        )


def _require_enum_member(value: object, enum_cls: type[Enum], *, field_name: str) -> None:
    """Rechaza cualquier valor que no sea una instancia real de `enum_cls`
    — en particular, un `str` crudo que coincida con el *valor* de un
    miembro (p. ej. `"expired"`) no es una instancia de un enum `(str,
    Enum)`, y por lo tanto se rechaza igual que cualquier otro tipo
    incorrecto."""

    if not isinstance(value, enum_cls):
        raise TypeError(
            f"{field_name} debe ser un miembro de {enum_cls.__name__}, no "
            f"{value!r} ({type(value).__name__}) — un string crudo no puede "
            "evadir las invariantes del tipo de dominio"
        )


def _freeze_mapping(
    source: object,
    *,
    field_name: str,
    value_type: type,
) -> MappingProxyType:
    """Copia defensiva de `source` (corta aliasing con el `dict` externo),
    valida que cada valor sea una instancia real de `value_type`, y
    devuelve el resultado envuelto en `MappingProxyType` (bloquea
    mutaciones futuras a través del objeto de dominio)."""

    if not isinstance(source, Mapping):
        raise TypeError(f"{field_name} debe ser un mapping, no {type(source).__name__}")
    for key, value in source.items():
        if not isinstance(value, value_type):
            raise TypeError(
                f"{field_name}[{key!r}] debe ser una instancia de "
                f"{value_type.__name__}, no {value!r} ({type(value).__name__})"
            )
    return MappingProxyType(dict(source))


# ---------------------------------------------------------------------------
# Vocabulario cualitativo de estado (todos con UNKNOWN explícito)
# ---------------------------------------------------------------------------


class HealthBand(str, Enum):
    """Banda de vida cualitativa de un actor.

    Tres bandas reales alcanzan: `FULL` (a tope), `HIGH` (tomó daño, sigue
    cómodo), `LOW` (daño suficiente para cambiar el cálculo de riesgo de
    un all-in). No hay una cuarta banda "parcial": un escenario que
    necesite distinguir dos actores con daño desigual usa `HIGH` para el
    que está mejor y `LOW` para el que está peor.
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
    mecánica no puebla ninguna entrada — la ausencia de la clave ya lo
    dice, no existe un `ReserveBand` "no aplica".
    """

    UNKNOWN = "unknown"
    NONE = "none"
    PARTIAL = "partial"
    NEAR_MAX = "near_max"


class AbilityAvailability(str, Enum):
    """Disponibilidad de una habilidad en un momento del estado.

    Describe un instante, no un cronómetro: no hay forma de derivar
    cuánto falta para que algo en `ON_COOLDOWN` vuelva a `READY` a partir
    de este solo valor. `UNLEARNED` es un estado conocido específico —
    "todavía no se invirtió un punto acá" — no un sinónimo de `UNKNOWN"
    (ver invariantes de `AbilityState`).
    """

    UNKNOWN = "unknown"
    READY = "ready"
    ON_COOLDOWN = "on_cooldown"
    UNLEARNED = "unlearned"


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
    está activa ahora — pregunta distinta de `StackWindow` ("¿el conjunto
    de cargas sigue vigente?" vs. "¿la recompensa está activa ahora?").
    Esta etapa no impone ninguna relación obligatoria entre ambas: una
    recompensa podría, en algún kit futuro, tener una persistencia propia
    distinta de la del conjunto que la activó — esa relación, si existe,
    debe salir de un hecho mecánico concreto, no de una regla genérica
    impuesta acá.
    """

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
    determina este valor por sí solo."""

    UNKNOWN = "unknown"
    ISOLATED = "isolated"
    CONTESTED = "contested"


class InvalidatorStatus(str, Enum):
    """Tri-estado de un invalidador dinámico para una acción concreta.

    La ausencia de declaración es `UNKNOWN`, nunca se infiere `ABSENT`: un
    escenario que quiera afirmar "no hay invalidadores" debe declarar
    `ABSENT` explícitamente para cada entrada conocida.
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
    — nunca "self", que es ambiguo sin decir de qué actor."""

    UNKNOWN = "unknown"
    CANDIDATE = "candidate"
    ENEMY = "enemy"


# ---------------------------------------------------------------------------
# Tipos de valor (hashables, sin mappings internos)
# ---------------------------------------------------------------------------


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
    en un instante dado. Sin mappings internos: es hashable.
    """

    count: int | None = None
    window: StackWindow = StackWindow.UNKNOWN
    reward_state: RewardState = RewardState.UNKNOWN

    def __post_init__(self) -> None:
        _require_optional_nonnegative_int(self.count, field_name="StackState.count")
        _require_enum_member(self.window, StackWindow, field_name="StackState.window")
        _require_enum_member(self.reward_state, RewardState, field_name="StackState.reward_state")
        if self.window is StackWindow.EXPIRED and self.count != 0:
            raise ValueError(
                "StackState con window=EXPIRED debe tener count=0 — un conjunto "
                "expirado no puede conservar un conteo residual ni quedar "
                f"desconocido (recibido count={self.count!r})"
            )


@dataclass(frozen=True, slots=True)
class WaveState:
    """Estado de oleada cualitativo y direccional (`SharedContext`, no por
    actor). No determina por sí solo rango, aislamiento ni ganador de
    ninguna acción — eso vive en cada `ActionContext`.

    Invariantes: `PUSHING` exige una dirección concreta
    (`CANDIDATE`/`ENEMY`); cualquier otro estado (`UNKNOWN`, `ABSENT`,
    `PRESENT_NEUTRAL`) exige `pushing_toward = UNKNOWN` — no tiene sentido
    declarar una dirección cuando no hay empuje que dirigir. Sin mappings
    internos: es hashable.
    """

    state: WaveStateKind = WaveStateKind.UNKNOWN
    pushing_toward: PushDirection = PushDirection.UNKNOWN

    def __post_init__(self) -> None:
        _require_enum_member(self.state, WaveStateKind, field_name="WaveState.state")
        _require_enum_member(self.pushing_toward, PushDirection, field_name="WaveState.pushing_toward")
        if self.state is WaveStateKind.PUSHING:
            if self.pushing_toward not in (PushDirection.CANDIDATE, PushDirection.ENEMY):
                raise ValueError(
                    "WaveState.state == PUSHING exige pushing_toward CANDIDATE o "
                    f"ENEMY; recibido {self.pushing_toward!r}"
                )
        elif self.pushing_toward is not PushDirection.UNKNOWN:
            raise ValueError(
                f"WaveState.state == {self.state.value!r} no admite una dirección "
                f"concreta — pushing_toward debe ser UNKNOWN, no {self.pushing_toward!r}"
            )


@dataclass(frozen=True, slots=True)
class AbilityState:
    """Rango de habilidad + disponibilidad, como un único tipo — dos
    mappings paralelos (`abilities_available`/`ability_ranks`) podrían
    tener claves distintas o contradecirse; este tipo lo hace imposible
    de construir por separado.

    Semántica: `rank=None` es rango desconocido; `rank=0` es "conocida
    pero todavía no aprendida"; `rank>=1` es rango conocido y aprendido.
    `availability=UNKNOWN` es disponibilidad no observada.

    El nivel del CAMPEÓN (`ActorState.level`) y el rango de ESTA habilidad
    son datos distintos y no se derivan uno del otro acá: cuántos puntos
    puede tener invertidos una habilidad a determinado nivel de campeón es
    conocimiento estático del kit (estará en el futuro constructor de
    escenarios y su conocimiento estático), no una regla de este
    dataclass genérico. Tampoco se impone un rango máximo universal (3, 5,
    ...): existen kits con progresiones excepcionales: el máximo válido
    para una habilidad concreta es, otra vez, metadato estático futuro,
    no algo que este tipo pueda saber de antemano. El rango exacto está
    pensado para que una ronda futura resuelva valores mecánicos POR
    RANGO (daño, curación, cooldown...) — esos valores en sí pertenecen al
    conocimiento estático del kit, nunca se duplican dentro de
    `CombatState`.

    Sin mappings internos: es hashable.
    """

    rank: int | None = None
    availability: AbilityAvailability = AbilityAvailability.UNKNOWN

    def __post_init__(self) -> None:
        _require_optional_nonnegative_int(self.rank, field_name="AbilityState.rank")
        _require_enum_member(self.availability, AbilityAvailability, field_name="AbilityState.availability")
        if self.rank == 0 and self.availability is not AbilityAvailability.UNLEARNED:
            raise ValueError(
                "AbilityState.rank == 0 exige availability == UNLEARNED "
                f"(recibido availability={self.availability!r})"
            )
        if self.availability is AbilityAvailability.UNLEARNED and self.rank != 0:
            raise ValueError(
                "AbilityState.availability == UNLEARNED exige rank == 0 "
                f"(recibido rank={self.rank!r})"
            )


# ---------------------------------------------------------------------------
# Tipos compuestos (contienen mappings congelados; no hashables)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ActionContext:
    """Rango, aislamiento e invalidadores de UNA acción/habilidad concreta.

    Nunca un campo global del escenario: dos acciones del mismo par de
    actores pueden estar en rango distinto y con aislamiento distinto al
    mismo tiempo — por eso este tipo se indexa por `action_ref` dentro de
    `SharedContext.action_contexts`, en vez de vivir como un campo suelto
    de `ActorState` o `CombatState`.

    `invalidators` se congela (`MappingProxyType` sobre una copia) en la
    frontera de construcción — no hashable como consecuencia (delega en
    un mapping).
    """

    action_ref: str
    range_status: RangeStatus = RangeStatus.UNKNOWN
    target_isolation: IsolationStatus = IsolationStatus.UNKNOWN
    invalidators: Mapping[str, InvalidatorStatus] = field(default_factory=dict)

    __hash__ = None  # type: ignore[assignment]  # contiene un mapping congelado, no un valor hashable

    def __post_init__(self) -> None:
        if not isinstance(self.action_ref, str) or not self.action_ref.strip():
            raise ValueError(
                "ActionContext.action_ref no puede ser vacío ni contener solo "
                f"espacios (recibido {self.action_ref!r})"
            )
        _require_enum_member(self.range_status, RangeStatus, field_name="ActionContext.range_status")
        _require_enum_member(
            self.target_isolation, IsolationStatus, field_name="ActionContext.target_isolation"
        )
        object.__setattr__(
            self,
            "invalidators",
            _freeze_mapping(
                self.invalidators, field_name="ActionContext.invalidators", value_type=InvalidatorStatus
            ),
        )


@dataclass(frozen=True, slots=True)
class ActorState:
    """Estado táctico de un actor (candidato o enemigo) en un escenario.

    Genérico por diseño: ningún campo nombra un campeón, una habilidad ni
    una mecánica concreta. `stacks`/`reserves`/`abilities`/`extension` son
    mappings poblados por quien construye el escenario según el kit real
    que esté modelando — este tipo no sabe qué kit es. Los cuatro se
    congelan (`MappingProxyType` sobre una copia) en la frontera de
    construcción — no hashable como consecuencia.
    """

    level: int | None = None
    health_band: HealthBand = HealthBand.UNKNOWN
    resource_type: ResourceKind = ResourceKind.UNKNOWN
    resource_band: ResourceBand = ResourceBand.UNKNOWN
    stacks: Mapping[str, StackState] = field(default_factory=dict)
    reserves: Mapping[str, ReserveBand] = field(default_factory=dict)
    abilities: Mapping[str, AbilityState] = field(default_factory=dict)
    extension: Mapping[str, str] = field(default_factory=dict)

    __hash__ = None  # type: ignore[assignment]  # contiene mappings congelados, no valores hashables

    def __post_init__(self) -> None:
        _require_optional_int_in_range(
            self.level, field_name="ActorState.level", minimum=MIN_LEVEL, maximum=MAX_LEVEL
        )
        _require_enum_member(self.health_band, HealthBand, field_name="ActorState.health_band")
        _require_enum_member(self.resource_type, ResourceKind, field_name="ActorState.resource_type")
        _require_enum_member(self.resource_band, ResourceBand, field_name="ActorState.resource_band")
        if self.resource_type is ResourceKind.RESOURCELESS and self.resource_band in (
            ResourceBand.FULL,
            ResourceBand.PARTIAL,
        ):
            raise ValueError(
                "ActorState.resource_type == RESOURCELESS es incompatible con "
                f"resource_band {self.resource_band!r} (FULL/PARTIAL implican un "
                "recurso que gastar, que RESOURCELESS niega por definición) — "
                "UNKNOWN y NONE siguen siendo válidos"
            )
        object.__setattr__(
            self, "stacks", _freeze_mapping(self.stacks, field_name="ActorState.stacks", value_type=StackState)
        )
        object.__setattr__(
            self,
            "reserves",
            _freeze_mapping(self.reserves, field_name="ActorState.reserves", value_type=ReserveBand),
        )
        object.__setattr__(
            self,
            "abilities",
            _freeze_mapping(self.abilities, field_name="ActorState.abilities", value_type=AbilityState),
        )
        object.__setattr__(
            self, "extension", _freeze_mapping(self.extension, field_name="ActorState.extension", value_type=str)
        )


@dataclass(frozen=True, slots=True)
class SharedContext:
    """Lo que no es propiedad de un solo actor: oleada y el contexto de
    cada acción concreta. Una sola copia por escenario — nunca duplicado
    dentro de cada `ActorState`.

    `action_contexts` se congela igual que los mappings de `ActorState`,
    con una validación adicional: la clave debe coincidir EXACTAMENTE con
    `ActionContext.action_ref` del valor — sin normalizar ni recortar
    espacios para "hacer coincidir" dos referencias distintas.
    """

    wave_state: WaveState = field(default_factory=WaveState)
    action_contexts: Mapping[str, ActionContext] = field(default_factory=dict)

    __hash__ = None  # type: ignore[assignment]  # contiene un mapping congelado, no un valor hashable

    def __post_init__(self) -> None:
        if not isinstance(self.wave_state, WaveState):
            raise TypeError(
                f"SharedContext.wave_state debe ser una instancia de WaveState, no "
                f"{self.wave_state!r} ({type(self.wave_state).__name__})"
            )
        if not isinstance(self.action_contexts, Mapping):
            raise TypeError(
                f"SharedContext.action_contexts debe ser un mapping, no "
                f"{type(self.action_contexts).__name__}"
            )
        for key, value in self.action_contexts.items():
            if not isinstance(value, ActionContext):
                raise TypeError(
                    f"SharedContext.action_contexts[{key!r}] debe ser una instancia "
                    f"de ActionContext, no {value!r} ({type(value).__name__})"
                )
            if key != value.action_ref:
                raise ValueError(
                    f"SharedContext.action_contexts[{key!r}] no coincide con "
                    f"ActionContext.action_ref={value.action_ref!r} — la clave debe "
                    "ser exactamente igual al `action_ref` de su valor, sin "
                    "normalizaciones silenciosas que puedan fusionar dos "
                    "referencias distintas"
                )
        object.__setattr__(self, "action_contexts", MappingProxyType(dict(self.action_contexts)))


@dataclass(frozen=True, slots=True)
class CombatState:
    """Estado completo de un escenario: un actor candidato, un actor
    enemigo, y el contexto compartido entre ambos.

    `candidate`/`enemy` reutilizan los mismos roles que ya usa
    `ReasoningContext.candidate_abilities()/enemy_abilities()` en el
    motor existente — no `self`/`other`, que son relativos a quién lee el
    estado.

    Es un snapshot: representa un instante, no algo que un paso futuro
    vaya a mutar. Un paso de una secuencia consumirá una instancia de
    `CombatState` y producirá una instancia NUEVA con sus postcondiciones
    — nunca modifica esta. Todos los mappings que participan, directa o
    transitivamente, están congelados (`MappingProxyType`), así que ni
    siquiera un error de programación puede alterar retroactivamente un
    snapshot ya entregado a una traza.
    """

    candidate: ActorState
    enemy: ActorState
    shared: SharedContext = field(default_factory=SharedContext)

    __hash__ = None  # type: ignore[assignment]  # contiene actores con mappings congelados

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, ActorState):
            raise TypeError(
                f"CombatState.candidate debe ser una instancia de ActorState, no "
                f"{self.candidate!r} ({type(self.candidate).__name__})"
            )
        if not isinstance(self.enemy, ActorState):
            raise TypeError(
                f"CombatState.enemy debe ser una instancia de ActorState, no "
                f"{self.enemy!r} ({type(self.enemy).__name__})"
            )
        if not isinstance(self.shared, SharedContext):
            raise TypeError(
                f"CombatState.shared debe ser una instancia de SharedContext, no "
                f"{self.shared!r} ({type(self.shared).__name__})"
            )
