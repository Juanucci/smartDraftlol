"""G12 — StackRaceRule: la tensión entre dos mecánicas de acumulación
(`StackingMechanic`), sin nombrar campeones.

v1.6.1 separa explícitamente tres situaciones que el hito 1.6 mezclaba
en una comparación de umbrales y una suma de magnitudes:

  A. **Quién activa primero.** No se puede predecir con certeza: el lado
     con menos aplicaciones necesarias tiene un umbral estructuralmente
     más accesible, pero el otro puede tener aceleradores (reset de
     ataque, potenciación del próximo golpe) y herramientas para
     conservar contacto (slow). Sin cadencia real, cooldowns, aciertos ni
     secuencia, esto es un orden estructural, no una predicción. Aporta
     CERO al score (`AMBIGUOUS`).

  B. **Uno activa primero y el intercambio se corta.** Que un lado
     alcance su recompensa antes no garantiza que el otro llegue a la
     suya: si el trade termina temprano, el de menor umbral cobró y el
     otro no. Inclinación pequeña y `CONDITIONED` hacia el de umbral más
     bajo, atenuada explícitamente si el otro lado tiene aceleradores
     para acortar la distancia.

  C. **Ambos completan.** Activar una mecánica NO elimina las cargas del
     rival, NO bloquea sus aplicaciones futuras y NO le impide alcanzar
     después su propia recompensa. Si el intercambio se extiende lo
     suficiente para que ambos completen, se compara el PAGO de cada
     recompensa.

Cómo se compara el pago (y cómo NO). El hito 1.6 sumaba magnitudes
ordinales de tipos heterogéneos y publicaba "magnitud agregada 9 vs 4".
Dos de los tres sumandos de ese 9 eran la MISMA relación causal
(las cargas potencian la definitiva) declarada dos veces. v1.6.1 elimina
esa suma: construye un `RewardProfile` con hechos estructurales del KB
—qué efectos concretos trae la recompensa, qué slots amplifica que estén
DISPONIBLES en la fase, y qué slots escalan con el conteo de la
mecánica— y compara por DOMINANCIA PARCIAL. Si un perfil cubre
estrictamente al otro, se inclina; si las recompensas son distintas pero
ninguna domina, el resultado es `AMBIGUOUS`. No hay jerarquía de "tipos
de recompensa buenos y malos": solo se pregunta si un lado puede hacer
todo lo que el otro hace, y algo más.

Toda conclusión de esta regla pertenece al factor `stacking_payoff` y
solo a él: es el saldo del subproblema de acumulación, nunca el ganador
del duelo completo.
"""

from __future__ import annotations

from dataclasses import dataclass

from lol_reasoner.domain.champion import Ability, Champion, StackingMechanic
from lol_reasoner.domain.enums import (
    ConditionKind,
    EffectType,
    Factor,
    Phase,
    Polarity,
    Support,
    is_available_in,
)
from lol_reasoner.reasoning.context import ReasoningContext
from lol_reasoner.reasoning.rules.base import Rule, RuleEffect
from lol_reasoner.reasoning.trace import FactRef

_ACCELERATOR_TYPES = frozenset({EffectType.AUTO_ATTACK_RESET, EffectType.EMPOWER_NEXT_ATTACK})

# Cómo se lee cada acelerador en el texto. Mapa de redacción, no de valor:
# se usa para nombrar los efectos que de verdad se encontraron.
_ACCELERATOR_PHRASES = {
    EffectType.AUTO_ATTACK_RESET: "el reset del ataque",
    EffectType.EMPOWER_NEXT_ATTACK: "la potenciación del próximo golpe",
}

