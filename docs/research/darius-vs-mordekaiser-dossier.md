# Dossier mecánico: Darius vs Mordekaiser (top lane)

Investigación de apoyo para el diseño de secuencias/estado de v1.7. **No es
conocimiento cargado en el runtime**: nada de este documento entra al motor
hasta que un hito futuro lo modele explícitamente vía `Effect`/`FactRef`
existentes, `InteractionSequence` o KB YAML, con su propia revisión. v1.7
no introduce una clase `MechanicalFact` nueva — ver
`v1.7-sequence-state-design.md` §B.1.

Este documento es una especificación viva: cada afirmación tiene una sola
formulación vigente. El historial de cómo se llegó a cada corrección vive en
`git log`/`git diff` de este archivo, no en el propio texto.

---

## 1. Procedencia y método

La política de egress de este entorno bloquea el acceso directo a
`ddragon.leagueoflegends.com`, `www.leagueoflegends.com`,
`wiki.leagueoflegends.com`, `raw.communitydragon.org`, `mobalytics.gg`,
`lolalytics.com` y `u.gg` (confirmado repetidamente, tanto por `curl` como
por `WebFetch`, en varias sesiones). Ni `WebSearch` ni fragmentos de
búsqueda sustituyen una fuente primaria completa — donde se usaron
(primera ronda de este dossier), el techo de confianza quedó en MEDIA y
nunca en ALTA.

El grueso de los hechos mecánicos actuales viene de
`lol_matchup_source_pack_26.17_2026-09-09.zip`, un paquete de evidencia
adjuntado por el usuario para sortear ese bloqueo. Verificación de
integridad realizada sobre ese paquete (fuera del repo, sin tocar el
working tree):

- Los 3 archivos JSON mirror de Data Dragon (`sources/*.json`) tienen su
  SHA-256 **recalculado independientemente** y coincide exactamente con lo
  declarado en `SOURCE_MANIFEST.json`.
- `VERIFY.sh` fue inspeccionado antes de ejecutar (solo `sha256sum --check`
  + 3 aserciones `jq`, sin red, sin nada destructivo) y corrido con éxito.
- Los tooltips/descripciones completos de cada pasiva y hechizo se leyeron
  directamente de los JSON crudos con `jq` (no solo el resumen del propio
  paquete), para no heredar ciegamente su capa de interpretación.

**Límite de lo que esto prueba**: la verificación anterior confirma
*consistencia interna* (el paquete es fiel a sí mismo) y que el JSON tiene
la forma exacta de un export real de Data Dragon. No confirma, de forma
independiente por esta sesión, que el commit del repositorio-espejo citado
(`github.com/noxelisdev/LoL_DDragon` @ `892a18751831d9aa4f5791dc01e6a881840784c2`)
sea fiel al CDN de Riot — esta sesión sigue sin poder alcanzar ese CDN en
vivo. Por eso todo dato citado como `riot_ddragon_*` se marca **ALTA-CONDICIONADA**
(no "ALTA-independiente"): alta en tanto se acepta la cadena de custodia
declarada, no auditada contra el CDN en vivo. Las notas de parche oficiales
citadas en el manifiesto (`riot_patch_25_12` … `riot_patch_26_17`) son URLs,
no texto espejado — cualquier valor cuya única fuente sea una de esas URLs
queda en MEDIA, nunca ALTA, hasta que exista un byte verificable detrás.

**Identidad de parche**: "Patch 26.17" (notas públicas de Riot) y "16.17.1"
(versión técnica de Data Dragon) son el mismo parche con dos sistemas de
numeración — no dos parches distintos. Se citan indistintamente como
`26.17 / 16.17.1`.

**Jerarquía de fuentes** (vale para todo el proyecto, no solo este matchup):

