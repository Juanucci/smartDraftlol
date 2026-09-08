# Decisiones técnicas — V0

Documento breve de decisiones tomadas sin bloquear en el usuario, con su
justificación. Ninguna de estas decisiones es definitiva: son puntos de
partida razonables para validar la arquitectura.

**Las secciones 1 a 12 son historia congelada**: describen lo que se
decidió en cada hito, con el vocabulario y las reglas que existían
entonces. Varias mencionan reglas que ya no existen (`G04`,
`MitigationAndDisruptionRule`, `SpikeAlignmentRule`,
`ExecutionDemandBaselineRule`, `PokeVsSustainRule`) o afirmaciones que un
hito posterior corrigió. Para el estado ACTUAL del motor, la sección
vigente es la última (§13, v1.6.1); si una sección anterior contradice a
la última, manda la última.

Secciones 1-10: hito 1 (primera implementación, schema v1). Sección 11:
hito 1.5 (refactor del modelo de conocimiento a schema v2 — mismo par de
campeones, Darius y Mordekaiser). Sección 12: hito 1.6 (reciprocidad de
reglas generales, causal_key/deduplicación de score, separación de
confianza epistémica vs. volatilidad, y arquitectura provisional de
PersonalScore). Sección 13: **v1.6.1** (certeza y procedencia como ejes
propios, división de la regla monolítica de daño, priors editoriales
acotados, StackRace en tres situaciones, y las asimetrías que
sobrevivieron al hito anterior).

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

## 12. Hito 1.6 — reciprocidad, causal_key y confianza vs. volatilidad

**12.1 — Bug de reciprocidad real, no solo hipotético.** La revisión del
hito 1.5 detectó que `RangeAccessRule`, `EarlyPressureVsScalingRule`,
`WaveclearGatingRule` y `DisplacementVsMobilityRule` solo implementaban
la mitad de una comparación mecánica compartida: el lado favorecido
recibía PRO como candidato, pero el mismo hecho nunca se traducía en
CONTRA cuando ese lado quedaba del lado `enemy`. Que una regla "vuelva a
ejecutarse" al invertir candidato/enemigo no prueba que produzca la
amenaza correspondiente — cada mitad de la comparación necesita su
propia rama de código, y se verificó empíricamente con campeones
sintéticos (no solo auditando el código a ojo) antes de dar por
corregido cada caso. Las cuatro reglas quedaron reescritas para calcular
ambas direcciones (ver sus docstrings en `general.py`); `PokeVsSustainRule`
se confirmó como el caso legítimamente no-recíproco (dos preguntas
independientes, no un hecho compartido con dueño ambiguo).
`tests/test_reciprocity.py` es el test dedicado: para cada regla
corregida comprueba que el **mismo** `FactRef`/`causal_key` aparece con
polaridad opuesta según de qué lado quede el campeón favorecido —no se
conforma con "las dos trazas son distintas" (eso ya lo cubría
`test_rules.py`).

**12.2 — Eliminación de la inferencia falsa `INTERRUPT → niega
STACK_APPLICATION`.** `MitigationAndDisruptionRule` cruzaba, de forma
general, cualquier `INTERRUPT`/`BRIEF_CC`/`DISPLACE_ENEMY` contra
cualquier `STACK_APPLICATION` rival y afirmaba que lo negaba. Un pull o
un CC breve no cancela por definición un ataque básico, un efecto on-hit
ni una pasiva — Death's Grasp y Apprehend no interrumpen Hemorrhage ni
Darkness Rise. La regla se eliminó; los efectos reales de Death's
Grasp/Apprehend (desplazamiento, penetración, control de espacio vía
`DisplacementVsMobilityRule`) se conservan. `INTERRUPT` queda
condicionalmente silencioso para este par (documentado en
`test_vocabulary_alive.py`), no vocabulario muerto. El uso en reversa de
Death's Grasp (Mordekaiser halándose a sí mismo) no se modela — es
direccional/posicional, algo que esta base de conocimiento no
representa — y queda en `docs/backlog-v1.md` como mecánica avanzada
futura, no inferido vía `interrupt` ni generalizado como disengage.