# Capacidades estructurales de una recompensa de acumulación. No es una
# jerarquía de valor entre tipos de efecto: son dos preguntas de sí/no
# sobre relaciones que el KB ya declara, y la comparación solo mira si un
# perfil cubre al otro.
# Capacidades estructurales de una recompensa de acumulación, derivadas de
# efectos y relaciones que el KB ya declara. NO son una jerarquía de valor
# entre tipos de efecto: se derivan para AMBOS lados con el mismo criterio,
# y una recompensa centrada en daño persistente y movilidad tiene las suyas
# igual que una centrada en empoderamiento ofensivo.
_CAP_EMPOWERS_OFFENSIVE_PROFILE = "empowers_offensive_profile"
_CAP_PERSISTENT_DAMAGE = "persistent_damage"
_CAP_SUSTAINS_CONTACT = "sustains_contact"
_CAP_AMPLIFIES_AVAILABLE = "amplifies_available_ability"
_CAP_SCALES_WITH_STACKS = "scales_with_stack_count"
# La única relación con la que esta V0 se anima a inclinar el subproblema
# (ver `_full_payoff`): que la recompensa empodere una habilidad que YA
# escalaba con el conteo de la MISMA mecánica. No es "mi tipo de efecto es
# mejor que el tuyo": es una cadena causal concreta que compone consigo
# misma, verificable en el KB, y que cualquiera de los dos lados puede
# tener.
_CAP_COMPOUNDS_WITH_ACCUMULATION = "compounds_with_accumulation"

# Qué capacidad aporta cada tipo de efecto de recompensa. Es un mapa de
# lectura (qué significa estructuralmente cada efecto), no un ranking:
# ningún valor de este dict se compara con otro.
_EFFECT_CAPABILITY = {
    EffectType.AURA_DAMAGE: _CAP_PERSISTENT_DAMAGE,
    EffectType.MOVEMENT_SPEED: _CAP_SUSTAINS_CONTACT,
}
_OFFENSIVE_PROFILE_SCOPE = "offensive_profile"

# Efectos que pueden aparecer en la cadena de una acumulación pero que NO
# otorgan ninguna capacidad en una consulta `pure_1v1`, y por lo tanto no
# participan de la comparación de recompensas. Se declaran explícitamente
# para que la exclusión quede citada en el código y no sea un olvido:
#   - COOLDOWN_RESET: un remate que resetea su propio cooldown perpetúa la
#     amenaza cuando hay más objetivos; en un duelo contra un único
#     enemigo, ese enemigo ya murió y no hay sobre quién perpetuarla.
_CAPABILITY_IRRELEVANT_IN_PURE_1V1 = frozenset({EffectType.COOLDOWN_RESET})


def _fact(champion_id: str, ability_slot: str, effect_type: EffectType, value: object) -> FactRef:
    """Convención uniforme con general.py: cita habilidad + tipo de efecto."""

    return FactRef(f"{champion_id}.abilities.{ability_slot}.effects.{effect_type.value}", value)


def _abilities_in_phase(champion: Champion, phase: Phase) -> tuple[Ability, ...]:
    return tuple(a for a in champion.abilities if is_available_in(a.available_from, phase))


def accelerator_abilities(champion: Champion, mechanic: StackingMechanic, phase: Phase) -> tuple[Ability, ...]:
    """Habilidades YA DISPONIBLES en `phase` que aceleran la llegada al
    próximo golpe que aplica una carga (auto-reset o potenciación del
    próximo ataque). Se deriva escaneando efectos, no se declara a mano
    en el YAML — así una habilidad como un reset de ataque no puede
    "duplicar" una carga: solo adelanta cuándo llega el próximo golpe que
    ya está contado en `applied_by`."""

    if "basic_attack" not in mechanic.applied_by:
        return ()
    return tuple(a for a in _abilities_in_phase(champion, phase) if a.effect_types() & _ACCELERATOR_TYPES)


def contact_abilities(champion: Champion, phase: Phase) -> tuple[Ability, ...]:
    """Habilidades disponibles que ayudan a CONSERVAR contacto (slow).
    Separado de los aceleradores porque responde otra pregunta: no
    adelantan la próxima aplicación, ayudan a que siga habiendo
    aplicaciones posteriores."""

    return tuple(a for a in _abilities_in_phase(champion, phase) if a.effects_of(EffectType.SLOW))


