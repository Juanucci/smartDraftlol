"""Vocabulario cerrado del dominio.

Todo lo que las reglas pueden consultar vive acá como enum o constante.
Disciplina de vocabulario (hito 1.5): un miembro de `EffectType` o
`TacticalUse` solo se agrega cuando al menos una regla lo consume
realmente (verificado por tests/test_vocabulary_alive.py); no se agregan
miembros "por completitud". `Tag` queda deliberadamente vacío en este
hito — ver el comentario al final del archivo con el vocabulario
potencial documentado para campeones futuros.
"""

from __future__ import annotations

from enum import Enum


class Phase(str, Enum):
    """Fases de progresión de la partida que la V0 modela.

    FIRST_ITEM es una fase aproximada de progresión de poder, NO asume
    qué objeto compró cada campeón. Cualquier conclusión que dependiera
    de un objeto concreto debe declararse como información faltante.
    """

    EARLY_LANE = "early_lane"
    LEVEL_6 = "level_6"
    FIRST_ITEM = "first_item"
    SIDE_LANE_LATE = "side_lane_late"


ALL_PHASES: tuple[Phase, ...] = (
    Phase.EARLY_LANE,
    Phase.LEVEL_6,
    Phase.FIRST_ITEM,
    Phase.SIDE_LANE_LATE,
)


def phase_index(phase: Phase) -> int:
    return ALL_PHASES.index(phase)


def is_available_in(available_from: Phase, phase: Phase) -> bool:
    """True si algo disponible desde `available_from` ya existe en `phase`."""

    return phase_index(available_from) <= phase_index(phase)


class Axis(str, Enum):
    """Ejes semánticos graduados 0..4 (ninguno/bajo/medio/alto/extremo)."""

    ATTACK_RANGE = "attack_range"
    MOBILITY = "mobility"
    SUSTAIN = "sustain"
    BURST = "burst"
    SUSTAINED_DPS = "sustained_dps"
    CC = "cc"
    DURABILITY = "durability"
    WAVECLEAR = "waveclear"
    EARLY_PRESSURE = "early_pressure"
    SCALING = "scaling"
    ALL_IN = "all_in"
    DISENGAGE = "disengage"
    ABILITY_RELIANCE = "ability_reliance"
    EXECUTION_DEMAND = "execution_demand"


ALL_AXES: tuple[Axis, ...] = tuple(Axis)
AXIS_MIN = 0
AXIS_MAX = 4


class TradePattern(str, Enum):
    """Vocabulario para el resumen descriptivo `Champion.trade_patterns`.

    Puramente informativo para la salida humana: ninguna regla lo lee.
    Las reglas inspeccionan `tactical_uses` de las habilidades concretas
    disponibles en cada fase, no esta etiqueta agregada.
    """

    SHORT_TRADE = "short_trade"
    EXTENDED_TRADE = "extended_trade"
    POKE = "poke"
    ALL_IN_ONLY = "all_in_only"


class DamageType(str, Enum):
    PHYSICAL = "physical"
    MAGIC = "magic"
    TRUE = "true"


class ResourceType(str, Enum):
    """Recurso de lanzamiento del campeón (`Champion.casting_resource`).

    No es la mecánica de escudo/recurso especial de una habilidad puntual
    (eso vive en los `Effect` de esa habilidad, p. ej. `SHIELD_FROM_STORED`
    de Indestructible): esto es el recurso que limita lanzar habilidades
    en general.
    """

    MANA = "mana"
    ENERGY = "energy"
    RESOURCELESS = "resourceless"
    HEALTH_COST = "health_cost"
    SPECIAL_RESOURCE = "special_resource"


class Tag(str, Enum):
    """Propiedades permanentes del campeón, verdaderamente ortogonales a
    axes/effects/tactical_uses/damage_type/casting_resource.

    Deliberadamente vacío en este hito: ni Darius ni Mordekaiser necesitan
    hoy una propiedad que no sea ya expresable por esos otros campos, y
    mantener miembros "por si acaso" es exactamente el vocabulario muerto
    que este refactor corrige. Ver el bloque de vocabulario potencial más
    abajo para lo que se activará cuando un campeón futuro lo necesite.
    """


ALL_TAGS: frozenset[str] = frozenset(t.value for t in Tag)


