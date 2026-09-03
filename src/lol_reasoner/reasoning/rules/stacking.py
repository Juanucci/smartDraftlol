"""G12 — StackRaceRule: la tensión genérica entre dos mecánicas de
acumulación (`StackingMechanic`), sin nombrar campeones.

Implementa el ejemplo central del brief:

    Mordekaiser busca tres impactos para activar Darkness Rise.
    Darius busca cinco cargas para activar Noxian Might y potenciar su R.
    Mordekaiser obtiene antes su primera recompensa de trade extendido.
    Continuar peleando después de activarla acerca a Darius a su
    recompensa más peligrosa.
    ...

Nada de esto se escribe a mano por campeón: se deriva de
`StackingMechanic.applied_by`/`threshold`/`stacks_per_application` y de
qué `Effect`s tienen las habilidades involucradas. La regla nunca lee
`champion.id` ni `champion.name` para decidir — solo para el texto.

Se emiten tres `TraceEntry` separados y nunca opuestos dentro de uno
solo, por pedido explícito:
  1. quién llega antes al primer umbral (`stack_race_first`)
  2. magnitud de la recompensa si el intercambio se extiende
     (`stack_race_reward`)
  3. la condición de extender-vs-cortar el intercambio
     (`stack_race_extend_cut`)
"""

from __future__ import annotations

from lol_reasoner.domain.champion import Champion, StackingMechanic
from lol_reasoner.domain.enums import EffectType, Factor, Phase, Polarity, TacticalUse, is_available_in
from lol_reasoner.reasoning.context import ReasoningContext
from lol_reasoner.reasoning.rules.base import Rule, RuleEffect
from lol_reasoner.reasoning.trace import FactRef

_ACCELERATOR_TYPES = frozenset({EffectType.AUTO_ATTACK_RESET, EffectType.EMPOWER_NEXT_ATTACK})

# Tipos de efecto reconocidos como contribuyentes a la magnitud de una
# recompensa de umbral. Dispatch explícito (en vez de sumar cualquier
# `effect.magnitude` a ciegas) para que quede citado en código cuál
# vocabulario alimenta esta cuenta.
_REWARD_CONTRIBUTING_TYPES = frozenset({
    EffectType.EMPOWER_SELF,
    EffectType.AMPLIFY_ABILITY,
    EffectType.AURA_DAMAGE,
    EffectType.MOVEMENT_SPEED,
})


def _fact(champion_id: str, ability_slot: str, effect_type: EffectType, value: object) -> FactRef:
    """Convención uniforme con general.py: cita habilidad + tipo de efecto."""

    return FactRef(f"{champion_id}.abilities.{ability_slot}.effects.{effect_type.value}", value)


def _abilities_in_phase(champion: Champion, phase: Phase):
    return tuple(a for a in champion.abilities if is_available_in(a.available_from, phase))


def accelerator_abilities(champion: Champion, mechanic: StackingMechanic, phase: Phase):
    """Habilidades YA DISPONIBLES en `phase` que aceleran la llegada al
    próximo golpe que aplica una carga (auto-reset o potenciación del
    próximo ataque). Se deriva escaneando efectos, no se declara a mano
    en el YAML — así un W como Crippling Strike no puede "duplicar" una
    carga: solo adelanta cuándo llega el próximo golpe que ya está
    contado en `applied_by`."""

    if "basic_attack" not in mechanic.applied_by:
        return ()
    return tuple(a for a in _abilities_in_phase(champion, phase) if a.effect_types() & _ACCELERATOR_TYPES)


def applications_needed(mechanic: StackingMechanic) -> int:
    return mechanic.applications_needed


def ramp_speed_rank(champion: Champion, mechanic: StackingMechanic, phase: Phase) -> int:
    """Ordinal cualitativo de "qué tan rápido llega" — NUNCA una tasa real
    ni una estimación de segundos. Solo sirve para comparar dos mecánicas
    entre sí, nunca en abstracto: más fuentes + más aceleradores YA
    DISPONIBLES en `phase` + menos aplicaciones necesarias => rank más
    alto => llega antes."""

    sources = len(mechanic.applied_by)
    accelerators = len(accelerator_abilities(champion, mechanic, phase))
    return sources + accelerators - applications_needed(mechanic)