def applications_needed(mechanic: StackingMechanic) -> int:
    return mechanic.applications_needed


def ramp_speed_rank(champion: Champion, mechanic: StackingMechanic, phase: Phase) -> int:
    """Ordinal cualitativo de "qué tan accesible es el umbral" — NUNCA una
    tasa real ni una estimación de segundos ni una predicción de quién
    activa primero. Solo sirve para comparar dos mecánicas entre sí:
    más fuentes + más aceleradores YA DISPONIBLES en `phase` + menos
    aplicaciones necesarias => rank más alto => umbral estructuralmente
    más accesible.

    v1.6.1: este ordinal ahora se CITA en la traza (premisas y texto de
    la situación A). Antes se calculaba solo como guarda de early-return,
    así que el aporte de los aceleradores no era observable en ningún
    lado — la misma clase de cálculo muerto que el hito 1.5 eliminó de
    los campos del YAML.
    """

    sources = len(mechanic.applied_by)
    accelerators = len(accelerator_abilities(champion, mechanic, phase))
    return sources + accelerators - applications_needed(mechanic)


@dataclass(frozen=True, slots=True)
class RewardProfile:
    """Qué hace la recompensa de una mecánica, en hechos estructurales del
    KB — no en un número agregado.

    `effect_types` alimenta el texto (nombra los efectos concretos de cada
    recompensa, para poder describir a cada una en sus propios términos) y
    también las capacidades, vía `_EFFECT_CAPABILITY`. La comparación NO
    ordena tipos de efecto entre sí: ver `dominates`.
    """

    mechanic_id: str
    reward_name: str
    effect_types: frozenset[EffectType]
    amplified_available_slots: frozenset[str]
    stack_scaling_slots: frozenset[str]
    empowers_offensive_profile: bool

    @property
    def capabilities(self) -> frozenset[str]:
        caps: set[str] = set()
        for effect_type in self.effect_types:
            capability = _EFFECT_CAPABILITY.get(effect_type)
            if capability:
                caps.add(capability)
        if self.empowers_offensive_profile:
            caps.add(_CAP_EMPOWERS_OFFENSIVE_PROFILE)
        if self.amplified_available_slots:
            caps.add(_CAP_AMPLIFIES_AVAILABLE)
        if self.stack_scaling_slots:
            caps.add(_CAP_SCALES_WITH_STACKS)
        if self.compounds_with_accumulation:
            caps.add(_CAP_COMPOUNDS_WITH_ACCUMULATION)
        return frozenset(caps)

    @property
    def compounds_with_accumulation(self) -> bool:
        """La recompensa empodera una habilidad que YA escalaba con el
        conteo de esta misma mecánica: el pago compone con lo que la
        acumulación venía haciendo, en vez de agotarse en sí mismo.

        Se cumple de dos formas, ambas derivadas del KB: porque la
        recompensa amplifica explícitamente ese slot, o porque empodera el
        perfil ofensivo completo (y por lo tanto también a esa habilidad).
        """

        if not self.stack_scaling_slots:
            return False
        if self.empowers_offensive_profile:
            return True
        return bool(self.amplified_available_slots & self.stack_scaling_slots)

    def dominates(self, other: RewardProfile) -> bool:
        """Dominancia PARCIAL sobre capacidades derivadas con el MISMO
        criterio para los dos lados: hace todo lo que el otro hace, y algo
        más. Si ninguno domina, no se desempata."""

        return self.capabilities > other.capabilities


