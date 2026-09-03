# Decisiones técnicas — V0

Documento breve de decisiones tomadas sin bloquear en el usuario, con su
justificación. Ninguna de estas decisiones es definitiva: son puntos de
partida razonables para validar la arquitectura.

Secciones 1-10: hito 1 (primera implementación, schema v1). Sección 11:
hito 1.5 (refactor del modelo de conocimiento a schema v2 — mismo par de
campeones, Darius y Mordekaiser).

## 1. Ejes semánticos 0..4, no 0..100

Un valor "73/100" en `sustain` es precisión falsa que nadie puede defender ni
auditar a mano. Con 5 niveles (ninguno/bajo/medio/alto/extremo) cada valor es
justificable en una línea de comentario del YAML, y las reglas comparan
diferencias pequeñas (≥1, ≥2) que siguen siendo legibles como "una ventaja
clara", no como ruido de redondeo.

## 2. YAML, no JSON, para la base de conocimiento

La KB se edita a mano y necesita comentarios explicando *por qué* Darius
tiene `early_pressure: 4` y no 3. JSON no admite comentarios. `pyyaml` es la
única dependencia de runtime del proyecto.

Nota práctica: `true` es una palabra reservada de YAML (se parsea como
booleano). La clave de `damage_profile.true` está entre comillas
(`"true": 0.2`) para que quede como string.

## 3. Reglas como objetos Python, no un DSL en YAML

Un DSL de reglas en YAML habría sido sobreingeniería para una V0 con 11
reglas generales. Las reglas siguen siendo inspeccionables como datos: cada
`Rule` expone `id`, `summary`, `category` y `phases` sin ejecutar código para
leerlos. Si el número de reglas creciera mucho, un DSL declarativo sería la
primera candidata a evaluar para V1.

## 4. Convención de signo en el scoring: `CONDITIONAL` no mueve el score

