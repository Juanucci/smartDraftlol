# Dossier mecánico: Darius vs Mordekaiser (top lane)

Investigación de apoyo para el diseño de secuencias/estado de v1.7. **No es
conocimiento cargado en el runtime**: nada de este documento entra al motor
hasta que un hito futuro lo modele explícitamente vía `MechanicalFact` /
`InteractionSequence` / KB YAML, con su propia revisión.

## 0. Limitación metodológica de esta ronda (léase primero)

La investigación pedida priorizaba Riot Data Dragon, páginas oficiales de
campeón y notas de parche oficiales. **Ninguna de las tres estuvo disponible
esta sesión**: la política de egress de este entorno bloqueó
`ddragon.leagueoflegends.com`, `www.leagueoflegends.com`,
`wiki.leagueoflegends.com`, `leagueoflegends.fandom.com`, `www.op.gg` y
`u.gg` a nivel de red (`EGRESS_BLOCKED`, confirmado con varios dominios). El
`WebFetch` de página completa no funcionó para ninguna fuente primaria.

Lo que sí funcionó fue `WebSearch`: sus fragmentos de resultado citan texto
real de esas mismas páginas (incluida la wiki oficial) con URL, pero son
**extractos parciales**, no la página completa verificada. Dos consecuencias:

1. No pude confirmar un número de parche único y consistente para cada dato
   mecánico — los fragmentos mezclan resultados de páginas que no cité en su
   forma canónica y, en un caso (recompensa de Hemorrhage al llegar a 5
   cargas), aparecieron **dos nombres distintos para el mismo mecanismo**
   ("Noxian Might" con 30–230/30–280 AD bonus, y "Blood Rage" con 40–200 AD
   bonus) sin poder determinar cuál es el actual. Lo registro como
   contradicción sin resolver, no como hecho.
2. Todo dato de esta sección lleva confianza MEDIA como techo, nunca ALTA,
   salvo que dos fuentes independientes coincidan Y el número ya esté
   confirmado por el propio KB estructural (que si es una lectura cualitativa
   propia, sin auditar — ver `docs/decisiones-tecnicas.md` §10).

Esto no bloquea el diseño: los objetivos B, C, D de esta ronda dependen de la
**forma** de las interacciones (qué habilita qué, qué precondiciones existen),
no de valores numéricos exactos de parche. Donde el número exacto importe
para una decisión de diseño, lo marco explícitamente como pendiente de
verificación antes de cargarlo al KB.

---

## 1. Tabla de hechos, derivaciones, hipótesis y benchmarks

Convención de columnas: **Tipo** = hecho mecánico / derivación / hipótesis /
evidencia empírica. **Confianza** = ALTA / MEDIA / BAJA, según cuántas fuentes
independientes coinciden y si pude verificar la página completa (nunca pude,
así que el techo es MEDIA para datos de la wiki, y BAJA donde hay
contradicción entre fuentes).