class EffectType(str, Enum):
    """Qué hace un efecto de habilidad, a nivel estructural.

    Cada miembro tiene al menos una regla que lo consume (ver
    tests/test_vocabulary_alive.py). Un efecto que ninguna regla lee no
    pertenece acá: pertenece a `Ability.doc`.
    """

    DAMAGE = "damage"
    HEAL = "heal"
    SLOW = "slow"
    DISPLACE_ENEMY = "displace_enemy"          # mueve al RIVAL; nunca al que castea
    SELF_DASH = "self_dash"                     # reposicionamiento propio real
    BRIEF_CC = "brief_cc"
    INTERRUPT = "interrupt"
    AUTO_ATTACK_RESET = "auto_attack_reset"
    EMPOWER_NEXT_ATTACK = "empower_next_attack"
    STACK_APPLICATION = "stack_application"
    AMPLIFY_ABILITY = "amplify_ability"          # escala otra habilidad (ver `amplifies_slot`)
    # Bonus de daño de ataque que fortalece el PERFIL OFENSIVO completo
    # (ver `Effect.scope`): ataques básicos, las habilidades que escalan
    # con AD y los ratios de las demás. Reemplaza en v1.6.1 al genérico
    # `empower_self`, que no decía QUÉ empoderaba y obligaba a compararlo
    # como una magnitud opaca. Un efecto concreto se puede razonar; uno
    # genérico solo se puede sumar.
    BONUS_ATTACK_DAMAGE = "bonus_attack_damage"
    SHIELD_FROM_STORED = "shield_from_stored"      # escudo construido a partir de un recurso acumulado
    CONVERT_SHIELD_TO_HEAL = "convert_shield_to_heal"
    AURA_DAMAGE = "aura_damage"
    MOVEMENT_SPEED = "movement_speed"
    MAGIC_PENETRATION = "magic_penetration"
    ARMOR_PENETRATION = "armor_penetration"
    STAT_STEAL = "stat_steal"
    # Sin ayuda externa que perder: esta V0 modela un 1v1 puro
    # (`pure_1v1`), así que ISOLATE_DUEL nunca puntúa por sí solo
    # (ver IsolationRule). Igual de "inerte para pure_1v1" es
    # COOLDOWN_RESET: el remate de Noxian Guillotine resetea su cooldown,
    # pero en una consulta de un único enemigo ese enemigo ya murió y no
    # hay un segundo objetivo sobre el que perpetuar la amenaza. El
    # efecto permanece en el YAML (es real, y relevante para un futuro
    # análisis 5v5) pero ninguna regla lo usa para puntuar en este hito.
    ISOLATE_DUEL = "isolate_duel"
    RESTRICT_ARENA = "restrict_arena"
    COOLDOWN_RESET = "cooldown_reset"


class EffectCondition(str, Enum):
    """Bajo qué circunstancia se activa un efecto. Un `Effect` puede tener
    varias simultáneas (`Effect.conditions: frozenset[EffectCondition]`)."""

    ON_HIT = "on_hit"
    ON_OUTER_ZONE = "on_outer_zone"
    ON_INNER_ZONE = "on_inner_zone"
    TARGET_IS_CHAMPION = "target_is_champion"
    # El impacto solo alcanzó a un enemigo (no se repartió entre minions
    # u otras unidades). Deliberadamente distinto de `ISOLATE_DUEL`
    # (EffectType de Realm of Death, "sin ayuda externa/1v1 aislado"):
    # esto es sobre la oleada/unidades golpeadas por ESTE impacto, no
    # sobre la geometría del duelo. Ver ObliterateSingleTargetSubRule.
    ON_SINGLE_TARGET_HIT = "on_single_target_hit"
    ON_DELAY = "on_delay"
    ON_REACTIVATION = "on_reactivation"
    ON_TAKEDOWN = "on_takedown"


class TacticalUse(str, Enum):
    """Para qué sirve una habilidad en la práctica (no qué hace mecánicamente:
    eso ya está en `effects`). Cada miembro tiene un consumidor real (ver
    tests/test_vocabulary_alive.py).

    `DISENGAGE` queda deliberadamente fuera: ni Darius ni Mordekaiser
    tienen una herramienta real de desconexión en este hito (Apprehend
    específicamente NO lo es). Se documenta como vocabulario potencial
    más abajo.
    """

    INITIATE = "initiate"
    ANTI_KITE = "anti_kite"
    SETUP_COMBO = "setup_combo"
    POKE = "poke"
    WAVECLEAR = "waveclear"
    SUSTAIN = "sustain"
    TRADE_EXTEND = "trade_extend"


class CooldownClass(str, Enum):
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"


class Polarity(str, Enum):
    PRO = "pro"
    CONTRA = "contra"
    CONDITIONAL = "conditional"