def cooldown_reset_abilities(champion: Champion, mechanic: StackingMechanic, phase: Phase):
    """Habilidades ya disponibles en `phase` que amplifican esta mecánica
    (`AMPLIFY_ABILITY.stack_scaling == mechanic.id`) y además resetean su
    propio cooldown al conseguir un remate (`COOLDOWN_RESET`): la
    recompensa de acumulación no es un evento único, se puede repetir
    dentro de la misma pelea mientras el objetivo siga bajo el umbral."""

    result = []
    for ability in _abilities_in_phase(champion, phase):
        amplifies_this = any(e.type == EffectType.AMPLIFY_ABILITY and e.stack_scaling == mechanic.id for e in ability.effects)
        resets = ability.effects_of(EffectType.COOLDOWN_RESET)
        if amplifies_this and resets:
            result.append(ability)
    return tuple(result)


def reward_magnitude(champion: Champion, mechanic: StackingMechanic, phase: Phase) -> int:
    """Magnitud agregada del beneficio de alcanzar el umbral, filtrada por
    fase: un efecto que amplifica un slot (`amplifies_slot`) solo cuenta
    si esa habilidad ya está disponible en `phase` (p. ej. la
    amplificación de Noxian Might sobre R no cuenta antes de level_6,
    aunque el propio umbral de 5 cargas sea alcanzable antes)."""

    total = 0
    for effect in mechanic.reward_effects:
        if effect.type not in _REWARD_CONTRIBUTING_TYPES:
            continue
        if effect.amplifies_slot is not None:
            amplified = champion.ability(effect.amplifies_slot)
            if amplified is None or not is_available_in(amplified.available_from, phase):
                continue
        total += effect.magnitude

    # Además de la recompensa declarada al umbral, una habilidad ya
    # disponible puede escalar continuamente con el conteo actual de la
    # mecánica (p. ej. el propio daño de Noxian Guillotine escala con
    # las cargas de Hemorrhage ya aplicadas, no solo al llegar a 5).
    for ability in _abilities_in_phase(champion, phase):
        for effect in ability.effects:
            if effect.type == EffectType.AMPLIFY_ABILITY and effect.stack_scaling == mechanic.id:
                total += effect.magnitude

    return total