**12.3 — Crippling Strike sin score propio, pero visible en la carrera de
stacks.** El reset de ataque y el slow de Crippling Strike (W de Darius)
no generan una `RuleEffect`/score independiente: se citan como premisas
(`AUTO_ATTACK_RESET`, `SLOW`) dentro de la misma entrada CONDITIONAL de
`StackRaceRule` que compara umbrales estructurales, en ambas
direcciones. Cuando Mordekaiser es candidato, el texto se lee
explícitamente como riesgo ("aunque Mordekaiser activa Darkness Rise con
menos impactos, el reset y la ralentización de Crippling Strike facilitan
que Darius mantenga el intercambio…") — no un delta de score aparte por
el slow, porque es la misma cadena causal.

**12.4 — `ON_ISOLATED_TARGET` → `ON_SINGLE_TARGET_HIT`.** El nombre
anterior sugería "sin campeones cerca" y se confundía con
`EffectType.ISOLATE_DUEL` (Realm of Death). El significado real de
Obliterate es "el impacto no se repartió con minions/otras unidades":
`EffectCondition.ON_SINGLE_TARGET_HIT`, con un consumidor genérico nuevo
(`DamageTypeAndShieldRule._single_target_bonus`, dentro de la regla
fusionada G03) que produce una entrada CONDITIONAL bidireccional (PRO
para Mordekaiser-candidato, riesgo para Darius-candidato), sin ventaja
numérica firme, y que relaciona — sin hardcodear campeones — la
condición con `ISOLATE_DUEL` desde `level_6` cuando ambos existen en el
mismo par.

**12.5 — Fusión G03+G04, escudo de Indestructible sin doble conteo.**
`_shield_mitigation` (absorción genérica de cualquier daño, incluido
verdadero) y `_damage_mitigation_of_sustained_plan` (el matiz de que
además mitiga un plan de intercambio sostenido y puede convertir el
remanente en curación) comparten `causal_key` sobre la misma habilidad:
es la misma capacidad de absorción con dos matices, no dos ventajas. Se
eliminó `trade_cut` de `tactical_uses` de Indestructible (no corta un
intercambio por sí sola ni genera distancia: depende de posicionamiento
y otras acciones) y se corrigió el comentario de `sustain` en el YAML
(Darkness Rise no cura ni sostiene).

**12.6 — `SpikeAlignmentRule` eliminada; `spikes`/`first_item` sin
magnitud manual.** `spikes` queda como estructura descriptiva/futura —
ninguna regla la lee, ninguna magnitud manual mueve score. Las
afirmaciones `first_item=N` del hito anterior (una ventaja de objeto sin
modelar objetos) se eliminaron sin reemplazo: `early_pressure` cubre la
tendencia temprana, `scaling` la tardía, `available_from` los
desbloqueos reales (p. ej. nivel 6). `ITEMGAP` sigue siendo el único
aviso que aparece en la fase `first_item`.

**12.7 — Denominador de cobertura de Confidence: traza espejo.** Antes,
`compute_confidence` solo veía las categorías que dispararon en la
traza del candidato — un candidato con poca evidencia (buena o mala)
inflaba artificialmente su propia cobertura. Ahora se construye también
`mirror_trace` (candidato/enemigo invertidos) exclusivamente para
determinar qué categorías eran aplicables a este matchup
(`ALL_CATEGORIES ∩ (categorías(trace) ∪ categorías(mirror_trace))`); el
contenido de `mirror_trace` nunca se expone ni se mezcla con el
resultado del candidato. Una traza vacía ahora da cobertura 0 y
confianza epistémica 0.0/BAJA — antes un piso aditivo escondía este caso
degenerado.

**12.8 — `ConditionKind` separa confianza epistémica de
volatilidad/condicionalidad.** Antes, cualquier entrada CONDITIONAL
inflaba por igual "cuánto sabemos" y "cuánto puede cambiar la
recomendación", mezclando falta de información con incertidumbre
táctica legítima. `ConditionKind.EXECUTION` (depende de que el jugador
ejecute algo) puede subir `required_skill` en PersonalScore.
`ConditionKind.STRATEGIC` (depende de una decisión/circunstancia de la
partida, no de ejecución) alimenta la volatilidad de Confidence, nunca
`required_skill`. `ConditionKind.KNOWLEDGE_GAP` (el motor no tiene el
dato, p. ej. `ITEMGAP`) reduce la confianza epistémica, no la
volatilidad. Que exista evidencia PRO y CONTRA sobre el mismo matchup ya
no se interpreta automáticamente como ignorancia: se cuenta como
contradicción `(fase, factor)`, una señal de volatilidad distinta de
"no tenemos el dato".

**12.9 — `ExecutionDemandBaselineRule` eliminada de GlobalScore;
`PlayerProfile`/`PersonalScoreBreakdown` como interfaz extensible.**
GlobalScore mide adecuación mecánica asumiendo ejecución competente —
nunca lee `execution_demand` ni ninguna variante de "cuán difícil es de
ejecutar". Esa señal vive exclusivamente en PersonalScore
(`required_skill`), junto con `execution_condition_count` (condiciones
`EXECUTION` distintas, no todas las CONDITIONAL). `PlayerProfile` hoy
solo trae `mastery`; su forma está pensada para agregar después partidas
jugadas, winrate personal con tamaño de muestra, desempeño reciente,
recencia y experiencia en el rol sin tocar la firma de
`personal_score()` — no se inventan esos datos en este hito.

**12.10 — Deltas y coeficientes: provisionales, no calibrados.** Los
deltas reducidos y los coeficientes heurísticos de este hito (incluidos
`config/weights.yaml`) se mantienen sin calibración competitiva: la
prioridad de esta V0 es polaridad correcta, trazabilidad, ausencia de
doble conteo, comportamiento contrafactual coherente y confianza
honesta — no un ranking final ajustado a datos reales. La calibración
queda en `docs/backlog-v1.md`.

**12.11 — Daño verdadero y penetración: fortalezas reales, no
sobrerrepresentadas.** Se mantienen en el YAML y en `DamageTypeAndShieldRule`
sin duplicarse entre fases (mismo `causal_key` por habilidad+efecto) ni
con la interacción de escudo (el daño verdadero es real, pero un escudo
común puede absorber cualquier tipo de daño salvo que una habilidad
declare explícitamente `bypasses_shields=True` — ninguna lo hace en esta
base de conocimiento). El escudo de Indestructible mitiga el valor de
ese daño, pero no elimina las cargas de acumulación que lo amplificaron.


## 13. v1.6.1 — certeza, procedencia y las asimetrías que sobrevivieron

Esta sección es la vigente. Nació de una auditoría empírica del hito 1.6
sobre el par ya cargado, no de una revisión de código a ojo: cada punto
de abajo se verificó ejecutando el motor y midiendo.

**13.1 — Tres escaneos unidireccionales sobrevivieron al hito 1.6.** El
hito anterior corrigió la reciprocidad de cuatro reglas basadas en ejes y
declaró el problema resuelto. Dentro de la regla de daño quedaban tres
casos:

  * `_true_damage_and_penetration` recorría solo `candidate_abilities()`.
    Consecuencia observable: al evaluar a Mordekaiser como candidato, el
    remate de daño verdadero de Noxian Guillotine **no aparecía en
    ninguna parte de sus riesgos**, mientras su propia ventaja de escudo
    sí decía "incluido el daño verdadero". La amenaza se nombraba al
    pasar sin haberse registrado nunca.
  * `_damage_mitigation_of_sustained_plan` recorría solo
    `enemy_abilities()`. Consecuencia: el MISMO escudo de Indestructible
    valía `0.045` como ventaja de su dueño y `0.084` como penalización del
    rival.

La corrección no es de disciplina sino estructural: existe un helper
`_sides(ctx)` que devuelve los dos dueños con su polaridad, y cada
submétodo se invoca dos veces con la MISMA fórmula de magnitud. No hay
ramas separadas por dirección donde esconder una asimetría. El test
`test_every_shared_cause_is_reciprocal_in_both_directions` barre TODAS
las causas de la traza, no las reglas que alguien se acordó de auditar, y
exige misma clave, mismas premisas, polaridad opuesta y misma magnitud
absoluta; las asimetrías legítimas (hechos del kit del propio candidato,
como la exigencia de ejecución) están en una allowlist justificada.

**13.2 — `Support`: la certeza como eje propio.** El hito 1.6 tenía un
solo eje de expresión, `Polarity`, para tres preguntas distintas: hacia
dónde se inclina algo, bajo qué condición se sostiene, y cuánta certeza
hay. El resultado medido: 11 de 24 entradas de la vista causal aportaban
cero, porque la única forma de decir "esto es real pero condicionado" era
refugiarse en `CONDITIONAL`. Ahora `Support` distingue `STRUCTURAL`
(se sostiene siempre que ambos kits estén en la fase), `CONDITIONED`
(inclina amortiguado, sin volverse certeza) y `AMBIGUOUS` (doble filo
real: aporta cero, pero se conserva entero en la explicación). El
multiplicador vive en `config/weights.yaml`, viaja en cada entrada de la
traza y está documentado como heurístico sin calibrar.

**13.3 — `Provenance`: un prior editorial no es una conclusión derivada.**
Medición del hito 1.6: los dos ejes escritos a mano (`early_pressure` y
`scaling`) producían el 40 % del movimiento de score en una dirección y
el 64 % en la otra. Y un solo punto editorial de `sustain` (2 → 3) movía
el GlobalScore **2.76 puntos**, doce veces la diferencia total entre los
dos candidatos (0.23). La primera versión de v1.6.1 los bajó a un peso reducido (0.25); la
revisión de las trazas mostró que no alcanzaba (ver §13.15) y hoy **ningún
prior editorial puntúa**: se declaran, se etiquetan y se muestran en su
propio canal, con aporte cero.

**13.4 — La regla monolítica de daño, partida en tres.** La ex-G03
declaraba cinco categorías y 226 líneas (las demás reglas declaraban una
o dos): daño verdadero, penetración, dos formas de mitigación por escudo
y daño a objetivo único. Ahí adentro se escondieron los escaneos
unidireccionales de 13.1 durante todo un hito. Queda dividida en
`DamageVsResistancesRule` (G03), `ShieldAbsorptionRule` (G16) y
`SingleTargetConditionRule` (G17).

**13.5 — El guardrail de cantidad de reglas era el incentivo equivocado.**
`MAX_GENERAL_RULES = 15` era un `assert` en import time, y fue el
argumento que justificó fusionar la mitigación dentro de la regla de
daño en el hito 1.6 — es decir, un guardrail pensado para contener la
complejidad terminó causándola. Pasa a ser **blando** (tope holgado,
verificado en tests con un mensaje que invita a revisar) y se lo
reemplaza por dos controles que sí miden complejidad real:
`MAX_CATEGORIES_PER_RULE = 3` (habría detectado la ex-G03 el día que se
fusionó) y la obligación de que toda entrada declare `causal_key`.

**13.6 — `causal_key` obligatorio; una causa, una contribución.** Nueve
de veinte construcciones de `RuleEffect` no lo traían, y eso producía
doble conteo real: la comparación de recompensas de acumulación aportaba
**tres veces** (una por fase disponible) y era el 100 % de su factor; la
regla de sustain aportaba dos. Un test AST exige la clave en toda
entrada. El scoring, el narrador y el cálculo de contradicciones leen la
vista causal; la traza cruda se conserva íntegra para auditoría, y
`PhaseNote` muestra las dos vistas por separado y etiquetadas.

**13.7 — StackRace: tres situaciones, sin sumar ordinales.** El hito 1.6
publicaba "magnitud agregada 9 vs 4". Dos de los tres sumandos de ese 9
eran la MISMA relación causal —las cargas potencian la definitiva—
declarada dos veces: una como `stack_scaling` en un `amplify_ability`
autorreferencial de la R, y otra como amplificación de la recompensa. El
KB ahora declara esa relación una sola vez, sobre el efecto que
realmente escala (el daño de la R). La comparación pasa a un
`RewardProfile` tipado con dos capacidades estructurales
(`amplifies_available_ability`, `scales_with_stack_count`) y **dominancia
parcial**: si un perfil cubre estrictamente al otro se inclina, y si las
recompensas son distintas pero ninguna domina, el resultado es
`AMBIGUOUS`. No hay jerarquía de tipos de recompensa. Las tres
situaciones se emiten por separado: A (quién activa primero — no
predecible, aporta cero), B (si el intercambio se corta — favorece al de
menor umbral, `CONDITIONED`), C (si ambos completan — se inclina solo si
la traza demuestra la cadena entera umbral → recompensa propia →
amplificación de una habilidad disponible).

**13.8 — `ramp_speed_rank` era un cálculo muerto.** Se computaba solo
como guarda de early-return: el aporte de los aceleradores no era
observable en ninguna parte de la traza. Es la misma clase de problema
que el hito 1.5 eliminó de los campos del YAML, reaparecida como
función. Ahora se cita en premisas y texto de la situación A.

**13.9 — Decimate deja de ser poke.** Es un intercambio cuerpo a cuerpo
con filo exterior que cura y aplica carga. La vieja `PokeVsSustainRule`
la trataba como poke y además infería un CONTRA desde el eje editorial
`sustain >= 3` del rival — un acantilado sobre un número escrito a mano.
La reemplaza `TradeSustainRule`, que solo mira efectos: una curación
condicionada en una habilidad de intercambio sostiene a su dueño y
erosiona el saldo del otro, recíprocamente. El concepto de sustain no
desaparece: deja de entrar como número editorial, y derivarlo de efectos
reales queda en el backlog. `TacticalUse.POKE` conserva un consumidor
real en `ResourceAttritionRule`, que describe una habilidad concreta con
su exposición y su cooldown, no una identidad de kit.

**13.10 — `PullTowardEngageRule` y la dirección del desplazamiento.**
Atraer y empujar son consecuencias opuestas del mismo `EffectType` e
indistinguibles sin declararlo, así que `Effect.displacement_vector`
(`toward_self` / `away`) entra al schema. La regla es generalizable a
cualquier pull futuro: dispara cuando el objetivo es una amenaza de corta
distancia (all-in alto, movilidad baja), y **no se inclina** — quién gana
al cerrar la distancia es justamente lo que el resto del análisis intenta
establecer, así que afirmar una dirección sería circular. El uso
invertido (castear el pull hacia atrás para alejarse) sigue sin
modelarse: depende de la geometría del casteo.

**13.11 — Confidence: cuatro señales, no dos.** Las contradicciones se
cuentan sobre la vista causal (una misma tensión repetida en tres fases
valía tres); las condiciones `STRATEGIC` cuentan sin importar la
polaridad de su entrada (antes se descartaban las colgadas de un PRO o un
CONTRA, justo las que v1.6.1 empezó a producir); se separa la volatilidad
estratégica COMPARTIDA —presente en ambas direcciones— de la exigencia de
ejecución propia del candidato; y la penalización por información
faltante dejó de saturar en 5.

**13.12 — Presentación: síntesis, no solo condiciones.** Con un solo
candidato ya no se anuncia un "mejor pick" (no hubo comparación que
ganar): se dice "candidato evaluado". Se agrega `Lean` — dirección,
intensidad, confianza, factores principales y condiciones de reversión —
derivado de la misma vista causal, sin números nuevos. Las razones y
riesgos se ordenan por aporte efectivo, no por delta crudo.

**13.13 — Los dos scores suman 100, y eso no los vuelve probabilidades.**
En el hito 1.6 sumaban 98.69 por acumulación de asimetrías (los escaneos
unidireccionales de 13.1). Corregida la reciprocidad, la antisimetría es
ahora EXACTA: toda causa compartida aparece en las dos direcciones con la
misma magnitud y signo opuesto, y los únicos hechos asimétricos —los del
kit del propio candidato— hoy no puntúan. Es una consecuencia mecánica
del invariante, no una medida de probabilidad complementaria, y dejará de
ser exacta en cuanto un hecho propio del candidato mueva el score. Queda
documentado en `domain/result.py`, en el README y en la salida de la CLI
para que nadie lea ese 100 como un reparto de victoria.

**13.14 — `TacticalUse.TRADE_CUT` eliminado.** Ningún YAML lo usaba desde
el hito 1.6 y la única rama que lo leía era inalcanzable. Se documenta
como concepto descartado en `domain/enums.py`, no como vocabulario
potencial: conservarlo "por compatibilidad" es exactamente el vocabulario
muerto que la disciplina del hito 1.5 prohíbe.


### 13.15 — Ronda final de revisión de v1.6.1

Correcciones posteriores a la primera lectura de las trazas completas.

**Un prior editorial ya no puntúa, punto.** El peso reducido (0.25) no
alcanzaba: `early_pressure` aportaba `+0.0638`, más que toda la diferencia
mecánica entre los dos candidatos, así que la ventaja publicada se
invertía al quitarlo. Un peso "pequeño pero decisivo" es peor que ninguno,
porque disfraza de conclusión derivada algo que nadie derivó.
`editorial_prior` pasa a `0.0`. El prior se conserva íntegro, con su
procedencia visible, en un canal de salida propio (`editorial_priors`),
separado de la evidencia derivada. La derivación de estos ejes desde el
kit está en el backlog; no se agregó ninguna heurística de reemplazo.
`SOURCED_PRIOR` (dato externo con fuente, parche, fecha y confianza) queda
documentado en `domain/enums.py` como candidato futuro y NO implementado:
sin los puertos de estadísticas sería un miembro de enum sin consumidor.

**Las dos penetraciones existen y no puntúan.** Compartían `magnitude: 1`
y se cancelaban a `+0.015` contra `-0.015`, como si fueran equivalentes.
Un ordinal cualitativo compartido no demuestra igual intensidad,
disponibilidad ni relevancia contra las resistencias concretas del rival.
Se conservan como evidencia `STRUCTURAL` —ventaja de su dueño, riesgo del
otro, recíprocas— con aporte cero y un `invalidated_if` que dice qué
faltaría para cuantificarlas. No son `AMBIGUOUS`: que la penetración
exista no tiene nada de ambiguo; lo que no está calibrado es su peso.
Aparecen en el canal `uncalibrated_observations`.

**Noxian Might es bonus AD sobre el perfil ofensivo.** Antes era un
`empower_self` genérico (que no decía qué empoderaba) más un
`amplify_ability` sobre R (que duplicaba lo que el bonus de AD ya explica
vía el ratio). Ahora es un solo efecto `bonus_attack_damage` con
`scope: offensive_profile`, que llega a ataques básicos, Decimate,
Crippling Strike, el escalado de Hemorrhage y el ratio de la R **sin
generar una entrada de score por cada uno**. Quedan dos mecanismos
distintos con dos causas distintas: el empoderamiento ofensivo general
(recompensa al umbral, factor `stacking_payoff`) y el escalado directo del
daño de la R con las cargas (factor `mechanical_interaction`).

**Cómo se inclina el subproblema de recompensas, y por qué no por
dominancia.** Al derivar las capacidades con el mismo criterio para los
dos lados, la recompensa de daño persistente + velocidad tiene las suyas
igual que la de empoderamiento ofensivo, y **ninguna domina a la otra**.
Desempatar por conjuntos exigiría ordenar tipos de efecto entre sí, que es
justamente lo que este motor no hace. La inclinación viene de UNA relación
concreta y verificable, que cualquiera de los dos lados podría tener:
`compounds_with_accumulation` — que la recompensa alcance a una habilidad
que YA escalaba con el conteo de la MISMA mecánica. La narración describe
ambas recompensas en sus propios términos y nunca dice que una "no
amplifica ninguna habilidad".

**Realm of Death: geometría, no solo robo de estadísticas.** La
observación ahora cubre que con menos espacio cortar o espaciar el
intercambio es más difícil PARA LOS DOS, que el trade tiende a extenderse,
que sin oleada la condición de objetivo único es más fácil de cumplir, y
que ambos pueden llegar a completar su acumulación. `CONDITIONED`, sin
score, y explícitamente sin afirmar que la zona favorece a quien la creó.

**La Q sin maná es una observación propia.** Antes la diferencia de
recurso quedaba escondida en la condición de otra regla. Ahora se enuncia
sola, sin score, sin convertir a nadie en campeón de poke y sin sugerir
daño repetible sin coste.

**Confianza: cobertura no es certeza.** `ALTA` resultaba engañoso. Se
separan cuatro señales: `candidate_knowledge_coverage_*` (cuánto miró el
motor para ESTE candidato, puede diferir por dirección),
`shared_matchup_confidence` (certeza del veredicto, **simétrica** por
construcción: "A tiene ventaja sobre B" es la misma afirmación se consulte
desde donde se consulte), `shared_strategic_volatility_*` y las
condiciones de ejecución propias, que van a PersonalScore. La confianza
del veredicto tiene un techo declarado (`_UNAUDITED_KB_CEILING = MEDIA`)
mientras la KB no esté auditada y los pesos no estén calibrados, y baja a
BAJA si la volatilidad compartida es alta. No es una fórmula nueva: es un
techo, una condición y las razones enumeradas en la salida.

**Presentación.** La síntesis se redacta desde la perspectiva del
candidato evaluado ("en contra de Mordekaiser y a favor de Darius", no
"hacia Darius" en una consulta sobre Mordekaiser), y las condiciones se
reparten con sujeto explícito: qué reduciría la ventaja estimada de quien
la tiene, y qué mejoraría la posición del otro. La conclusión cualitativa
—dirección, intensidad, confianza, volatilidad, factores— va primero; el
número queda como dato técnico secundario. Las fases reportan "causas
NUEVAS que esta fase desbloquea": cero no significa que las interacciones
anteriores dejen de existir.

**Un bug que encontró un test conductual.** Al exigir que quitar en
memoria el reset o el slow de Crippling Strike cambiara la resolución de
la situación B (y no solo que ciertas palabras aparecieran), salió a la
luz que el texto decía "mediante el reset del ataque" de forma fija: seguía
afirmando un reset aunque el KB dejara de declararlo. La frase ahora se
construye con los aceleradores realmente encontrados.

**Semántica del score y versionado.** El número se documenta como
`MatchupScore`: relativo, antisimétrico por el invariante de reciprocidad,
heurístico y sin calibrar. Un `GlobalScore` futuro —matchup + composición
+ meta + loadout + PersonalScore— no tendrá obligación de sumar 100 con el
rival; queda documentado, no implementado. `knowledge_version` sube a
`0.2.1` por el cambio de contenido semántico. `schema_version` sube a
**3**: no por los campos nuevos (`displacement_vector`, `scope`, que son
opcionales y aditivos) sino porque se ELIMINARON miembros de vocabulario
(`trade_cut`, `empower_self`), y un documento v2 que los usara ya no
valida. Quitar valores permitidos rompe la compatibilidad hacia atrás;
agregar campos opcionales no.