class Support(str, Enum):
    """Cuánta CERTEZA respalda la inclinación de una entrada — un eje
    independiente de la DIRECCIÓN (`Polarity`) y del TIPO de
    incertidumbre (`ConditionKind`). v1.6.1 separa los tres conceptos que
    antes se apretaban dentro de `Polarity`:

      - hacia qué lado se inclina la interacción  -> `Polarity`
      - bajo qué condición se sostiene            -> `condition` + `ConditionKind`
      - cuánta certeza hay sobre esa inclinación  -> `Support` (esto)

    Antes, una ventaja real pero condicionada solo podía elegir entre
    afirmarse entera (PRO, con toda su magnitud) o refugiarse en
    CONDITIONAL y no mover nada. El resultado observado en el hito 1.6
    fue que casi la mitad de las entradas pesaban cero y el motor no
    producía ninguna síntesis.

      - STRUCTURAL: se sostiene siempre que ambos kits estén presentes en
        la fase (p. ej. "esta habilidad roba estadísticas mientras dura").
      - CONDITIONED: la dirección es clara, pero requiere una
        circunstancia (que el intercambio se extienda, que haya escudo
        acumulado). Inclina el score de forma amortiguada — NO se vuelve
        certeza — y su condición alimenta volatilidad.
      - AMBIGUOUS: doble filo real, sin dirección neta derivable. Aporta
        CERO al score (obliga `Polarity.CONDITIONAL`), pero se conserva
        íntegra en la explicación: que el motor no pueda inclinarse no es
        motivo para ocultar el hecho.

    El multiplicador de cada nivel vive en `config/weights.yaml`
    (`support:`), es configurable, viaja en la traza y está documentado
    como heurístico sin calibrar — no es una probabilidad.
    """

    STRUCTURAL = "structural"
    CONDITIONED = "conditioned"
    AMBIGUOUS = "ambiguous"


class Provenance(str, Enum):
    """De dónde sale un hecho: del kit modelado o de un juicio humano.

    v1.6.1. En el hito 1.6, dos ejes escritos a mano (`early_pressure` y
    `scaling`) producían el 40-64 % de todo el movimiento de score, y un
    solo punto editorial de `sustain` movía el GlobalScore 2.76 puntos —
    doce veces la diferencia total entre los dos candidatos. Eso no es
    razonamiento mecánico derivado: es una valoración manual entrando al
    número sin identificarse como tal.

      - DERIVED: se deriva de la estructura del kit (`effects`,
        `tactical_uses`, `StackingMechanic`, disponibilidad por fase).
      - EDITORIAL_PRIOR: sale de un eje 0..4 escrito a mano en el YAML.
        Se etiqueta explícitamente ante el consumidor, se pondera con un
        peso reducido (`provenance:` en config/weights.yaml) y está
        acotado por un guardrail de participación máxima en el score.

    La meta es que los priors editoriales se vayan derivando del kit a
    medida que el modelo lo permita (ver docs/backlog-v1.md), no que se
    borren: un prior identificado es honesto, un prior disfrazado de
    conclusión derivada no.
    """

    DERIVED = "derived"
    EDITORIAL_PRIOR = "editorial_prior"


class Factor(str, Enum):
    """Factores de scoring, con pesos centralizados en config/weights.yaml.

    NO existe un factor EXECUTION_DEMAND: GlobalScore mide adecuación
    mecánica teórica suponiendo ejecución competente (hito 1.6). Cuánto
    exige ejecutar el plan solo afecta PersonalScore (ver
    scoring/personal_score.py), nunca GlobalScore.
    """

    MECHANICAL_INTERACTION = "mechanical_interaction"
    LANE_PATTERN = "lane_pattern"
    RELIABILITY = "reliability"
    # Recompensa comparada de las mecánicas de acumulación (StackRaceRule).
    # Renombrado en v1.6.1: se llamaba `power_spikes`, pero NUNCA leyó
    # `Champion.spikes` — describía exclusivamente el pago de una
    # StackingMechanic. Un campeón sin acumulaciones también puede tener
    # spikes (desbloqueo, transformación, nivel, breakpoint, sinergia);
    # ese modelo genérico está documentado en docs/backlog-v1.md.
    STACKING_PAYOFF = "stacking_payoff"
    SCALING_SIDELANE = "scaling_sidelane"


ALL_FACTORS: tuple[Factor, ...] = tuple(Factor)