def reward_profile(champion: Champion, mechanic: StackingMechanic, phase: Phase) -> RewardProfile:
    """Construye el perfil SOLO desde efectos y relaciones ya presentes en
    el KB (`reward_effects`, `amplifies_slot`, `stack_scaling`,
    `available_from`). Nada escrito para este matchup en particular."""

    available_slots = {a.slot for a in _abilities_in_phase(champion, phase)}

    # `_CAPABILITY_IRRELEVANT_IN_PURE_1V1` (COOLDOWN_RESET) queda fuera de
    # las capacidades a propósito: ver su comentario arriba.
    relevant_reward_effects = [
        e for e in mechanic.reward_effects if e.type not in _CAPABILITY_IRRELEVANT_IN_PURE_1V1
    ]

    amplified = {
        effect.amplifies_slot
        for effect in relevant_reward_effects
        if effect.type == EffectType.AMPLIFY_ABILITY
        and effect.amplifies_slot is not None
        and effect.amplifies_slot in available_slots
    }
    scaling = {
        ability.slot
        for ability in _abilities_in_phase(champion, phase)
        for effect in ability.effects
        if effect.stack_scaling == mechanic.id and effect.type not in _CAPABILITY_IRRELEVANT_IN_PURE_1V1
    }
    empowers_offensive_profile = any(
        e.scope == _OFFENSIVE_PROFILE_SCOPE for e in relevant_reward_effects
    )
    return RewardProfile(
        mechanic_id=mechanic.id,
        reward_name=mechanic.reward_name,
        effect_types=frozenset(e.type for e in relevant_reward_effects),
        amplified_available_slots=frozenset(amplified),
        stack_scaling_slots=frozenset(scaling),
        empowers_offensive_profile=empowers_offensive_profile,
    )