`PRO` = +delta, `CONTRA` = -delta, `CONDITIONAL` = 0 en el cálculo de
`GlobalScore`. Una entrada condicional (p. ej. "esto vale mientras el rival
no tenga X disponible") no debería inflar ni desinflar el número si esa
circunstancia no está confirmada — pero sigue apareciendo íntegra en
`conditions` y sigue penalizando la confianza. Esto separa "cuánto mueve el
score" de "cuánto sabemos con certeza", que son preguntas distintas.

## 5. Confianza por cobertura de categorías, no por cantidad de reglas

Requisito explícito del brief: varias reglas de la misma categoría mecánica
(p. ej. tres observaciones distintas sobre `ability_interaction`) no son
evidencia independiente. La cobertura se mide en categorías **distintas**
que dispararon (`TraceEntry.category`), sobre un denominador fijo (todas las
categorías que el registro de reglas generales conoce). Dos reglas de la
misma categoría no suman cobertura extra, así que no pueden inflar la
confianza por sí solas.

## 6. Reglas "estructurales" restringidas a una sola fase

Varias reglas (dependencia de habilidad, fragilidad de all-in, ventana de
cooldown de una habilidad defensiva) describen un hecho del kit que no
cambia fase a fase. Si se evaluaran en las 4 fases, producirían 4 entradas
`CONDITIONAL` idénticas por el mismo hecho, inflando artificialmente
`conditional_count` (y, por lo tanto, `required_skill` en el ajuste
personal) sin aportar información nueva. Por eso esas reglas específicas
restringen `phases = {EARLY_LANE}`: el hecho se registra una sola vez. Las
reglas cuyo efecto sí es distinto por fase (presión temprana vs. escalado
tardío, aislamiento del ultimate desde nivel 6) sí se evalúan en cada fase
relevante, porque ahí la repetición es información real, no ruido.

## 7. `PersonalScore` no es un promedio con `mastery`

`PersonalScore = GlobalScore + K · (mastery − required_skill) / 100`, donde
`required_skill` depende de `execution_demand` del candidato y de cuántas
entradas condicionales trae su plan (más condiciones para acertar = más
exigente de ejecutar bien). Un pick simple con mastery bajo cae poco; un pick
de ejecución alta con mastery 0 cae fuerte. `GlobalScore` no lee `mastery` en
ningún punto del código — es la garantía estructural (y el test) de que
cambiar el dominio del usuario nunca cambia el ranking global.

## 8. Excepciones específicas: por habilidad, no por campeón

`reasoning/rules/specific.py` no dice "Darius le gana a Mordekaiser": cada
entrada referencia un slot de habilidad concreto de cada lado, trae una
`justification` (por qué el cruce genérico de tags no alcanza) y una
`condition`. Un test (`test_no_hardcoded_pairs.py`) obliga a que el archivo
tenga como máximo 10 entradas y que ninguna tenga esos campos vacíos.

## 9. `FIRST_ITEM` como fase de progresión, no de objeto concreto

Cada vez que se evalúa la fase `first_item`, el motor de forma fija agrega
una entrada de información faltante (`ITEMGAP`) recordando que no se conoce
el objeto específico del candidato. Es una decisión deliberada para no
fingir precisión: preferimos declarar el hueco de información antes que
inventar un timing de objeto.

## 10. Qué es heurístico y qué no (honestidad explícita)

**Heurístico, sin calibrar:**
- Los valores de ejes/tags/spikes de Darius y Mordekaiser (lectura cualitativa
  propia).
- Todos los pesos de `config/weights.yaml` (factor, fase, ajuste personal).
- La fórmula exacta de `required_skill` y la de `confidence.score`.
- Los umbrales de las reglas (p. ej. "≥2 de diferencia en un eje").

**No heurístico, mecánico/determinista:**
- La construcción de la traza a partir de las reglas (dado un YAML y una
  consulta, el resultado es reproducible).
- La convención de signo de scoring.
- La prohibición de nombres de campeón en reglas generales (verificada por
  test, no por buena voluntad).

## 11. Hito 1.5 — refactor del modelo de conocimiento (schema v2)

El hito 1 validó la tubería (YAML → traza → score → explicación), pero el
modelo de conocimiento era demasiado limitado: `AbilityEffect.kind` era
singular (una habilidad = un efecto), `counters`/`countered_by` permitían
afirmar un resultado sin representar el mecanismo, y `available_from`,
`spikes`, `strengths`/`vulnerabilities` se cargaban sin que ninguna regla
los leyera. Dos afirmaciones concretas resultaron directamente falsas:
"el daño verdadero ignora escudos" (S01) y "Indestructible revierte
cargas de Hemorrhage" (S02).

**11.1 — `Ability` tiene N `Effect`, no un `kind`.** Cada `Effect` es
`{type, magnitude, conditions: frozenset[EffectCondition], damage_type?,
feeds_stack?, stack_scaling?, amplifies_slot?, bypasses_shields=False,
doc}`. `conditions` es un conjunto (no un solo valor) porque un efecto
puede depender de varias circunstancias a la vez (p. ej. el heal de
Decimate exige `ON_OUTER_ZONE` **y** `TARGET_IS_CHAMPION`).

**11.2 — Se elimina `counters`/`countered_by`.** Las reglas generales
ahora cruzan `EffectType`/`tactical_uses` estructuralmente (¿tiene un
escudo? ¿tiene daño verdadero? ¿interrumpe?), nunca una lista de tags
declarada a mano que ya presupone el resultado. `bypasses_shields`
existe como una vía de extensión explícita (una habilidad *futura y
concreta* podría declararlo) pero ninguna del hito 1.5 lo activa: por
defecto, cualquier escudo absorbe cualquier daño, verdadero incluido.

**11.3 — `StackingMechanic` como objeto de primera clase.** Umbral,
`stacks_per_application`, `applied_by` (fuentes) y `reward_effects`
declarados; `applications_needed` se deriva (`ceil(threshold /
stacks_per_application)`); `ramp_speed_rank` (qué tan rápido se llega,
un ordinal cualitativo, nunca una tasa) y `reward_magnitude` (filtrada
por fase vía `amplifies_slot`) se calculan en
`reasoning/rules/stacking.py`, no se escriben a mano por campeón. Una
validación cruzada en `schema.py` obliga a que todo slot listado en
`applied_by` tenga de verdad un efecto `STACK_APPLICATION` con ese
`feeds_stack`, para que ambas declaraciones no puedan desincronizarse.

**11.4 — `available_from` se cumple estructuralmente.**
`ReasoningContext.candidate_abilities()`/`enemy_abilities()` filtran por
fase; ninguna regla puede leer `champion.abilities` directo (verificado
por AST en `test_phase_availability.py`). Antes, `true_damage_source`
era un tag global de Darius legible en `early_lane` aunque proviniera de
su R (nivel 6): ahora el daño verdadero vive en el `Effect` de la R, y
solo aparece en la traza desde que esa habilidad está disponible.

**11.5 — Disciplina de vocabulario vivo.** `Tag` quedó vacío (los
candidatos `percent_health_damage`, `attack_speed_slow`,
`dash_dependent`, `ranged_poke`, `short_trader` se documentan como
vocabulario potencial en `domain/enums.py`, no como miembros de enum
inactivos). Cada `EffectType`/`TacticalUse` activo tiene un consumidor
real, verificado en `tests/test_vocabulary_alive.py` con evidencia
comportamental (aparece citado en un `FactRef` de la traza real, en
alguna de las dos direcciones) más un escaneo de referencia en código.
Tres tipos (`DISPLACE_ENEMY`, `BRIEF_CC`, `SLOW`, todos de
`DisplacementVsMobilityRule`/G15) están documentados como
"condicionalmente silenciosos para este par": la regla existe y se
ejecuta, pero ni Darius ni Mordekaiser tienen movilidad/disengage que un
desplazamiento pudiera negar — se espera que esa lista se achique con
campeones más móviles.

**11.6 — Deduplicación causal (anti-doble-conteo).** Cuando varios
`Effect` de una misma habilidad describen el mismo "momento" (p. ej.
`DISPLACE_ENEMY` + `BRIEF_CC` + `INTERRUPT` de Apprehend), la regla que
los interpreta agrega el **máximo** de sus magnitudes, no la suma, en
una única `RuleEffect` — ver `DisplacementVsMobilityRule`. Esto es
distinto de que dos *reglas diferentes* lean el mismo efecto para
afirmar cosas *distintas* (p. ej. `INTERRUPT` de Apprehend aporta tanto
a "control de espacio" en G15 como a "niega una aplicación de stack
puntual" en G04): eso no es doble conteo, son dos consecuencias reales y
no redundantes del mismo efecto.

**11.7 — Confianza: tres correcciones.** (a) La cobertura se interseca
con `registry.ALL_CATEGORIES` antes de dividir: categorías de aviso como
`missing_item_data` no cuentan como cobertura mecánica. (b)
`missing_info_count` cuenta textos `invalidated_if` **distintos**, no
entradas — la misma observación repetida en 4 fases contaba 4 veces
antes. (c) La contradicción se calcula por `(fase, factor)`, no
agregada sobre toda la traza: una ventaja de `early_lane` y una
desventaja de `side_lane_late` en el mismo factor ya no se cancelan
como si fueran simultáneas. La misma dedup por texto distinto se aplicó
a `conditional_entry_count` (usado por `required_skill` en
`PersonalScore`).

**11.8 — `specific.py` queda vacío.** S01 y S02 no eran interacciones
reales que las reglas generales no pudieran capturar: eran afirmaciones
falsas. Al modelar `Effect.damage_type` y
`SHIELD_FROM_STORED`/`CONVERT_SHIELD_TO_HEAL` estructuralmente, ambas
quedaron cubiertas — correctamente — por reglas generales
(`DamageTypeAndShieldRule`, `MitigationAndDisruptionRule`) sin necesitar
ninguna excepción. El módulo, el tope de 10 y los tests que exigen
`justification`+`condition` se conservan para cuando de verdad haga
falta una.

**11.9 — Guardrail de 15 reglas generales: temporal.** Este hito llega a
14 (13 en `general.py` + `StackRaceRule` en `stacking.py`). Es un límite
deliberadamente estrecho para esta V0 con 2 campeones; se revisa
explícitamente al incorporar los otros ocho.