class ConfidenceLevel(str, Enum):
    ALTA = "alta"
    MEDIA = "media"
    BAJA = "baja"


class ConditionKind(str, Enum):
    """Clasifica una `condition` (de un `RuleEffect`/`TraceEntry`) según
    qué tipo de incertidumbre representa. Hito 1.6: antes, cualquier
    entrada CONDITIONAL inflaba por igual `required_skill` (PersonalScore)
    y la "densidad de condiciones" de Confidence, mezclando cosas muy
    distintas (que el jugador falle un combo vs. que no sepamos qué
    objeto tiene vs. que el resultado dependa de una decisión táctica).

      - EXECUTION: depende de la habilidad del jugador para ejecutar
        algo (acertar, esquivar, reaccionar a tiempo). Es la ÚNICA que
        puede subir `required_skill` en PersonalScore.
      - STRATEGIC: depende de una decisión o circunstancia de la partida
        (extender vs. cortar, geometría del duelo, ventaja previa). No
        es "el jugador ejecuta peor": alimenta volatilidad/condicionalidad,
        no confianza epistémica ni PersonalScore.
      - KNOWLEDGE_GAP: el motor no tiene el dato (objeto concreto, timing
        real). Reduce confianza epistémica; no es dificultad de ejecución
        ni un rasgo del matchup.
    """

    EXECUTION = "execution"
    STRATEGIC = "strategic"
    KNOWLEDGE_GAP = "knowledge_gap"


# ---------------------------------------------------------------------------
# Vocabulario potencial (NO activo en este hito)
# ---------------------------------------------------------------------------
# Documentado por pedido explícito: podar sin descartar. Se activa un
# término de esta lista moviéndolo a un enum de arriba únicamente cuando
# las tres condiciones se cumplan a la vez:
#   1. Un campeón nuevo posee realmente esa propiedad.
#   2. Existe una regla que la consume.
#   3. Existe un test que demuestra el comportamiento.
#
# Candidatos a `Tag` (propiedades permanentes):
#   - percent_health_damage: daño que escala con la vida (máxima o actual)
#     del objetivo en vez de con stats propias.
#   - attack_speed_slow: fuente de reducción de velocidad de ataque como
#     rasgo central del kit (no un slow de movimiento puntual).
#   - dash_dependent: el plan del campeón depende de un dash con cooldown
#     largo, más allá de si ese dash es SELF_DASH ofensivo o defensivo.
#   - ranged_poke: identidad de poke a distancia dominante (a diferencia
#     de un poke ocasional de un kit principalmente de trade extendido,
#     como el Q de Mordekaiser en este hito).
#   - short_trader: identidad de trade corto/hit-and-run como patrón
#     dominante (ninguno de Darius/Mordekaiser lo es).
#
# Conceptos DESCARTADOS (no vocabulario potencial: no vuelven salvo que
# aparezca un dato real que los justifique):
#   - trade_cut: existió como TacticalUse hasta v1.6.1. Se le había puesto
#     a Indestructible, y el hito 1.6 se lo quitó al comprobar que un
#     escudo no corta un intercambio por sí solo (salir depende del
#     posicionamiento y de otras acciones). Desde entonces ningún YAML lo
#     usaba y la única rama que lo leía era inalcanzable. Se elimina en
#     lugar de conservarse "por compatibilidad": un miembro de enum que
#     ningún dato ni regla legítima consume es exactamente el vocabulario
#     muerto que la disciplina del hito 1.5 prohíbe.
#
# Candidato a `TacticalUse`:
#   - disengage: una herramienta que de verdad permite desconectar un
#     intercambio (romper línea de visión, ganar distancia neta). Apprehend
#     NO calza: desplaza al rival, no crea espacio para quien la usa.
#
# Candidato a `Provenance` (documentado, NO implementado en v1.6.1):
#   - SOURCED_PRIOR: un dato traído de una fuente externa (winrate, tasa
#     de matchup, tier list), con fuente, parche, fecha, tamaño de muestra
#     y confianza del dato. Sería un tercer nivel entre DERIVED y
#     EDITORIAL_PRIOR: no lo derivó el motor, pero tampoco es la opinión
#     de quien cargó el YAML. Requiere los puertos de estadísticas del
#     backlog (#4) y un modelo de parche; agregar hoy el miembro del enum
#     sin esos puertos sería exactamente el vocabulario muerto que la
#     disciplina del hito 1.5 prohíbe. Debe quedar separado del
#     razonamiento mecánico, nunca fundido con él.
# ---------------------------------------------------------------------------