class StackRaceRule(Rule):
    """La tensión entre dos StackingMechanic enfrentadas. Ver docstring del
    módulo para los tres TraceEntry que produce."""

    id = "G12"
    summary = "Compara umbral, fuentes, aceleradores y recompensa de las StackingMechanic de ambos lados."
    categories = frozenset({"stack_race"})
    category = "stack_race"

    def evaluate(self, ctx: ReasoningContext) -> list[RuleEffect]:
        if not ctx.candidate.stacking_mechanics or not ctx.enemy.stacking_mechanics:
            return []
        candidate_mechanic = ctx.candidate.stacking_mechanics[0]
        enemy_mechanic = ctx.enemy.stacking_mechanics[0]
        effects: list[RuleEffect] = []

        effects.extend(self._first_threshold_effect(ctx, candidate_mechanic, enemy_mechanic))
        effects.extend(self._reward_magnitude_effect(ctx, candidate_mechanic, enemy_mechanic))
        effects.extend(self._extend_or_cut_effect(ctx, candidate_mechanic, enemy_mechanic))
        return effects

    def _first_threshold_effect(self, ctx, candidate_mechanic, enemy_mechanic) -> list[RuleEffect]:
        candidate_accelerators = accelerator_abilities(ctx.candidate, candidate_mechanic, ctx.phase)
        enemy_accelerators = accelerator_abilities(ctx.enemy, enemy_mechanic, ctx.phase)
        candidate_rank = ramp_speed_rank(ctx.candidate, candidate_mechanic, ctx.phase)
        enemy_rank = ramp_speed_rank(ctx.enemy, enemy_mechanic, ctx.phase)
        if candidate_rank == enemy_rank:
            return []
        polarity = Polarity.PRO if candidate_rank > enemy_rank else Polarity.CONTRA
        who = "antes" if polarity == Polarity.PRO else "después"

        premises = [
            FactRef(f"{ctx.candidate.id}.stacking.{candidate_mechanic.id}.applications_needed", candidate_mechanic.applications_needed),
            FactRef(f"{ctx.enemy.id}.stacking.{enemy_mechanic.id}.applications_needed", enemy_mechanic.applications_needed),
        ]
        for ability in candidate_accelerators:
            premises.append(_fact(ctx.candidate.id, ability.slot, EffectType.AUTO_ATTACK_RESET, "accelerator"))
        for ability in enemy_accelerators:
            premises.append(_fact(ctx.enemy.id, ability.slot, EffectType.EMPOWER_NEXT_ATTACK, "accelerator"))

        accel_note = ""
        if candidate_accelerators:
            accel_note = f" (acelerado por {candidate_accelerators[0].name})"

        return [
            RuleEffect(
                factor=Factor.POWER_SPIKES,
                polarity=polarity,
                delta=0.12,
                text=(
                    f"{ctx.candidate.name} alcanza el umbral de {candidate_mechanic.name} "
                    f"({candidate_mechanic.applications_needed} aplicaciones válidas desde "
                    f"{len(candidate_mechanic.applied_by)} fuente(s){accel_note}) {who} que {ctx.enemy.name} el de "
                    f"{enemy_mechanic.name} ({enemy_mechanic.applications_needed} aplicaciones desde "
                    f"{len(enemy_mechanic.applied_by)} fuente(s)); esto es un orden cualitativo, no una "
                    "estimación de tiempo real."
                ),
                premises=tuple(premises),
                category="stack_race",
            )
        ]

    def _reward_magnitude_effect(self, ctx, candidate_mechanic, enemy_mechanic) -> list[RuleEffect]:
        candidate_reward = reward_magnitude(ctx.candidate, candidate_mechanic, ctx.phase)
        enemy_reward = reward_magnitude(ctx.enemy, enemy_mechanic, ctx.phase)
        if candidate_reward == enemy_reward:
            return []
        polarity = Polarity.PRO if candidate_reward > enemy_reward else Polarity.CONTRA
        premises = [
            FactRef(f"{ctx.candidate.id}.stacking.{candidate_mechanic.id}.reward_magnitude@{ctx.phase.value}", candidate_reward),
            FactRef(f"{ctx.enemy.id}.stacking.{enemy_mechanic.id}.reward_magnitude@{ctx.phase.value}", enemy_reward),
        ]
        for eff in (*candidate_mechanic.reward_effects,):
            premises.append(FactRef(f"{ctx.candidate.id}.stacking.{candidate_mechanic.id}.reward.{eff.type.value}", eff.magnitude))

        reset_note = ""
        resetting = cooldown_reset_abilities(ctx.candidate, candidate_mechanic, ctx.phase)
        if resetting:
            reset_note = (
                f" Además, {resetting[0].name} resetea su cooldown al conseguir el remate, lo que perpetúa la "
                "amenaza mientras el objetivo siga bajo el umbral, en vez de ser un evento único por pelea."
            )
            for ability in resetting:
                premises.append(_fact(ctx.candidate.id, ability.slot, EffectType.COOLDOWN_RESET, True))

        return [
            RuleEffect(
                factor=Factor.POWER_SPIKES,
                polarity=polarity,
                delta=0.1,
                text=(
                    f"Si el intercambio se extiende lo suficiente, la recompensa de {ctx.candidate.name} al "
                    f"alcanzar {candidate_mechanic.reward_name} (magnitud agregada {candidate_reward} en esta "
                    f"fase) {'supera' if polarity == Polarity.PRO else 'queda por debajo de'} la de "
                    f"{ctx.enemy.name} ({enemy_mechanic.reward_name}, magnitud {enemy_reward}).{reset_note}"
                ),
                premises=tuple(premises),
                category="stack_race",
            )
        ]

    def _extend_or_cut_effect(self, ctx, candidate_mechanic, enemy_mechanic) -> list[RuleEffect]:
        enemy_cut_tools = [
            a for a in ctx.enemy_abilities() if TacticalUse.TRADE_CUT in a.tactical_uses
        ]
        condition = (
            "extender el intercambio acerca a ambos lados a su propia recompensa de acumulación; "
            "alcanzar el umbral rival primero castiga seguir peleando en vez de cortar"
        )
        if enemy_cut_tools:
            condition += f", y {ctx.enemy.name} puede intentar cortarlo antes con {enemy_cut_tools[0].name}"
        return [
            RuleEffect(
                factor=Factor.RELIABILITY,
                polarity=Polarity.CONDITIONAL,
                delta=0.08,
                text=(
                    f"La conclusión sobre este intercambio depende de si se extiende lo suficiente para que "
                    f"{candidate_mechanic.name} o {enemy_mechanic.name} lleguen a su recompensa, no es "
                    "automática desde el primer contacto."
                ),
                premises=(),
                condition=condition,
                invalidated_if=(
                    "el ritmo real de intercambio (auto-ataques efectivamente conectados por segundo) no se "
                    "simula en esta V0; el orden de acumulación es cualitativo"
                ),
                category="stack_race",
            )
        ]


STACKING_RULES: tuple[Rule, ...] = (StackRaceRule(),)