| # | Dato | Valor / contenido | Tipo | Fuente(s) | Parche referenciado | Fecha de consulta | Confianza | Limitación |
|---|---|---|---|---|---|---|---|---|
| 1 | Decimate (Q) cooldown | 10/9/8/7/6 s | Hecho mecánico | [wiki.leagueoflegends.com/Darius](https://wiki.leagueoflegends.com/en-us/Darius) (vía snippet) | No confirmado | 2026-09 | MEDIA | Solo fragmento de búsqueda, no página completa |
| 2 | Decimate: filo exterior aplica Hemorrhage + cura por vida faltante ×campeones golpeados (máx. 3) | Confirma la asimetría exterior/interior ya modelada en el KB (`ON_OUTER_ZONE` cura+stack, `ON_INNER_ZONE` solo daño reducido) | Hecho mecánico | ídem | No confirmado | 2026-09 | MEDIA | El multiplicador "×campeones golpeados hasta 3" **no está en el KB actual** (que asume `pure_1v1`, coherente con el alcance) |
| 3 | Crippling Strike (W) cooldown | 7 s (fijo, no por rango según el fragmento) | Hecho mecánico | ídem | No confirmado | 2026-09 | MEDIA | Contradice la intuición de que escale por rango; no verificado contra tabla completa |
| 4 | Crippling Strike: reset de ataque no cancelable + 25 rango bonus + daño bonus + 90% slow por 1s | Confirma `AUTO_ATTACK_RESET` + `SLOW` ya modelados; el rango bonus y el "no cancelable" **no están representados** en el KB | Hecho mecánico | ídem | No confirmado | 2026-09 | MEDIA | — |
| 5 | Apprehend (E): cono, pull hacia Darius, rebote 150 unidades, airborne, 40% slow 1s, visión 1s | Confirma `DISPLACE_ENEMY(toward_self)` + `BRIEF_CC` + `SLOW` ya modelados. El "rebote" (empuja después de atraer) es una segunda fase de movimiento que el KB no distingue | Hecho mecánico | ídem | No confirmado | 2026-09 | MEDIA | La secuencia pull→rebote→airborne es más rica que un solo `DISPLACE_ENEMY` |
| 6 | Hemorrhage: aplicación por auto/habilidades, dura 5s, stackea hasta 5, se refresca (no acumula duración) | Confirma el modelo de `StackingMechanic` (umbral 5, `stacks_per_application=1`) | Hecho mecánico | ídem | No confirmado | 2026-09 | MEDIA | El KB no modela la duración/decaimiento (5s) — coherente con el alcance declarado de no simular tiempo real |
| 7 | Noxian Guillotine (R): daño verdadero +0–100% según cargas de Hemorrhage del objetivo; reset de cooldown si remata | Confirma `stack_scaling` sobre el efecto de daño y `COOLDOWN_RESET` on-takedown, ya modelados | Hecho mecánico | ídem | No confirmado | 2026-09 | MEDIA | El "+0–100%" es más preciso que el modelo ordinal 0..4 del KB; no se puede ni se debe copiar el número exacto sin fuente primaria |
| 8 | Recompensa al llegar a 5 cargas (o rematar con R): bonus de AD temporal (5s) + reaplica 5 cargas automáticamente | Derivación (con contradicción de nombre/número sin resolver, ver §0) | Hecho mecánico (identidad) / Hipótesis (número exacto) | ídem, dos variantes contradictorias | No confirmado | 2026-09 | BAJA en el número; MEDIA en que el mecanismo existe | **Punto crítico para el diseño**: es un efecto CON DURACIÓN (5s), no un empoderamiento permanente. El KB actual (`bonus_attack_damage`, `scope=offensive_profile`) no representa que expira ni que reaplica cargas — ver diagnóstico §C |
| 9 | Obliterate (Q, Mordekaiser): daño en área, aumentado si golpea a un único enemigo | Confirma `ON_SINGLE_TARGET_HIT` ya modelado | Hecho mecánico | [wiki.leagueoflegends.com/Mordekaiser](https://wiki.leagueoflegends.com/en-us/Mordekaiser) (vía snippet) | No confirmado | 2026-09 | MEDIA | — |
| 10 | Indestructible (W): consume el "Escudo Potencial" acumulado, dura 4s, cooldown ~8–12s por rango | Confirma `SHIELD_FROM_STORED` acumulado; el KB no modela que el escudo resultante EXPIRA a los 4s ni que consumir "gasta" el acumulado (vacía el pool) | Hecho mecánico | ídem | No confirmado (números de cooldown de una nota de parche no fechada con precisión) | 2026-09 | MEDIA | El "consume/vacía" es relevante: activar el escudo dos veces seguidas no da dos escudos completos — precondición de estado que el KB no tiene |
| 11 | Death's Grasp (E): 0.5s de demora, daño mágico, pull 250 unidades | Confirma `magic_penetration` + `DISPLACE_ENEMY` + demora, ya modelados en forma cualitativa | Hecho mecánico | ídem | No confirmado | 2026-09 | MEDIA | El "0.5s de demora" es una ventana de reacción/esquive real que el KB no representa (ninguna regla trata el pull como "puede fallar") |
| 12 | Realm of Death (R): apunta con demora (slow 75% + revela durante el cast), banishea 7s, **roba temporalmente** AD/AP/velocidad de ataque/vida máx./armadura/RM/tamaño, **cura a Mordekaiser** por parte de la vida máxima del objetivo, si el objetivo muere dentro conserva las estadísticas robadas | Hecho mecánico — bastante más rico que el actual modelo (`STAT_STEAL` + `RESTRICT_ARENA`) | Hecho mecánico | ídem (múltiples fragmentos coincidentes) | No confirmado | 2026-09 | MEDIA-ALTA (dos fragmentos independientes coinciden en la forma, aunque no en cooldowns exactos) | **Punto crítico**: el robo de stats YA es correcto en el KB, pero falta (a) la CURACIÓN a Mordekaiser (efecto nuevo, no modelado en absoluto), (b) que el robo depende de landear un cast con demora y slow revelador (precondición de acierto ausente), (c) que dentro del Death Realm ninguno de los dos puede recibir ni dar ayuda de terceros — ya cubierto conceptualmente por `pure_1v1` pero nunca declarado como consecuencia de R específicamente |
| 13 | Cooldown de Realm of Death | Un fragmento dice "140→100s por rango"; otro dice "16/14/12/10/8s" | Hipótesis contradictoria | ídem | No confirmado | 2026-09 | BAJA | Los dos números no pueden ser el mismo cooldown (probablemente un fragmento mezcla el cooldown de E, no de R) — **no usar ninguno de los dos sin verificar contra fuente primaria** |
| 14 | Benchmark: Darius vs Mordekaiser (top, Emeralda+, ~4300 partidas cada lado) | Mobalytics: Darius 53.2% WR / Mordekaiser 47.8% WR. LoLalytics: Darius 54.46% / Mordekaiser 49.02%. MetaBot: Darius 53.3% WR | Evidencia empírica (externa, NO mecánica) | [mobalytics.gg](https://mobalytics.gg/lol/champions/darius/counters/top/vs-mordekaiser), [lolalytics.com](https://lolalytics.com/lol/darius/vs/mordekaiser/build/), [metabot.gg](https://metabot.gg/en/league/champion/Darius/matchups/Mordekaiser) | ~26.16–26.17 (inconsistente entre fuentes: un snippet dice "16.17", casi seguro error de transcripción por "26.17") | 2026-09 | MEDIA (tres fuentes independientes coinciden en dirección y orden de magnitud; ninguna fue leída en página completa) | Rango/región no confirmados más allá de "Emerald+"; sin split por nivel de maestría, patch exacto de cada snapshot, ni metodología de normalización de cada sitio |

### 1.1 Qué NO se pudo obtener esta ronda

- Valores exactos de daño base y ratios de escalado (AD/AP) por rango para
  ninguna de las 10 habilidades.
- Rango de lanzamiento (unidades) de Decimate, Crippling Strike, Obliterate.
- Costo de maná/energía (no aplica: ambos son de recurso especial/gratuito,
  ya reflejado correctamente en el KB — `ResourceType.RESOURCELESS` para
  Mordekaiser).
- Un número de parche único, verificado, para fechar todo el dossier.
- Confirmación de si "Noxian Might" sigue siendo el nombre vigente del
  mecanismo o fue renombrado ("Blood Rage") en un rework reciente.

### 1.2 Coherencia con el KB actual (verificación cruzada, no investigación externa)

Todo lo confirmado arriba es **compatible** con la forma cualitativa que ya
tiene `darius.yaml`/`mordekaiser.yaml`: ningún hallazgo contradice una
relación causal ya modelada (dirección de daño, qué aplica qué). Lo que
aparece sistemáticamith es **más textura de la que el modelo actual admite**:
duraciones, demoras de cast, consumo/vaciado de un recurso acumulado, y una
consecuencia completa de R (la curación) que falta por completo. Ninguno de
estos hallazgos justifica tocar los deltas existentes — son motivo para
ampliar la EXPRESIVIDAD del modelo (objetivo D), no para recalibrar el
existente.

---

## 2. Dossier por fases

Formato por fase: habilidades disponibles → estadísticas relevantes →
aperturas posibles → secuencias representativas (con ramas) → transición de
cargas → ventanas de respuesta → condiciones de éxito/fallo → resultado
cualitativo del subproblema → información aún indeterminada.

Ninguna probabilidad de acierto se inventa. Donde hay ramas, se listan todas
sin ponderar.

### Nivel 1

**Habilidades disponibles**: cada campeón tiene una habilidad puesta (más la
pasiva, siempre activa). El orden de skill (Q/W/E primero) no está en el KB
y esta V0 no lo modela — es una decisión del jugador con múltiples ramas
válidas, no un hecho fijo.

**Estadísticas relevantes**: rango de ataque (`attack_range`: ambos 1 —
"corto", según el eje 0..4 del KB, sin unidades reales), `sustain` (Darius 2,
Mordekaiser 3, pero recordar: `sustain` es editorial y no puntúa desde
v1.6.1), `early_pressure` (Darius 4, Mordekaiser 2 — también editorial, no
puntúa).

**Aperturas posibles**:
- *Rama A — Darius agresivo*: si Darius pone Q primero, puede intentar
  golpear con el filo exterior para aplicar la primera carga de Hemorrhage y
  curarse si conecta contra campeón. Precondición: Mordekaiser debe estar al
  alcance del filo exterior (una zona, no un punto — geometría que el KB no
  representa).
- *Rama B — Mordekaiser agresivo*: si Mordekaiser pone Q primero, intenta
  golpear con Obliterate; el bonus de único objetivo aplica automáticamente
  si no hay minions cerca (a nivel 1, la wave recién está llegando —
  información de estado de oleada que esta V0 declara explícitamente no
  modelada).
- *Rama C — ninguno arriesga*: ambos animan la wave sin exponerse; no hay
  secuencia que evaluar.

**Secuencia representativa (rama A) con precondiciones y ramas**:
1. Darius se acerca al filo exterior de Q. **Precondición**: Mordekaiser no
   retrocede fuera de rango. **Si falla**: no hay contacto, no hay stack,
   round de trade sin efecto.
2. Si conecta: aplica Hemorrhage (carga 1/5) y cura por vida faltante. **No
   hay control de Darius disponible a nivel 1** (Apprehend puesto o no,
   sigue en cooldown si se usó ya, o simplemente no fue la habilidad
   elegida) — sin CC propio, Mordekaiser puede simplemente caminar fuera de
   distancia de auto-ataque después del Q, cortando el intercambio.
3. **Respuesta de Mordekaiser**: puede responder con su propio Obliterate si
   Darius se quedó cerca tras el filo exterior (el filo exterior es más una
   posición de riesgo que un espacio seguro).

**Condiciones de éxito para Darius**: conectar el filo exterior sin recibir
el Obliterate de vuelta a cambio, o recibirlo pero salir con vida
suficiente.
**Condiciones de fallo**: fallar el filo exterior (Mordekaiser fuera de
rango) deja a Darius habiendo gastado el cooldown de Q sin nada a cambio, y
expuesto un instante más cerca.

**Resultado cualitativo del subproblema**: a nivel 1, ninguno tiene
herramienta de control garantizado sobre el otro; el intercambio es de
"quién conecta primero su daño de habilidad", sin cadena de más de un paso
posible todavía (Apprehend y Crippling Strike pueden no estar
desbloqueados). **No hay base para inclinar esta fase** — es, correctamente,
donde el motor actual no produce casi ninguna entrada de score (todas las
reglas de rango/waveclear/aislamiento requieren fases posteriores o ejes que
no discriminan a nivel 1).

**Información que no puede determinarse**: qué habilidad puso cada uno
(depende del jugador), si hay summoner spells de utilidad como flash
disponibles siempre (se asume que sí, sin verificar cooldowns cruzados de
partida), estado exacto de posición/wave.

### Nivel 2

**Habilidades disponibles**: dos habilidades puestas. Esta es la primera
fase donde una **cadena de dos pasos** se vuelve posible para Darius si
priorizó E+Q o Q+E: Apprehend (control) habilitando un golpe de Q que de
otro modo no conectaría.

**Secuencia representativa — "todo-in de nivel 2" (rama con
precondiciones explícitas)**:
1. Darius castea Apprehend. **Precondición**: Mordekaiser dentro del cono, y
   Apprehend disponible (no en cooldown de un uso previo). **Rama de
   fallo**: si Mordekaiser está fuera del cono o Darius falla el ángulo, la
   secuencia termina acá — cooldown gastado, sin control, sin daño, y
   Darius avanzó posición sin nada a cambio (una apertura fallida empeora
   su exposición).
2. Si conecta: Mordekaiser es atraído, rebota, queda *airborne* y
   ralentizado 1s. **Durante esta ventana**, Darius puede aplicar un
   auto-ataque y/o el filo exterior de Q.
3. Con Q disponible: golpe de filo exterior sobre un objetivo inmovilizado
   tiene una probabilidad de acierto estructuralmente mayor que sobre un
   objetivo libre — pero esta V0 **no cuantifica** esa diferencia (no hay
   modelo de probabilidad de acierto, por diseño). Lo único que se puede
   afirmar sin inventar un número es la relación causal: *el control de
   Apprehend crea la ventana en la que el filo exterior de Q es más fácil
   de conectar*.
4. Cada impacto (auto + Q) aplica una carga de Hemorrhage: hasta 2 cargas en
   una sola apertura si ambas conectan.

**Respuesta de Mordekaiser disponible en esta fase**: si tiene Indestructible
puesta, puede activarla para absorber parte del daño de la secuencia —
**pero solo si ya acumuló escudo potencial** (ha recibido o infligido daño
antes de este intercambio). Si es el primer contacto de la partida, el
escudo acumulado puede ser mínimo o nulo — precondición de estado que hoy
el motor no representa (`ShieldAbsorptionRule` asume una magnitud fija,
como si el escudo estuviera siempre "cargado").

**Condiciones de éxito para Darius**: conectar Apprehend Y el follow-up,
saliendo con Mordekaiser en 2 cargas de Hemorrhage sin haber recibido un
intercambio equivalente.
**Condiciones de fallo**: fallar Apprehend (fin de la secuencia en el paso
1), o conectarlo pero que Mordekaiser tenga escudo suficiente acumulado
para neutralizar la mayor parte del daño del follow-up.

**Resultado cualitativo**: esta es la primera fase donde "control habilita
otra acción" es un mecanismo real y observable — y es exactamente el tipo
de cadena que el motor actual no puede expresar como una sola unidad: hoy
Apprehend puntúa (o no) por `DisplacementVsMobilityRule`/`PullTowardEngageRule`
de forma aislada, sin ninguna conexión hacia el hecho de que también
acelera la acumulación de Hemorrhage.

**Información indeterminada**: si Mordekaiser realmente tiene Indestructible
puesta a nivel 2 (depende del orden de skill del jugador), cuánto escudo
potencial acumulado tiene en ese momento exacto de la partida.

### Niveles 3–5

**Habilidades disponibles**: kit completo salvo la definitiva en ambos
lados. Ambos pueden ejecutar su combo completo de no-ultimate.

**Estadísticas relevantes**: aquí `all_in` (ambos 4) y `durability` (Darius
3, Mordekaiser 4) empiezan a importar — Darius tiene alto all-in con
durabilidad media; `AllInFragilityRule` ya lo modela como riesgo propio
(CONDITIONAL, STRATEGIC).

**Secuencias representativas**:

*Secuencia extendida de Darius (generalización de la de nivel 2, ahora con
W)*:
1. Apprehend conecta (misma precondición y rama de fallo que antes).
2. Auto-ataque durante la ventana de control.
3. Crippling Strike sobre el siguiente auto: resetea el ataque (adelanta el
   próximo golpe) y aplica 90% de slow — la ventana de contacto se extiende
   más allá de lo que el control de Apprehend por sí solo daría.
4. Filo exterior de Q, si el cooldown ya se recuperó (Q suele tener
   cooldown más corto que Apprehend a este nivel — dato no confirmado con
   precisión, ver §1).
5. Con 3–4 cargas de Hemorrhage aplicadas en una sola secuencia, Darius
   queda a 1–2 impactos de Noxian Might (aunque R todavía no existe: el
   umbral de 5 cargas se activa igual sin necesitar el ultimate).

**Ramas de interrupción**: en cualquier paso, Mordekaiser puede:
- Activar Indestructible si tiene escudo acumulado suficiente (reduce el
  valor de los pasos 2–4 sin impedirlos).
- Si su propio E (Death's Grasp) está disponible, intentar su propio pull
  para interrumpir el posicionamiento de Darius — pero Death's Grasp tiene
  0.5s de demora antes de aplicar el efecto, así que no es una respuesta
  instantánea.
- Simplemente recibir el combo completo si no tiene ninguna herramienta
  disponible en el momento (todo en cooldown).

**Secuencia representativa de Mordekaiser (contra-ataque en el mismo
intercambio)**: Obliterate (idealmente a un único objetivo, si no hay
minions cerca) + auto-ataques aplicando Darkness Rise. A 3 cargas
(Q+auto+auto, o E+Q, dependiendo de qué conecte), activa Darkness Rise:
daño de aura + velocidad de movimiento por una ventana con duración (no
modelada en el KB actual, coherente con el alcance).

**Condición de éxito para Darius**: completar la secuencia de 4 pasos y
llegar a Noxian Might, aunque R siga sin desbloquear — esto ya es una
amenaza real de daño explosivo en un pick de nivel 2-3 con auto reset, y es
precisamente el "pago temprano" que el diagnóstico (§3) marca como ausente
del motor.
**Condición de éxito para Mordekaiser**: absorber suficiente del combo con
Indestructible Y devolver Obliterate+Darkness Rise antes de que Darius
llegue a las 5 cargas.
**Condición de fallo compartida**: cualquiera de los dos puede fallar su
propia secuencia en el primer paso (Apprehend / Obliterate no conectan) y
terminar solo habiendo gastado cooldowns.

**Resultado cualitativo**: este es el tramo donde el motor actual pierde
más información real. Hoy solo ve fragmentos: `stack_race:short_trade`
compara umbrales (5 vs 3) sin secuencia; `trade_sustain` ve la curación de Q
aislada; `displacement_control`/`pull_engage_tradeoff` ven a Apprehend
aislado. Ninguna regla actual conecta "Apprehend conecta → esto habilita
más golpes de auto/Q → esto acelera Hemorrhage" como una sola cadena con una
precondición de acierto compartida.

**Información indeterminada**: si el jugador realmente ejecuta la secuencia
de 4 pasos (depende de su habilidad — por diseño, esta V0 no evalúa
ejecución del jugador salvo como `ConditionKind.EXECUTION` genérico), estado
exacto de vida/escudo de cada uno al momento del intercambio.

### Nivel 6

**Habilidades disponibles**: ambas definitivas. Cambia cualitativamente el
subproblema: ahora ambos ultimates son parte de la secuencia posible.

**Secuencias representativas**:

*Rama Darius — "cierre con R"*: si Darius ya tiene 3+ cargas de Hemorrhage
sobre Mordekaiser (de un intercambio previo o del propio combo de esta
fase) y logra conectar Noxian Guillotine, el daño verdadero escala con esas
cargas y, si remata, resetea el cooldown de R. **Precondición fuerte**: las
cargas deben estar activas (no decayeron — recordar que Hemorrhage se
refresca pero también expira; el KB no modela expiración, así que esta
precondición temporal HOY es invisible para el motor).

*Rama Mordekaiser — "Realm of Death como respuesta o como iniciación"*:
- *Si Mordekaiser inicia con R*: aísla a Darius del resto de la lane (en
  esta V0, del resto del análisis — ya es un 1v1 puro, así que el efecto
  real es robar stats + restringir la geometría del duelo, no "quitar
  ayuda externa"). **Precondición de acierto**: R tiene un cast con demora
  (revela y ralentiza) antes de banishear — Darius puede, en teoría, tener
  una ventana para reaccionar (aunque esta V0 no modela reacción del
  jugador). **Consecuencia adicional no modelada hoy**: Mordekaiser se cura
  por una porción de la vida máxima de Darius al conectar R — un efecto que
  hoy no existe en el KB en absoluto.
- *Si Mordekaiser usa R como respuesta al all-in de Darius*: lo mismo, pero
  con el añadido de que dentro del Death Realm ninguno de los dos puede
  recibir ayuda de terceros — en un 1v1 puro esto no cambia nada
  estructural (ya no había ayuda que perder), así que el único efecto real
  es el robo de stats + la curación + la geometría del duelo.

**Ventana de respuesta cruzada**: si Darius ya viene con 3+ cargas de
Hemorrhage y suficiente HP, extender el duelo DENTRO del Realm (que además
restringe el espacio, favoreciendo el contacto sostenido) puede acercarlo a
su propia recompensa de acumulación antes de que termine el banish de 7s —
exactamente la observación de geometría que `IsolationRule._restrict_arena`
ya captura de forma genérica (favorece a quien sostiene el contacto, no
necesariamente a quien creó la zona), aunque sin saber todavía que viene
acompañada de una curación real a favor de Mordekaiser.

**Condiciones de éxito para Darius**: llegar a nivel 6 con cargas ya
aplicadas y useR con ellas activas, o sobrevivir el Realm de Mordekaiser el
tiempo suficiente para rematar con R propio al salir.
**Condiciones de éxito para Mordekaiser**: conectar R antes de que Darius
acumule 5 cargas, capturando la curación y el robo de stats.
**Condiciones de fallo**: Darius gasta R sin cargas suficientes (pierde la
mayor parte del bono de daño verdadero); Mordekaiser falla el cast de R
(ventana de demora) y queda expuesto sin su herramienta principal.

**Resultado cualitativo**: nivel 6 es donde el motor actual SÍ tiene algo de
razón estructural (situación C de StackRace empieza a inclinarse hacia
Darius recién acá, por la composición R+Hemorrhage) pero **sigue sin la
curación de Realm of Death, sin la precondición de acierto de R, y sin
conectar el "trae cargas ya aplicadas" como precondición de la propia
situación C** — hoy situación C se evalúa como si ambos llegaran a nivel 6
con cero cargas previas.

**Información indeterminada**: cuántas cargas de Hemorrhage sobreviven
hasta nivel 6 (depende de cuántos intercambios previos hubo y si
decayeron), estado exacto de escudo/HP de ambos al momento de decidir quién
inicia con su ultimate.

---

## 3. Resumen de hallazgos que alimentan el diagnóstico (§C del documento de diseño)

1. Confirma que las relaciones causales ya modeladas (quién aplica qué,
   quién amplifica qué) son estructuralmente correctas — la investigación
   no encontró ninguna dirección causal invertida o falsa en el KB actual.
2. La brecha real es de **secuencia y estado**, no de vocabulario de
   efectos: casi todo lo que falta (duración, demora de cast, consumo de un
   recurso acumulado, curación de R, precondición de acierto) es "cuándo y
   bajo qué condición se activa un efecto ya conocido", no un efecto nuevo
   que el motor no sepa nombrar.
3. Un hallazgo concreto y accionable: **Realm of Death cura a Mordekaiser**.
   Esto no está en el KB en absoluto y no es un matiz — es un efecto
   completo ausente. Cuando exista fuente primaria verificada, es candidato
   directo a un nuevo `EffectType` (posiblemente reutilizando `HEAL` con una
   condición, o uno nuevo si "curar por vida máxima ROBADA del objetivo" no
   encaja en el `HEAL` genérico existente — a decidir en el hito que lo
   implemente, no en este).