class StackRaceRule(Rule):
    """Las tres situaciones de una carrera de acumulaciones (ver docstring
    del módulo): quién activa primero, qué pasa si el intercambio se
    corta, y qué pasa si ambos completan."""

    id = "G12"
    summary = "Separa quién tiene el umbral más accesible, qué pasa si el intercambio se corta antes y qué recompensa pesa más si ambos lados completan su acumulación."
    categories = frozenset({"stack_race_activation", "stack_race_short_trade", "stack_race_payoff"})
    category = "stack_race_activation"

    def evaluate(self, ctx: ReasoningContext) -> list[RuleEffect]:
        if not ctx.candidate.stacking_mechanics or not ctx.enemy.stacking_mechanics:
            return []
        cand = ctx.candidate.stacking_mechanics[0]
        enemy = ctx.enemy.stacking_mechanics[0]
        return [
            *self._first_activation(ctx, cand, enemy),
            *self._short_trade(ctx, cand, enemy),
            *self._full_payoff(ctx, cand, enemy),
        ]

    # ------------------------------------------------------------------ A
    @staticmethod
    def _tempo_clause(owner, mechanic, accelerators, contacts, premises: list[FactRef]) -> str:
        """Cita los efectos REALMENTE encontrados (no un tipo fijo por
        posición). El reset adelanta la próxima aplicación; el slow ayuda
        a conservar contacto para las posteriores. Es una sola cadena
        causal: nunca genera un delta aparte."""

        clauses: list[str] = []
        if accelerators:
            ability = accelerators[0]
            matched = sorted(ability.effect_types() & _ACCELERATOR_TYPES, key=lambda t: t.value)
            for t in matched:
                premises.append(_fact(owner.id, ability.slot, t, "accelerator"))
            # El texto nombra los aceleradores REALMENTE encontrados. Si se
            # fijara la frase ("mediante el reset del ataque"), seguiría
            # afirmando un reset aunque el KB dejara de declararlo: la
            # narración tiene que moverse con los hechos, no describir un
            # kit de memoria.
            how = " y ".join(_ACCELERATOR_PHRASES[t] for t in matched)
            clauses.append(
                f"{ability.name} de {owner.name} adelanta la siguiente aplicación válida hacia {mechanic.name} "
                f"mediante {how}"
            )
            if ability.effects_of(EffectType.SLOW):
                premises.append(_fact(owner.id, ability.slot, EffectType.SLOW, "contact"))
                clauses.append(
                    f"su ralentización ayuda a {owner.name} a conservar contacto para intentar completar las "
                    "cargas posteriores"
                )
                return " " + ", y ".join(clauses) + "."
        for ability in contacts:
            if accelerators and ability.slot == accelerators[0].slot:
                continue
            premises.append(_fact(owner.id, ability.slot, EffectType.SLOW, "contact"))
            clauses.append(
                f"{ability.name} de {owner.name} ralentiza y ayuda a conservar el contacto necesario para seguir "
                "aplicando cargas"
            )
            break
        return (" " + " ".join(clauses) + ".") if clauses else ""

    def _first_activation(self, ctx, cand, enemy) -> list[RuleEffect]:
        cand_accel = accelerator_abilities(ctx.candidate, cand, ctx.phase)
        enemy_accel = accelerator_abilities(ctx.enemy, enemy, ctx.phase)
        cand_contact = contact_abilities(ctx.candidate, ctx.phase)
        enemy_contact = contact_abilities(ctx.enemy, ctx.phase)
        cand_rank = ramp_speed_rank(ctx.candidate, cand, ctx.phase)
        enemy_rank = ramp_speed_rank(ctx.enemy, enemy, ctx.phase)

        premises = [
            FactRef(f"{ctx.candidate.id}.stacking.{cand.id}.applications_needed", cand.applications_needed),
            FactRef(f"{ctx.enemy.id}.stacking.{enemy.id}.applications_needed", enemy.applications_needed),
            FactRef(f"{ctx.candidate.id}.stacking.{cand.id}.ramp_speed_rank", cand_rank),
            FactRef(f"{ctx.enemy.id}.stacking.{enemy.id}.ramp_speed_rank", enemy_rank),
        ]
        cand_clause = self._tempo_clause(ctx.candidate, cand, cand_accel, cand_contact, premises)
        enemy_clause = self._tempo_clause(ctx.enemy, enemy, enemy_accel, enemy_contact, premises)

        if cand_rank == enemy_rank:
            ordering = (
                f"Ninguno de los dos umbrales queda estructuralmente más accesible que el otro "
                f"(ambos con rango {cand_rank})."
            )
        else:
            faster, slower = (
                (ctx.candidate, ctx.enemy) if cand_rank > enemy_rank else (ctx.enemy, ctx.candidate)
            )
            ordering = (
                f"Contando fuentes y aceleradores disponibles contra aplicaciones necesarias, el umbral de "
                f"{faster.name} queda estructuralmente más accesible que el de {slower.name}."
            )

        text = (
            f"{cand.name} de {ctx.candidate.name} requiere {cand.applications_needed} aplicaciones válidas desde "
            f"{len(cand.applied_by)} fuente(s); {enemy.name} de {ctx.enemy.name} requiere "
            f"{enemy.applications_needed} desde {len(enemy.applied_by)} fuente(s). {ordering} No puede predecirse "
            f"con certeza quién activa primero: cadencia de golpes, cooldowns, acierto y secuencia no se modelan "
            f"en esta V0.{cand_clause}{enemy_clause}"
        )
        return [
            RuleEffect(
                factor=Factor.STACKING_PAYOFF,
                polarity=Polarity.CONDITIONAL,
                delta=0.05,
                text=text,
                premises=tuple(premises),
                condition="el umbral estructuralmente más accesible no garantiza activarse primero en el tiempo real de la partida",
                invalidated_if="cadencia de golpes, cooldowns, acierto y secuencia de habilidades no se modelan en esta V0",
                condition_kind=ConditionKind.STRATEGIC,
                support=Support.AMBIGUOUS,
                category="stack_race_activation",
                causal_key="stack_race:first_activation",
            )
        ]

    # ------------------------------------------------------------------ B
    def _short_trade(self, ctx, cand, enemy) -> list[RuleEffect]:
        if cand.applications_needed == enemy.applications_needed:
            return []
        candidate_is_faster = cand.applications_needed < enemy.applications_needed
        polarity = Polarity.PRO if candidate_is_faster else Polarity.CONTRA
        lower, higher = (
            (ctx.candidate, ctx.enemy) if candidate_is_faster else (ctx.enemy, ctx.candidate)
        )
        lower_mech, higher_mech = (cand, enemy) if candidate_is_faster else (enemy, cand)

        premises = [
            FactRef(f"{lower.id}.stacking.{lower_mech.id}.applications_needed", lower_mech.applications_needed),
            FactRef(f"{higher.id}.stacking.{higher_mech.id}.applications_needed", higher_mech.applications_needed),
        ]
        higher_accel = accelerator_abilities(higher, higher_mech, ctx.phase)
        higher_contact = contact_abilities(higher, ctx.phase)
        mitigation = self._tempo_clause(higher, higher_mech, higher_accel, higher_contact, premises)
        mitigation_text = (
            f" Eso no lo decide solo:{mitigation.rstrip('.')}, lo que le da a {higher.name} margen para acortar "
            f"esa distancia dentro del mismo intercambio."
            if mitigation
            else ""
        )

        return [
            RuleEffect(
                factor=Factor.STACKING_PAYOFF,
                polarity=polarity,
                delta=0.07,
                text=(
                    f"Si el intercambio se corta temprano, {lower.name} necesita menos aplicaciones válidas "
                    f"({lower_mech.applications_needed} contra {higher_mech.applications_needed}) para haber "
                    f"cobrado {lower_mech.reward_name}, mientras que {higher.name} puede quedarse sin completar "
                    f"{higher_mech.name}.{mitigation_text}"
                ),
                premises=tuple(premises),
                condition=(
                    "solo aplica si el intercambio termina antes de que el lado de mayor umbral complete su "
                    "acumulación; en un trade que se extiende, esta ventaja se diluye"
                ),
                condition_kind=ConditionKind.STRATEGIC,
                support=Support.CONDITIONED,
                invalidated_if=(
                    "el ritmo real de intercambio (auto-ataques efectivamente conectados por segundo) no se "
                    "simula en esta V0; el orden de acumulación es cualitativo"
                ),
                category="stack_race_short_trade",
                causal_key="stack_race:short_trade",
            )
        ]

    # ------------------------------------------------------------------ C
    @staticmethod
    def _describe(profile: RewardProfile) -> str:
        """Describe una recompensa EN SUS PROPIOS TÉRMINOS. Es un mapa de
        redacción (tipo de efecto -> frase legible), no un orden de valor:
        ninguna de estas frases se compara con otra para decidir nada."""

        parts: list[str] = []
        if profile.empowers_offensive_profile:
            parts.append("un empoderamiento ofensivo general")
        if EffectType.AURA_DAMAGE in profile.effect_types:
            parts.append("daño persistente")
        if EffectType.MOVEMENT_SPEED in profile.effect_types:
            parts.append("velocidad para mantener contacto")
        if profile.amplified_available_slots:
            parts.append(f"amplificación de {', '.join(sorted(profile.amplified_available_slots))}")
        if not parts:
            parts.append("una recompensa que esta V0 no sabe caracterizar")
        return " y ".join(parts)

    def _full_payoff(self, ctx, cand, enemy) -> list[RuleEffect]:
        cand_profile = reward_profile(ctx.candidate, cand, ctx.phase)
        enemy_profile = reward_profile(ctx.enemy, enemy, ctx.phase)
        if cand_profile.effect_types == enemy_profile.effect_types and cand_profile.capabilities == enemy_profile.capabilities:
            return []

        premises = [
            FactRef(f"{ctx.candidate.id}.stacking.{cand.id}.reward_capabilities", tuple(sorted(cand_profile.capabilities))),
            FactRef(f"{ctx.enemy.id}.stacking.{enemy.id}.reward_capabilities", tuple(sorted(enemy_profile.capabilities))),
        ]
        for champion, mechanic in ((ctx.candidate, cand), (ctx.enemy, enemy)):
            for effect in mechanic.reward_effects:
                premises.append(
                    FactRef(f"{champion.id}.stacking.{mechanic.id}.reward.{effect.type.value}", effect.magnitude)
                )

        preamble = (
            f"Que {ctx.enemy.name} o {ctx.candidate.name} active su mecánica primero no elimina las cargas del "
            f"otro, no bloquea sus aplicaciones futuras ni le impide alcanzar después su propia recompensa."
        )
        both = (
            f"Si el intercambio se extiende lo suficiente para que ambos completen, {ctx.candidate.name} obtiene "
            f"{self._describe(cand_profile)} con {cand_profile.reward_name}, y {ctx.enemy.name} obtiene "
            f"{self._describe(enemy_profile)} con {enemy_profile.reward_name}: son recompensas distintas, no una "
            f"mejor y otra peor."
        )

        # La ÚNICA relación con la que esta V0 se inclina: que la recompensa
        # de un lado componga con una habilidad que ya escalaba con el
        # conteo de la misma mecánica. Comparar los conjuntos completos de
        # capacidades no alcanza —y de hecho no alcanzaría acá: cada
        # recompensa tiene capacidades que la otra no tiene, así que
        # ninguna domina—, y desempatar por "qué tipo de efecto vale más"
        # sería inventar una jerarquía.
        compounding = [
            (champion, profile)
            for champion, profile in ((ctx.candidate, cand_profile), (ctx.enemy, enemy_profile))
            if profile.compounds_with_accumulation
        ]
        if len(compounding) != 1:
            return [
                RuleEffect(
                    factor=Factor.STACKING_PAYOFF,
                    polarity=Polarity.CONDITIONAL,
                    delta=0.05,
                    text=(
                        f"{preamble} {both} Ninguna de las dos compone con su propia acumulación de una forma "
                        f"que esta V0 pueda comparar, así que el subproblema de recompensas queda sin inclinar: "
                        f"desempatarlo exigiría ordenar tipos de efecto entre sí, que es precisamente lo que "
                        f"este motor no hace."
                    ),
                    premises=tuple(premises),
                    condition="depende de que el intercambio se extienda lo suficiente para que ambos lados completen su acumulación",
                    condition_kind=ConditionKind.STRATEGIC,
                    support=Support.AMBIGUOUS,
                    category="stack_race_payoff",
                    causal_key="stack_race:full_payoff",
                )
            ]

        champion, profile = compounding[0]
        other = ctx.enemy if champion is ctx.candidate else ctx.candidate
        polarity = Polarity.PRO if champion is ctx.candidate else Polarity.CONTRA
        scaling_slots = ", ".join(sorted(profile.stack_scaling_slots))
        premises.append(
            FactRef(f"{champion.id}.stacking.{profile.mechanic_id}.compounds_with", scaling_slots)
        )

        return [
            RuleEffect(
                factor=Factor.STACKING_PAYOFF,
                polarity=polarity,
                delta=0.07,
                text=(
                    f"{preamble} {both} La diferencia que esta V0 sí puede sostener es de composición: el pago de "
                    f"{champion.name} alcanza a {scaling_slots}, una habilidad cuyo daño YA escalaba con las "
                    f"cargas de {profile.mechanic_id}, así que la recompensa se suma a lo que la acumulación "
                    f"venía construyendo; la de {other.name} no compone con su propio conteo de esa manera. Eso "
                    f"inclina el subproblema de recompensas de acumulación y nada más: quién gana el duelo sigue "
                    f"dependiendo de la vida previa, de las habilidades acertadas, del escudo, de las "
                    f"estadísticas robadas y del posicionamiento."
                ),
                premises=tuple(premises),
                condition=(
                    "solo si el intercambio se extiende lo suficiente para que AMBOS completen su acumulación, y "
                    "sin que eso implique ganar el duelo completo"
                ),
                condition_kind=ConditionKind.STRATEGIC,
                support=Support.CONDITIONED,
                category="stack_race_payoff",
                causal_key="stack_race:full_payoff",
            )
        ]


STACKING_RULES: tuple[Rule, ...] = (StackRaceRule(),)