| Nivel | Tipo de fuente | Techo de confianza |
|---|---|---|
| 1 | Datos/archivos oficiales del parche vigente (Data Dragon, notas de parche oficiales) | ALTA-condicionada si hay bytes verificables (hash o lectura directa); MEDIA si solo se cita la URL sin releer el contenido |
| 2 | Datos raw estructurados de terceros (CommunityDragon, Meraki) | MEDIA — requiere reconciliación contra Nivel 1; nunca importar un snapshot `latest` en bloque (ver hallazgo de Death's Grasp, §2) |
| 3 | Documentación secundaria confiable (wiki comunitaria, etc.) | MEDIA |
| 4 | Sitios de estadísticas (benchmarks externos) | Nunca alimenta hechos mecánicos — ver `benchmark-format.md` |
| 5 | Fragmentos de búsqueda sin página completa | BAJA, solo como hipótesis a verificar |

Si dos fuentes de distinto nivel discrepan, se documenta la contradicción
(§3) y se prioriza la de nivel más alto — nunca se elige en silencio la que
da el resultado esperado.

---

## 2. Hechos mecánicos vigentes

| # | Campeón | Dato | Valor vigente | `source_id` | Confianza | Categoría |
|---|---|---|---|---|---|---|
| 1 | Darius | Stats base (HP/AD/Armor/MR/MS/Rango de ataque) | 652 / 64 / 37 / 32 / 340 / 175 | `riot_ddragon_darius` | ALTA-cond. | FACT |
| 2 | Darius | Recurso | Maná, base 263 (+58/nivel) | `riot_ddragon_darius` | ALTA-cond. | FACT |
| 3 | Darius | Pasiva (Hemorrhage): duración y stacks | 5 s por aplicación, hasta 5 cargas | `riot_ddragon_darius` (tooltip) | ALTA-cond. | FACT |
| 4 | Darius | Hemorrhage: ¿se refresca o acumula duración? | Se refresca por aplicación (no acumula duración) | `meraki_darius` | MEDIA | DERIVATION |
| 5 | Darius | Recompensa a 5 cargas: existencia | Bono temporal de AD por 5 s al llegar a 5 cargas de Hemorrhage sobre el objetivo | `riot_ddragon_darius` (tooltip, sin nombrar el efecto) | ALTA-cond. | FACT |
| 6 | Darius | Recompensa a 5 cargas: nombre y magnitud | "Noxian Might", bono de AD 30–230 según nivel | `meraki_darius` | MEDIA | DERIVATION |
| 7 | Darius | Q (Decimate) cooldown | 9/8/7/6/5 s | `riot_ddragon_darius` | ALTA-cond. | FACT |
| 8 | Darius | Q: filo vs. mango | Filo: `50 + 100% AD total` (~114 de daño con AD base), aplica Hemorrhage. Mango: 35% de ese daño, **no** aplica Hemorrhage | `riot_ddragon_darius` (estructura) / `meraki_darius` (números) | ALTA-cond. (estructura) / MEDIA (números) | FACT / DERIVATION |
| 9 | Darius | Q: curación por filo | 17/34/51% de vida faltante por 1/2/3+ campeones o monstruos grandes golpeados con el filo | `riot_patch_25_14` (no releída) | MEDIA | FACT |
| 10 | Darius | W (Crippling Strike) cooldown | 5 s, fijo en las 5 gradas | `riot_ddragon_darius` | ALTA-cond. | FACT |
| 11 | Darius | W: empoderamiento del próximo ataque | +140–160% AD total según grada; ralentiza 90% por 1 s | `meraki_darius` (magnitudes); `riot_ddragon_darius` (existencia del slow) | MEDIA (magnitudes) / ALTA-cond. (existencia) | DERIVATION |
| 12 | Darius | W: ¿resetea el temporizador de ataque? | Afirmado solo por fuente Tier 2; el tooltip crudo no lo menciona | `meraki_darius` | MEDIA | DERIVATION — contradicción abierta (§3) |
| 13 | Darius | E (Apprehend) cooldown | 26/23.5/21/18.5/16 s | `riot_ddragon_darius` | ALTA-cond. | FACT |
| 14 | Darius | E: rango y penetración pasiva | Rango 535; pasivo 20/25/30/35/40% de penetración de armadura por grada | `riot_ddragon_darius` | ALTA-cond. | FACT |
| 15 | Darius | E: efecto activo | Pull + knockup + slow hacia Darius. **No hace daño ni aplica Hemorrhage por sí sola** | `riot_ddragon_darius` (tooltip) | ALTA-cond. | FACT |
| 16 | Darius | E: ¿segunda fase de "rebote" tras el pull? | Sin respaldo — el tooltip solo describe pull/knockup/slow | — | — | HYPOTHESIS no confirmada; no cargar al KB |
| 17 | Darius | R (Noxian Guillotine) cooldown | 120/100/80 s | `riot_ddragon_darius` | ALTA-cond. | FACT |
| 18 | Darius | R: daño y targeting | Verdadero, escala con las cargas de Hemorrhage del objetivo hasta un máximo; unit-targeted (Darius se desplaza al objetivo) | `riot_ddragon_darius` (tooltip) | ALTA-cond. | FACT |
| 19 | Darius | R: comportamiento al rematar | Cualquier grada: recast disponible en una ventana tras matar. **Solo en grada 3**: además sin coste de maná y con reinicio total del cooldown | `riot_ddragon_darius` (tooltip) | ALTA-cond. | FACT |
| 20 | Mordekaiser | Stats base (HP/AD/Armor/MR/MS/Rango de ataque) | 645 / 61 / 37 / 32 / 335 / 175 | `riot_ddragon_mordekaiser` | ALTA-cond. | FACT |
| 21 | Mordekaiser | Recurso | `partype: "Shield"` — ningún hechizo tiene coste de maná; el campo `mp=100` del schema genérico de Data Dragon no es funcional | `riot_ddragon_mordekaiser` | ALTA-cond. | FACT |
| 22 | Mordekaiser | Pasiva (Darkness Rise) | Se activa tras 3 golpes (ataques o hechizos) contra campeones o monstruos; recompensa = aura de daño + velocidad de movimiento | `riot_ddragon_mordekaiser` (tooltip) | ALTA-cond. | FACT |
| 23 | Mordekaiser | Q (Obliterate) cooldown, rango y cast | 8/7/6/5/4 s; rango 675; ~0.5 s de cast | `riot_ddragon_mordekaiser` (cooldown/rango); `meraki_mordekaiser` (cast) | ALTA-cond. (cooldown/rango) / MEDIA (cast) | FACT |
| 24 | Mordekaiser | Q: daño y bono por objetivo único | Estructura confirmada: más daño si golpea a un único enemigo. Magnitud: base `80/115/150/185/220` + 70% AP + 120% AD bonus; multiplicador aislado `1.30–1.50` por grada | `riot_ddragon_mordekaiser` (estructura); `meraki_mordekaiser` + notas de parche no releídas (números) | ALTA-cond. (estructura) / MEDIA (números) | FACT / DERIVATION |
| 25 | Mordekaiser | Q: ¿qué pasa si golpea más de un objetivo? | Daña a **todas** las unidades alcanzadas (no hay un pool de daño que se reparta entre ellas — cada unidad golpeada recibe el daño de la habilidad). Simplemente **no** obtiene el bono de objetivo único, que solo aplica cuando golpea a un único enemigo | `riot_ddragon_mordekaiser` (tooltip: "dealing damage to each enemy struck... increased if it hits only a single enemy") | ALTA-cond. | FACT |
| 26 | Mordekaiser | W (Indestructible) cooldown | 12/11/10/9/8 s | `riot_ddragon_mordekaiser` | ALTA-cond. | FACT |
| 27 | Mordekaiser | W: mecanismo | Pasivo almacena % del daño dado y % del daño recibido → activo lo convierte en escudo real → recast opcional convierte el escudo restante en curación. Tope: 30% de la vida máxima | `riot_ddragon_mordekaiser` (mecanismo); `meraki_mordekaiser` (tope) | ALTA-cond. (mecanismo) / MEDIA (tope) | FACT |
| 28 | Mordekaiser | E (Death's Grasp) cooldown y rango | 16/14/12/10/8 s; rango 700 | `riot_ddragon_mordekaiser` | ALTA-cond. | FACT |
| 29 | Mordekaiser | E: penetración pasiva y daño | Pasivo 5/7.5/10/12.5/15% penetración mágica; daño vigente `60/80/100/120/140 + 45% AP` | `meraki_mordekaiser` (pen.); `riot_patch_26_14` no releída (daño) | MEDIA | DERIVATION — el JSON `latest` de Meraki trae un valor de daño obsoleto (`60/75/90/105/120+40%AP`); no importar snapshots `latest` sin reconciliar contra Nivel 1 |
| 30 | Mordekaiser | E: ¿demora antes de aplicar el pull? | Existe cualitativamente. El único `cast_time_seconds: 0.5` explícito del paquete está asignado a Q y a R, **no** a E — no asumir el mismo valor sin fuente puntual | Texto del paquete (sin `source_id` numérico para E) | MEDIA (que existe) | HYPOTHESIS parcial — contradicción abierta (§3) |
| 31 | Mordekaiser | R (Realm of Death) cooldown, rango y cast | 140/120/100 s; rango 650; ~0.5 s de cast | `riot_ddragon_mordekaiser` (cooldown/rango); `meraki_mordekaiser` (cast) | ALTA-cond. (cooldown/rango) / MEDIA (cast) | FACT |
| 32 | Mordekaiser | R: targeting | Unit-targeted / point-and-click — **no** es un skillshot, no lleva una condición genérica de "acierto" | `meraki_mordekaiser` (clasificación); tooltip crudo (redacción consistente) | MEDIA | FACT |
| 33 | Mordekaiser | R: invalidadores del cast (~0.5 s) | Únicos respaldados por el paquete: objetivo untargetable, fuera de rango o sin visión al completarse el cast; inmunidad o interacción de spell shield. **Ningún otro invalidador está confirmado** (p. ej. que un CC/silencio sobre el propio Mordekaiser corte el cast no tiene fuente en el paquete — no se afirma) | Texto citado del paquete, sin `source_id` numérico | MEDIA | FACT (los listados) — el resto queda como ausencia declarada, no como hecho |
| 34 | Mordekaiser | R: efecto durante los 7 s de duración | Roba 10% de las estadísticas centrales del objetivo; si lo mata dentro, conserva las estadísticas hasta que el objetivo reaparece | `riot_ddragon_mordekaiser` (tooltip) | ALTA-cond. | FACT |
| 35 | Mordekaiser | R: ¿hay además un componente de curación/transferencia de vida separado del robo de stats? | El tooltip crudo **solo** describe robo de estadísticas — ninguna mención de curación. Un componente de vida solo aparece en fuentes no releídas / Tier 2 | Tooltip crudo (sin heal); fuente no releída + `meraki_mordekaiser` (posible heal) | ALTA-cond. (que el tooltip no lo menciona) / MEDIA (que podría existir igual) | HYPOTHESIS — regla de modelado en §4 (Nivel 6) |
| 36 | Ambos | Penetración de armadura (Darius) vs. penetración mágica (Mordekaiser) | Fortalezas paralelas contra defensas distintas — no se cancelan ni se comparan sin valores por nivel, resistencias del objetivo y contexto de daño real. Observación estructural de **aporte cero**, pendiente de calibración | `riot_ddragon_darius` (armor pen); `meraki_mordekaiser` (magic pen) | ALTA-cond. (que el % existe) | Guardrail de diseño, no causa puntuable |
| 37 | Darius | R: ¿puede lanzarse dentro de Realm of Death de Mordekaiser? | Sí — el Realm aísla el duelo del resto de la partida, pero **no deshabilita las habilidades entre los dos combatientes**. Noxian Guillotine no está limitado a lanzarse solo antes de entrar o después de salir del Realm | Texto del paquete (síntesis, sin `source_id` numérico) | MEDIA | FACT |

Los benchmarks externos (winrate, GD@15, etc.) viven exclusivamente en
`benchmark-format.md` — nunca en esta tabla. Mezclarlos aquí violaría la
separación mecánico/empírico que ese mismo documento exige.

---

## 3. Contradicciones

**Resueltas:**

- Cooldown de Realm of Death (R) vs. Death's Grasp (E) de Mordekaiser: son
  habilidades distintas — R = `140/120/100 s`, E = `16/14/12/10/8 s`.
  Confirmado con fuente Tier 1 hash-verificada (fila 17/28 y 31 de §2).
- Nombre del bono de AD a 5 cargas de Hemorrhage: sin ninguna fuente (Tier 1
  ni Tier 2) que sostenga "Blood Rage"; "Noxian Might" es el único nombre
  con algún respaldo (Tier 2).
- Daño de Death's Grasp (E): el valor vigente (`60/80/100/120/140+45%AP`)
  prevalece sobre el snapshot `latest` obsoleto de Meraki
  (`60/75/90/105/120+40%AP`), por la jerarquía de fuentes de §1.

**Abiertas** (no resueltas por conveniencia — quedan en la confianza que
les corresponde hasta encontrar mejor fuente):

- ¿Crippling Strike (Darius W) resetea el temporizador de ataque? (fila 12)
- ¿La demora del pull de Death's Grasp (Mordekaiser E) es exactamente 0.5s,
  o ese valor pertenece solo a Q/R? (fila 30)
- ¿Apprehend tiene una segunda fase de "rebote" tras el pull? Sin respaldo,
  no se carga al KB en ningún caso mientras siga así (fila 16).
- ¿Existe un componente de curación en Realm of Death, distinto del robo de
  stats? (fila 35) — la regla de modelado (§4, Nivel 6) no depende de
  resolver esto: se modela como un único grupo causal se confirme o no.
- Los números exactos de daño/ratios de Q de Mordekaiser y la mayoría de
  las magnitudes citadas de Meraki no tienen una fuente Tier-1 textual
  completa que los confirme carácter por carácter — límite real de lo que
  Data Dragon expone en su tooltip templado (`{{ variable }}`) sin resolver
  sus fórmulas internas, no reconstruido esta ronda.

---

## 4. Dossier por fases

Formato por fase: habilidades disponibles → estadísticas relevantes →
aperturas posibles → secuencias representativas (con ramas) → condiciones
de éxito/fallo → resultado cualitativo → información indeterminada. Ninguna
probabilidad de acierto se inventa; donde hay ramas, se listan todas sin
ponderar cuál es más probable.

### Nivel 1

**Habilidades disponibles**: cada campeón tiene una habilidad puesta (más
la pasiva, siempre activa). El orden de skill no está fijo — es una
decisión del jugador con múltiples ramas válidas.

**Estadísticas relevantes**: rango de ataque igual para ambos (175, fila 1
y 20 de §2).

**Rama A — Darius abre con Q**: Darius busca golpear con el filo exterior
para aplicar la primera carga de Hemorrhage y curarse si conecta contra
campeón.
1. Darius se acerca al filo exterior. **Precondición**: Mordekaiser no
   retrocede fuera de esa zona. **Si falla**: sin contacto, sin stack, Q
   gastado sin efecto.
2. Si conecta: aplica Hemorrhage (carga 1/5). La curación depende del orden
   de resolución frente al daño recibido — ver Rama E más abajo para el
   detalle de esa dependencia quirúrgica (aplica igual aquí: ambos parten
   de vida completa, así que si el filo resuelve antes de que Darius reciba
   cualquier daño, la vida faltante en ese instante es cero).
3. **Respuesta de Mordekaiser**: puede contraatacar con su propio Obliterate
   si Darius quedó cerca tras el filo (el filo exterior es una posición de
   riesgo, no un espacio seguro).

**Condiciones de éxito para Darius**: conectar el filo sin recibir el
Obliterate de vuelta, o recibirlo y salir con vida suficiente.
**Condiciones de fallo**: Mordekaiser fuera de rango — Q gastado sin nada a
cambio, y Darius más expuesto.

**Rama B — Mordekaiser abre con Q**: busca golpear con Obliterate; el bono
de objetivo único aplica si no hay minions cerca (a nivel 1 la oleada recién
llega — estado de oleada declarado como no modelado en esta V0).

**Rama C — ninguno arriesga**: ambos animan la oleada sin exponerse; no hay
secuencia que evaluar.

**Rama D — Darius abre con W**: W es un empoderamiento del **propio próximo
ataque** de Darius — no un hechizo dirigido a Mordekaiser, así que su
activación no requiere que Mordekaiser esté dentro de ningún rango en ese
instante, y no entra en un "cooldown vacío" por eso. Se desperdicia
únicamente si la ventana del empoderamiento termina sin que Darius llegue a
ejecutar el ataque correspondiente (p. ej. Mordekaiser se aleja antes de que
Darius pueda swingear). Dos aperturas posibles, con distinto número de
cargas de Hemorrhage aplicadas:

- **Apertura directa con el ataque empoderado (sin AA previo)**: un único
  ataque potenciado conecta → una sola aplicación de Hemorrhage (carga
  1/5), con el daño empoderado (+140–160% AD total, fila 11) y 90% de slow
  por 1 s sobre Mordekaiser.
- **Cadena `AA → W` (reset)**: primero un auto-ataque normal conecta
  (carga 1/5 si es el primer contacto), y si el reset de temporizador
  ocurre (fila 12 — MEDIA, contradicción abierta, no se sube su certeza
  aquí), un segundo ataque (el empoderado por W) conecta antes de lo que
  ocurriría sin el reset → dos auto-ataques, **dos** aplicaciones de
  Hemorrhage (cargas 1/5 y 2/5) en una sola apertura, más el slow de W en el
  segundo golpe.

El slow de W recae sobre Mordekaiser, no sobre Darius, así que no expone
más a quien lo activa — si acaso, ayuda a sostener el contacto para el
siguiente golpe.

**Condiciones de éxito para Darius**: conectar el ataque correspondiente
(uno o dos, según la apertura) antes de que Mordekaiser se separe.
**Condiciones de fallo**: la ventana de empoderamiento termina sin que
Darius conecte el ataque — W gastado sin efecto.

**Rama E — Q de Darius vs. Q de Mordekaiser**: comparación de las 4
combinaciones posibles de un intercambio de Q entre ambos. El orden de
resolución entre el Q de Darius y el Q de Mordekaiser **no está determinado
por esta V0** (depende de inputs del jugador y de la resolución del motor
del juego, fuera de alcance) — no se llama "simultáneo" a este intercambio
porque la curación del filo de Darius depende exactamente de ese orden:

| Combinación | Efecto en Darius (filo/mango) | Efecto en Mordekaiser (aislado/no aislado) |
|---|---|---|
| Darius filo + Mordekaiser aislado | Aplica Hemorrhage (carga 1/5). Curación: **depende del orden** — ver ramas de resolución abajo | Daño aumentado por objetivo único (multiplicador ~1.30 a grada 1, fila 24, MEDIA) |
| Darius filo + Mordekaiser no aislado (con minions cerca) | Igual que arriba en Hemorrhage/curación | Daña a todas las unidades golpeadas (sin reparto de un pool); **no** obtiene el bono de objetivo único (fila 25) |
| Darius mango + Mordekaiser aislado | Solo 35% del daño del filo, **sin** aplicar Hemorrhage y **sin** curación (fila 8) | Daño aumentado por objetivo único, igual que arriba |
| Darius mango + Mordekaiser no aislado | Igual que arriba (sin Hemorrhage, sin curación) | Sin bono de objetivo único |

**Ramas de resolución de la curación del filo (ambos parten de vida
completa)**:
- Si el filo de Darius resuelve **antes** de que reciba cualquier daño en
  el intercambio → su vida faltante en ese instante es 0 → la curación es
  efectivamente nula (17% de 0 faltante = 0), aunque la fórmula "17% de
  vida faltante" siga siendo correcta.
- Si Darius recibe daño primero (p. ej. el Q de Mordekaiser resuelve antes)
  y **luego** conecta el filo → tiene vida faltante en ese instante → cura
  17% de esa vida faltante (por un campeón golpeado).
- Si Darius conecta con el **mango** → no hay curación en ningún caso,
  independientemente del orden, porque el mango no dispara ese efecto.

Ninguna de las 4 combinaciones ni de las 3 ramas de orden se declara "más
probable" — existen para que una futura `InteractionSequence` declare sus
ramas explícitas con sus propias precondiciones (¿filo o mango? ¿minions
cerca de Mordekaiser? ¿qué Q resolvió primero?), no para resolver el
intercambio aquí.

**Información indeterminada (todas las ramas de Nivel 1)**: qué habilidad
puso cada uno, estado exacto de posición/oleada, disponibilidad de
summoner spells.

### Nivel 2

**Habilidades disponibles**: dos habilidades puestas. Primera fase donde
una cadena de dos pasos es posible para Darius (E+Q o Q+E): Apprehend
habilita un golpe de Q que de otro modo no conectaría.

**Secuencia representativa — "todo-in de nivel 2"**:
1. Darius castea Apprehend. **Precondición**: Mordekaiser dentro del cono,
   y Apprehend disponible.
2. Si conecta: Mordekaiser es atraído, queda airborne y ralentizado 1 s.
   Durante esta ventana Darius puede aplicar un auto-ataque y/o el filo de
   Q.
3. Cada impacto (auto + Q) aplica una carga de Hemorrhage: hasta 2 cargas
   en una sola apertura si ambas conectan.

**Ramas de fallo — dos causas distintas, mismo resultado observable pero
distinto estado**:
- **Fallada por posicionamiento**: Apprehend está disponible (no en
  cooldown) pero Mordekaiser está fuera del cono o Darius falla el ángulo.
  La secuencia termina en el paso 1 — cooldown gastado, sin control, sin
  daño.
- **No disponible por cooldown**: Darius ya usó Apprehend en un
  intercambio previo de esta misma fase y sigue en su cooldown de
  26–16 s (fila 13). La secuencia completa **no puede iniciarse** — a
  diferencia de la rama anterior, acá no hay ni siquiera un intento que
  gastar; el estado relevante no es "falló", es "no disponible".

Estas dos ramas son la razón por la que un futuro `CombatState` necesita
distinguir explícitamente disponibilidad de habilidad (`on_cooldown`) de
resultado de un intento (`missed`) — son estados de entrada distintos, no
el mismo hecho con otro nombre (ver `v1.7-sequence-state-design.md` §B.6).

**Respuesta de Mordekaiser disponible en esta fase**: si tiene Indestructible
puesta, puede activarla para absorber parte del daño — pero solo si ya
acumuló Potential Shield (recibió o infligió daño antes de este
intercambio). Si es el primer contacto de la partida, el acumulado puede
ser mínimo o nulo.

**Condiciones de éxito para Darius**: conectar Apprehend y el follow-up,
saliendo con Mordekaiser en 2 cargas de Hemorrhage.
**Condiciones de fallo**: cualquiera de las dos ramas de arriba.

**Información indeterminada**: si Mordekaiser realmente tiene Indestructible
puesta a nivel 2, cuánto Potential Shield acumulado tiene en ese momento.

### Niveles 3–5

**Habilidades disponibles**: kit completo salvo la definitiva, en ambos
lados.

**Secuencia extendida de Darius (generalización de la de nivel 2, con W):
`E → AA → W → Q exterior`**. Cuatro pasos, **tres** aplicaciones de
Hemorrhage — Apprehend (E) es control puro y no aplica ninguna (fila 15):
1. **E** — Apprehend conecta (misma precondición y las dos ramas de fallo
   de Nivel 2). Cero aplicaciones de Hemorrhage; habilita los pasos
   siguientes.
2. **AA** — auto-ataque durante la ventana de control. **Primera
   aplicación** de Hemorrhage (carga 1/5).
3. **W** — Crippling Strike potenciando el siguiente auto-ataque: aplica su
   empoderamiento y 90% de slow (el reset de temporizador sigue en
   confianza MEDIA, fila 12 — no se asume aquí con más certeza que en
   Nivel 1). Ese auto potenciado es la **segunda aplicación** (carga 2/5).
4. **Q exterior** — filo de Q, si su cooldown (9–5s, fila 7) ya se
   recuperó. **Tercera aplicación** (carga 3/5).

Con exactamente 3 cargas aplicadas en esta secuencia, Darius queda a
**dos** aplicaciones válidas de cinco — no a una — para alcanzar la
recompensa de 5 cargas (fila 5/6); el umbral se activa sin necesitar la
definitiva. Documentar una cuarta carga en esta misma apertura requeriría
un evento explícito adicional (p. ej. un segundo auto-ataque conectado
antes de Q) — no se asume sin declararlo.

**Esta secuencia parte de cero cargas de Hemorrhage previas**: no hereda
cargas de una fase anterior sin que el escenario lo declare explícitamente
como precondición (ver `v1.7-sequence-state-design.md` §B.5).

**Ramas de interrupción de Mordekaiser**: activar Indestructible si tiene
Potential Shield suficiente (reduce el valor de los pasos 2–4 sin
impedirlos); intentar su propio Death's Grasp para interrumpir el
posicionamiento (con la demora cualitativa de fila 30 — número no
confirmado); o simplemente recibir el combo si no tiene ninguna
herramienta disponible.

**Secuencia representativa de Mordekaiser (contra-ataque en el mismo
intercambio)**: Obliterate (idealmente a un único objetivo) + auto-ataques
aplicando Darkness Rise (activación a 3 golpes, fila 22).

**Condición de éxito para Darius**: completar la secuencia y llegar a la
recompensa de 5 cargas, aunque la definitiva siga sin desbloquear.
**Condición de éxito para Mordekaiser**: absorber suficiente con
Indestructible y devolver Obliterate+Darkness Rise antes de que Darius
llegue a las 5 cargas.
**Condición de fallo compartida**: cualquiera de los dos puede fallar su
propia secuencia en el primer paso y terminar solo habiendo gastado
cooldowns.

**Información indeterminada**: si el jugador ejecuta la secuencia completa
(fuera de alcance de esta V0), estado exacto de vida/escudo de cada uno al
momento del intercambio.

### Nivel 6a — All-in neutral (cero cargas previas, vida comparable)

Precondiciones declaradas: ambos llegan al intercambio sin cargas de
Hemorrhage activas sobre el otro, con vida comparable (ninguno en
desventaja de fase previa), y ambas definitivas disponibles.

**Secuencia de Darius**: repite la cadena de Niveles 3–5 (Apprehend →
auto → Crippling Strike → Q) desde cero, ahora con Noxian Guillotine
disponible como cierre si logra 3+ cargas de Hemorrhage en la propia
secuencia — el daño verdadero escala con esas cargas (fila 18).

**Dos aperturas posibles de Mordekaiser, independientes entre sí**:

- **R como iniciación directa (point-and-click)**: Mordekaiser castea
  Realm of Death sin ningún paso previo. R es unit-targeted (fila 32) —
  conecta salvo por los invalidadores específicos de fila 33; no hay una
  "ventana de esquive" genérica que Darius pueda aprovechar por diseño de
  la habilidad en sí. Esta apertura no depende de que Q o E hayan conectado
  antes — R es una acción independiente, siempre disponible si no está en
  cooldown.
- **Secuencia previa de Q/E/ataques, con R como cierre opcional**:
  Mordekaiser busca daño, control o activar Darkness Rise primero
  (Obliterate, Death's Grasp, auto-ataques) y decide después si castea R.
  **Fallar Q o E en esta apertura no es una precondición estructural que
  impida intentar R después** — son acciones independientes; solo cambia
  el estado con el que Mordekaiser llega al intento de R (p. ej. sin el
  daño de Q, o sin haber activado Darkness Rise todavía).

**Darius puede lanzar su propio Noxian Guillotine mientras está dentro del
Realm of Death de Mordekaiser** (fila 37) — no solo antes de entrar o
después de salir; el Realm aísla el duelo pero no deshabilita las
habilidades entre los dos combatientes.

**Condiciones de éxito para Darius**: llegar a 3+ cargas y conectar R —ya
sea antes de que Mordekaiser inicie su propio R, mientras está dentro del
Realm, o al salir de él.
**Condiciones de éxito para Mordekaiser**: conectar su R (por cualquiera de
las dos aperturas) antes de que Darius acumule 5 cargas, capturando el
robo de estadísticas.
**Condiciones de fallo**: Darius gasta R sin cargas suficientes (pierde la
mayor parte del bono de daño verdadero); Mordekaiser gasta R sin haber
generado ninguna ventaja previa y sin invalidador en contra de Darius
presente, sin haber podido evitar que Darius llegue a 5 cargas.

**Información indeterminada**: quién actúa primero (depende de posición y
del jugador, fuera de alcance).

### Nivel 6b — All-in precondicionado (estado previo declarado)

**Declaración explícita de continuidad** (requisito de
`v1.7-sequence-state-design.md` §B.5 para que un escenario pueda partir de
estado distinto de cero): este escenario se declara **continuación directa
de un intercambio previo dentro de la misma fase (Niveles 3–5)**, no un
escenario nuevo que hereda estado por inferencia. El `CombatState` de
salida de ese intercambio previo es, por esta declaración, el `CombatState`
de entrada de 6b — nunca ocurre por defecto entre dos escenarios sin esta
declaración.

A diferencia de 6a, este escenario declara explícitamente un estado de
entrada distinto de cero, como ejemplo de instanciación (no como el único
estado previo posible). Estado inicial completo — todo lo que el checklist
de §5 marca como "declarado" para este escenario aparece aquí, y solo eso:

- **Cargas**: Darius con 3 cargas de Hemorrhage ya aplicadas sobre
  Mordekaiser, de un intercambio previo en esta misma fase.
- **Banda de vida**: Darius en banda **alta** (no completa; gastó algo de
  vida en el intercambio previo); Mordekaiser en banda **parcial**.
- **Recurso de Darius (maná)**: banda **parcial** — gastó maná en Q/E
  durante el intercambio previo, no se recuperó del todo.
- **Reserva de Mordekaiser (Potential Shield)**: banda **alta** — acumuló
  daño dado/recibido en el intercambio previo, sin haberlo consumido
  todavía.
- **Disponibilidad de habilidades**: Apprehend de Darius **en cooldown**
  (se usó en el intercambio previo, no se recuperó a tiempo para el
  all-in); Death's Grasp de Mordekaiser **disponible**. Ambas
  definitivas disponibles (precondición del escenario 6, igual que 6a).
- **Distancia/contacto**: `melee_contact` para las acciones de rango de
  auto-ataque (175, fila 1/20) de ambos al comenzar el escenario
  (continuación directa del intercambio previo, sin que ninguno se haya
  retirado); `within_ability_range` para Death's Grasp (rango 700, fila
  28) y Realm of Death (rango 650, fila 31) de Mordekaiser desde esa misma
  posición — la banda se declara por acción, no una sola vez para todo el
  escenario (ver `v1.7-sequence-state-design.md` §B.2).
- **Oleada**: `pushing_toward_enemy` desde el `CombatState` de Darius
  (equivalente a `pushing_toward_self` desde el de Mordekaiser) — la
  oleada avanza hacia el lado de Mordekaiser, heredada del intercambio
  previo (ver `v1.7-sequence-state-design.md` §B.2 para la nomenclatura de
  dirección de oleada).
- **Aislamiento del objetivo**: contestado — no hay minions entre ambos
  que interrumpan el contacto directo, pero tampoco una zona que aísle a
  un tercero (no aplica en un 1v1 puro).

Ningún dato fuera de esta lista se declara para este escenario — si el
checklist de §5 marcara "declarado" algo que no aparece explícitamente
acá, sería un error a corregir, no una omisión aceptable.

Con este estado declarado, la secuencia de Darius no necesita reconstruir
las 3 cargas — está a **dos** aplicaciones válidas de cinco (no una) antes
de siquiera castear R, y su Noxian Guillotine, si conecta, ya parte de una
base de daño verdadero mayor que en 6a. La secuencia de Mordekaiser, en
cambio, no depende de que Darius tenga o no su propio control disponible:
Apprehend es una herramienta de **Darius**, y que esté en cooldown limita
solo las opciones de Darius, no las de Mordekaiser — Mordekaiser puede
igualmente abrir con Death's Grasp (disponible) o con Realm of Death
directo, como en las dos aperturas de 6a. Lo que sí cambia respecto al
caso neutral es que el Potential Shield alto de Mordekaiser significa que
Indestructible puede absorber una porción mayor del burst entrante que en
6a.

**Condiciones de éxito/fallo**: las mismas categorías que 6a, pero
evaluadas contra el estado ya declarado, no contra cero — ninguna de las
dos declara un ganador; el punto de este escenario es mostrar que el
mismo par de secuencias produce distinta distancia a cada umbral según el
estado de entrada, que es exactamente lo que un `CombatState` con estado
previo debe poder representar.

**Información indeterminada**: exactamente qué llevó a ese estado previo
(depende de la partida real; el escenario lo toma como dato ya declarado,
no lo deriva).

---

## 5. Checklist de escenarios mínimos

| # | Escenario | Dónde vive | Estado |
|---|---|---|---|
| 1 | Nivel 1, Darius W vs. Mordekaiser Q, oleada presente, ambos full HP | §4, Nivel 1, Rama D | Cubierto |
| 2 | Nivel 1, Darius Q vs. Mordekaiser Q, filo/mango e impacto aislado/no aislado | §4, Nivel 1, Rama E | Cubierto |
| 3 | Niveles 2–3, intercambio corto con habilidad clave fallada/gastada/no disponible | §4, Nivel 2, las dos ramas de fallo | Cubierto |
| 4 | Niveles 3–5, intercambio extendido desde cero cargas | §4, Niveles 3–5 | Cubierto |
| 5 | Nivel 6, all-in neutral desde cero cargas, vida comparable, ambas definitivas disponibles | §4, Nivel 6a | Cubierto |
| 6 | Nivel 6, all-in precondicionado (banda de vida, cargas, recurso de Darius, Potential Shield de Mordekaiser, disponibilidad de habilidades, distancia/contacto, oleada y aislamiento, todos declarados explícitamente) | §4, Nivel 6b | Cubierto — los 8 datos listados aparecen expresamente en el estado inicial del escenario |

Ninguno de los seis afirma un ganador: cada uno describe qué cadena puede
ejecutarse, qué condición persigue cada lado y qué dato falta.

---

## 6. Síntesis para el diseño

1. Las relaciones causales ya modeladas en el KB (quién aplica qué, quién
   amplifica qué) son estructuralmente correctas — esta investigación no
   encontró ninguna dirección causal invertida.
2. La brecha real es de **secuencia y estado**, no de vocabulario de
   efectos: casi todo lo que falta (duración, demora de cast, consumo de
   un recurso acumulado, precondición de acierto) es "cuándo y bajo qué
   condición se activa un efecto ya conocido", no un efecto nuevo.
3. La transferencia de vida/estadísticas de Realm of Death se modela
   **siempre** como un único grupo causal — se confirme o no, en el
   futuro, un componente de curación separado del robo de stats. Ver
   `v1.7-sequence-state-design.md` §A.2 y §J.
4. Realm of Death es point-and-click: no lleva una condición genérica de
   "acierto" ni una "ventana de reacción" — solo los invalidadores
   específicos y respaldados de la fila 33 de §2. Ver
   `v1.7-sequence-state-design.md` §B.4.
