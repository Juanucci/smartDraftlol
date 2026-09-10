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

**Precisión adicional sobre qué bytes existen realmente en el paquete**
(auditado de nuevo para esta ronda, `SOURCE_MANIFEST.json`): `meraki_darius`
y `meraki_mordekaiser` — citados en buena parte de las filas MEDIA de §2 —
son entradas `type: community_processed_mechanics` con **solo una URL**
(`cdn.merakianalytics.com/...`), sin `local_file` ni hash. El paquete nunca
incluyó los bytes de Meraki; lo que cito como "`meraki_*`, MEDIA" es la
paráfrasis que el propio paquete (`mechanics_facts.yaml`/
`VERIFIED_FINDINGS.md`) hace de esa fuente, no un byte que yo haya podido
inspeccionar. Lo mismo aplica a cada `riot_patch_25_XX`/`riot_patch_26_XX`:
son URLs de notas de parche, nunca texto espejado. Esto no cambia ningún
techo de confianza ya asignado (MEDIA ya era el techo correcto para Tier 2
y para URLs no releídas) — se deja explícito acá porque esta ronda pidió
releer bytes concretos de Realm of Death y la respuesta honesta es que, más
allá del JSON crudo de Data Dragon (Tier 1, sí bundleado y hash-verificado),
**no existen más bytes que releer** en este paquete.

---

## 2. Hechos mecánicos vigentes

| # | Campeón | Dato | Valor vigente | `source_id` | Confianza | Categoría |
|---|---|---|---|---|---|---|
| 1 | Darius | Stats base (HP/AD/Armor/MR/MS/Rango de ataque) | 652 / 64 / 37 / 32 / 340 / 175 | `riot_ddragon_darius` | ALTA-cond. | FACT |
| 2 | Darius | Recurso | Maná, base 263 (+58/nivel) | `riot_ddragon_darius` | ALTA-cond. | FACT |
| 3 | Darius | Pasiva (Hemorrhage): duración y stacks | 5 s por aplicación, hasta 5 cargas | `riot_ddragon_darius` (tooltip) | ALTA-cond. | FACT |
| 4 | Darius | Hemorrhage: ¿se refresca o acumula duración? | Cada nueva aplicación **refresca** la ventana de 5 s de todo el conjunto de cargas activas — no hay evidencia de que cada carga decaiga con un temporizador propio e independiente. No se modela un array de N timers; el "refresco" es un **evento** de aplicación durante una ventana ya `active`, no un tercer valor de `window` (que solo distingue `active`/`expired`; ver `v1.7-sequence-state-design.md` §B.2, `StackState`) | `meraki_darius` | MEDIA | DERIVATION |
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
| 35 | Mordekaiser | R: ¿hay además un componente de curación/transferencia de vida máxima separado del robo de stats, para el parche 26.17/16.17.1? | El JSON crudo de Data Dragon 16.17.1 (Tier 1, hash-verificado) para `MordekaiserR` tiene `effect`/`effectBurn`/`vars` todos vacíos o en cero, y su tooltip **solo** dice "stealing X% of their core stats" — cero campos relacionados con curación o vida máxima. El paquete no incluye ningún byte de `meraki_mordekaiser` (solo una URL, ver §1) ni el texto de `riot_patch_26_15` (también solo URL) que sostendrían la hipótesis de un componente de vida — la afirmación de que existe viene únicamente de la paráfrasis del propio paquete (`VERIFIED_FINDINGS.md`/`mechanics_facts.yaml`), no de una fuente releíble. **Dato exacto que falta para confirmar o descartar**: los bytes reales de `meraki_mordekaiser` o el texto de `riot_patch_26_15`/`26.17` — ninguno de los dos está en este paquete | Tooltip crudo Data Dragon 16.17.1 (sin heal, campos vacíos); paráfrasis del paquete sin bytes verificables (posible heal) | ALTA-cond. (que el tooltip/vars de 16.17.1 no lo contienen) / BAJA (la hipótesis del heal, al no tener ni URL-releída ni bytes Tier 2 reales detrás — se baja de MEDIA a BAJA tras esta auditoría) | HYPOTHESIS, no FACT — permanece agrupada bajo la regla de modelado de §4 (Nivel 6) mientras falten esos bytes |
| 36 | Ambos | Penetración de armadura (Darius) vs. penetración mágica (Mordekaiser) | Fortalezas paralelas contra defensas distintas — no se cancelan ni se comparan sin valores por nivel, resistencias del objetivo y contexto de daño real. Observación estructural de **aporte cero**, pendiente de calibración | `riot_ddragon_darius` (armor pen); `meraki_mordekaiser` (magic pen) | ALTA-cond. (que el % existe) | Guardrail de diseño, no causa puntuable |
| 37 | Darius | R: ¿puede lanzarse dentro de Realm of Death de Mordekaiser? | Sí — el Realm aísla el duelo del resto de la partida, pero **no deshabilita las habilidades entre los dos combatientes**. Noxian Guillotine no está limitado a lanzarse solo antes de entrar o después de salir del Realm | Texto del paquete (síntesis, sin `source_id` numérico) | MEDIA | FACT |
| 38 | Darius | Hemorrhage: daño por carga | `13–30 físico según nivel + 30% AD adicional` por cada carga, a lo largo de su ventana de 5 s (la fuente no desglosa si es el total de la ventana o una tasa por tick — no se asume ninguna de las dos sin más detalle) | `meraki_darius` | MEDIA | DERIVATION — magnitud registrada como fuente de daño durante el trade, no se calcula daño final tras resistencias (fuera de alcance) |

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
- ¿Existe un componente de curación/transferencia de vida máxima en Realm
  of Death, distinto del robo de stats, para 26.17/16.17.1? (fila 35) —
  releídos los bytes crudos de Data Dragon (única fuente con bytes reales
  en el paquete), no hay ningún campo relacionado con curación en `R`; la
  hipótesis depende de dos fuentes que el paquete solo cita por URL
  (`meraki_mordekaiser`, `riot_patch_26_15`) y nunca incluyó como bytes.
  Confianza bajada de MEDIA a BAJA tras esta auditoría. La regla de
  modelado (§4, Nivel 6) no depende de resolver esto: se modela como un
  único grupo causal se confirme o no.
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

**Rama D — Darius abre con W, oleada presente, ambos full HP** (estado
inicial declarado explícitamente, no implícito): `health_band = full` para
ambos actores, `wave_state = {state: present_neutral}` en `shared` — sin
esto declarado, esta rama no podría marcarse "Cubierto" en el checklist de
§5. W es un empoderamiento del **propio próximo
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

Ambas ramas de Darius de esta fase parten de **cero cargas de Hemorrhage
previas**: no heredan cargas de una fase anterior sin que el escenario lo
declare explícitamente como precondición (ver
`v1.7-sequence-state-design.md` §B.5).

**Rama corta — `E → AA → W-AA → Q exterior`** (generalización de la
secuencia de nivel 2, con W agregado). Cuatro pasos, **exactamente tres**
aplicaciones de Hemorrhage — Apprehend (E) es control puro y no aplica
ninguna (fila 15):
1. **E** — Apprehend conecta (misma precondición y las dos ramas de fallo
   de Nivel 2). Cero aplicaciones de Hemorrhage; habilita los pasos
   siguientes.
2. **AA** — auto-ataque durante la ventana de control. **Primera
   aplicación** de Hemorrhage (carga 1/5) — cada carga es también una
   fuente de daño físico continuo durante el intercambio, no solo un
   contador (fila 38: 13–30 según nivel + 30% AD adicional por carga,
   MEDIA).
3. **W-AA** — Crippling Strike potenciando el siguiente auto-ataque: aplica
   su empoderamiento y 90% de slow (el reset de temporizador sigue en
   confianza MEDIA, fila 12 — no se asume aquí con más certeza que en
   Nivel 1). Ese auto potenciado es la **segunda aplicación** (carga 2/5).
4. **Q exterior** — filo de Q, si su cooldown (9–5s, fila 7) ya se
   recuperó. **Tercera aplicación** (carga 3/5).

Con exactamente 3 cargas, Darius queda a **dos** aplicaciones válidas de
cinco — no a una — para alcanzar la recompensa de 5 cargas (fila 5/6). Esta
rama **no** llega a activar Noxian Might; se detiene acá.

**Rama extendida — la rama corta más dos aplicaciones válidas explícitas
adicionales, hasta 5 cargas, activando Noxian Might a mitad de la
secuencia**. No es "la misma jugada un poco más larga": es un payoff
mecánicamente distinto, con una recompensa que se activa DURANTE la cadena
y modifica los pasos que vienen después — no se trata como equivalente a
la rama corta.
5. **AA** (cuarta aplicación, carga 4/5) — un auto-ataque adicional,
   declarado explícitamente como evento de esta rama (no asumido por
   default): requiere que Mordekaiser siga en `melee_contact` después del
   paso 4, sin haberse retirado.
6. **AA** (quinta aplicación, carga 5/5) — otro auto-ataque adicional, con
   la misma precondición explícita de contacto sostenido. Este quinto
   auto-ataque en sí **no** lleva el bono de Noxian Might — inflige su
   daño normal y, **al conectar**, cruza el umbral de 5 cargas:
   `reward_state` pasa de `inactive` a `active` (Noxian Might, bono de AD
   por 5 s, fila 5/6) recién en ese instante, como consecuencia de esta
   aplicación, no como una propiedad que ya tenía.
7. **Acciones posteriores, ya con Noxian Might activo**: cualquier
   auto-ataque adicional que Darius conecte **después** del paso 6, durante
   esos 5 s de bono, inflige más daño que uno idéntico en los pasos 2–6 —
   ninguno de los pasos 1–6 se beneficia de Noxian Might, solo lo que
   ocurre después de que `reward_state` pasó a `active`. A este nivel (3–5)
   Noxian Guillotine
   **no está disponible todavía** (R se desbloquea recién en nivel 6) —
   la posibilidad de cerrar con R, ya con Noxian Might activo y no solo
   con 3 cargas, se retoma explícitamente en Nivel 6a más abajo, como una
   rama distinta de la que abre R con solo 3 cargas.

**Ramas de interrupción de Mordekaiser**: activar Indestructible si tiene
Potential Shield suficiente (reduce el valor de los pasos 2–4 sin
impedirlos); intentar su propio Death's Grasp para interrumpir el
posicionamiento (con la demora cualitativa de fila 30 — número no
confirmado); o simplemente recibir el combo si no tiene ninguna
herramienta disponible.

**Secuencia representativa de Mordekaiser (contra-ataque en el mismo
intercambio)**: Obliterate (idealmente a un único objetivo) + auto-ataques
aplicando Darkness Rise (activación a 3 golpes, fila 22).

**Condición de éxito para Darius**: completar la rama corta (3 cargas, dos
aplicaciones de distancia de la recompensa) o la rama extendida (5 cargas,
Noxian Might activo) — son dos resultados distintos, no el mismo payoff en
dos velocidades; ninguno requiere la definitiva, que a este nivel sigue sin
desbloquear.
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
Hemorrhage activas sobre el otro (`stacks[hemorrhage]` en ambos en
`count: 0`, no `unknown` — es un cero conocido, ver
`v1.7-sequence-state-design.md` §B.2), con vida comparable (`health_band:
high` para ambos — ninguno en desventaja de fase previa), y ambas
definitivas disponibles.

**Dos ramas de Darius, con payoffs distintos — no la misma jugada en dos
velocidades**:
- **R con 3 cargas**: la rama corta de Niveles 3–5
  (`E → AA → W-AA → Q exterior`) deja a Mordekaiser en 3 cargas de
  Hemorrhage; Darius cierra con Noxian Guillotine ahí mismo. El daño
  verdadero de R escala con esas 3 cargas (fila 18) — un payoff concreto,
  menor que el de la rama siguiente.
- **R después de Noxian Might**: la rama extendida de Niveles 3–5 (llega a
  5 cargas — ninguno de los golpes que construyen esas 5 cargas lleva el
  bono, `reward_state` sigue `inactive` hasta que la quinta conecta — y
  recién ahí `reward_state` pasa a `active`) y **entonces** cierra con R —
  el daño verdadero escala con 5 cargas en vez de 3, y solo los
  auto-ataques posteriores a la activación (no los que la construyeron)
  llevan el bono de AD de Noxian Might. Este es un resultado mecánicamente
  distinto del anterior, no una versión "mejorada" del mismo número.

**Tres aperturas posibles de Mordekaiser, con profundidad comparable a las
de Darius**:
- **R como iniciación directa (point-and-click)**: Mordekaiser castea
  Realm of Death sin ningún paso previo. R es unit-targeted (fila 32) —
  conecta salvo por los invalidadores específicos de fila 33; no hay una
  "ventana de esquive" genérica que Darius pueda aprovechar por diseño de
  la habilidad en sí. No depende de que Q o E hayan conectado antes.
- **Secuencia previa de Q/E/auto-ataques, con R como cierre opcional**:
  Mordekaiser busca daño (Obliterate, idealmente aislado — fila 24),
  control o activar Darkness Rise (3 golpes, fila 22) primero, y decide
  después si castea R. **Fallar Q o E en esta apertura no es una
  precondición estructural que impida intentar R después** — son acciones
  independientes; solo cambia el estado con el que Mordekaiser llega al
  intento de R.
- **W según el estado de Potential Shield, combinada con cualquiera de las
  dos anteriores**: si `reserves[potential_shield]` está en banda
  `near_max` (acumulado en la propia secuencia o heredado si el escenario
  lo declara), Indestructible puede convertir una porción real del burst
  entrante en escudo o, con el recast, en curación (fila 27); en banda
  `none`/`partial`, la misma activación absorbe/cura mucho menos — es la
  misma habilidad con un resultado distinto según el estado declarado, no
  una magnitud fija.

**Continuar dentro del Realm no es un callejón sin salida para ninguno de
los dos**: ambos siguen pudiendo actuar dentro de él. Darius puede seguir
aplicando Hemorrhage (auto-ataques, Q) y lanzar su propio Noxian Guillotine
estando dentro del Realm (fila 37) — no solo antes de entrar o después de
salir. Mordekaiser puede seguir atacando para sostener o completar
Darkness Rise. El Realm no pausa ninguna de las dos secuencias.

**Cast, transformación, geometría y resultado — cuatro cosas distintas, no
una sola "condición de éxito"** (para la apertura de R de Mordekaiser):
1. **El cast se completa** — point-and-click, `Support.STRUCTURAL` salvo
   invalidador presente (fila 33).
2. **Se aplica la transformación de estadísticas** — Mordekaiser roba 10%
   de las estadísticas centrales de Darius por 7s (fila 34); esto por sí
   solo no termina el intercambio.
3. **El aislamiento modifica las condiciones del intercambio** — dentro del
   Realm ninguno recibe ayuda externa (irrelevante en un 1v1 puro) y el
   espacio se restringe, lo que puede favorecer a quien sostenga mejor el
   contacto — sin especificar de antemano a cuál de los dos.
4. **El resultado del duelo sigue dependiente del estado y de las
   secuencias posteriores** — R **no** elimina las cargas de Hemorrhage ya
   aplicadas, **no** impide que Darius aplique más, y **no** deshabilita
   Noxian Guillotine. Que Mordekaiser complete su cast antes de que Darius
   llegue a 5 cargas es el paso 1 de su condición de éxito, no la condición
   completa — el resto depende de qué pase dentro del Realm.

**Condiciones de fallo**: Darius gasta R con solo 3 cargas cuando la
secuencia extendida seguía siendo alcanzable (pierde parte del bono de
daño verdadero disponible, aunque sigue siendo una rama válida, no un
error); Mordekaiser falla el cast de R (invalidador presente, fila 33) y
queda expuesto sin su herramienta principal.

**Información indeterminada**: quién actúa primero (depende de posición y
del jugador, fuera de alcance); si Mordekaiser ejecuta la apertura con
Q/E previo o R directo (decisión del jugador, ambas ramas válidas).

### Nivel 6b — All-in precondicionado (estado previo declarado)

**Simplificación de continuidad** (requisito de
`v1.7-sequence-state-design.md` §B.5 para que un escenario pueda partir de
estado distinto de cero, sin recurrir a un evento artificial de subida de
nivel): ambos campeones **ya están en nivel 6** desde el inicio de este
escenario — no hay ninguna subida de nivel a mitad del intercambio, ni
remate de minion que la dispare. El escenario declara un **checkpoint**
explícito como estado de entrada: la rama corta de Niveles 3–5
(`E → AA → W-AA → Q exterior`) ya se ejecutó y dejó 3 cargas de Hemorrhage
sobre Mordekaiser, con su ventana todavía `active` (no `expired`) en el
instante en que arranca este escenario — y el intercambio **continúa**
desde ahí, ya con las definitivas disponibles porque ambos son nivel 6.
Esto no es "hereda de una fase anterior" en el sentido prohibido por §B.5
(dos escenarios distintos donde uno copia el final del otro): es un único
escenario que **declara su propio estado de entrada** como un checkpoint
posterior a una rama corta ya conocida, en vez de empezar todo en cero — la
declaración de continuidad es sobre esa rama corta como parte del mismo
escenario, no una inferencia entre dos escenarios separados.

Quedan así tres momentos separados, no mezclados:
- La **rama corta** (Niveles 3–5) que produce el checkpoint: 3 cargas,
  ventana activa — ya descripta en esa sección, no repetida acá salvo como
  precondición de entrada.
- El **checkpoint declarado** de este escenario 6b: el estado inicial
  completo, listado abajo.
- La **continuación del intercambio** desde ese checkpoint (ver el cierre
  de esta sección) — que puede o no llegar a una rama extendida de 5
  cargas o a eventos posteriores a una recompensa, sin mezclarse con los
  3 cargas del checkpoint.

A diferencia de 6a, este escenario declara explícitamente un estado de
entrada distinto de cero, como ejemplo de instanciación (no como el único
estado previo posible). Estado inicial completo — todo lo que el checklist
de §5 marca como "declarado" para este escenario aparece aquí, y solo eso:

Taxonomía usada abajo: exactamente la de
`v1.7-sequence-state-design.md` §B.2 — `health_band` ∈
{`full`,`high`,`low`}, `reserves` ∈ {`none`,`partial`,`near_max`}, sin
sinónimos.

- **Cargas**: `stacks[hemorrhage] = {count: 3, window: active}` sobre
  Mordekaiser (Darius es quien las aplicó) — de la rama corta del
  intercambio previo dentro de este mismo escenario continuo (no de "otra
  fase"; ver la declaración de continuidad arriba).
- **Banda de vida**: Darius `high` (no completa; gastó algo de vida en el
  intercambio); Mordekaiser `low` (tomó más daño en ese mismo intercambio
  — de ahí la diferencia con Darius, ambos usando las mismas 3 bandas
  canónicas, no un cuarto término).
- **Recurso de Darius**: `resource.type = mana`, `resource.band = partial`
  — gastó maná en Q/E durante el intercambio, no se recuperó del todo.
- **Reserva de Mordekaiser**: `reserves[potential_shield] = near_max` —
  acumuló daño dado/recibido en el intercambio, sin haberlo consumido
  todavía.
- **Disponibilidad de habilidades**: Apprehend de Darius `on_cooldown` (se
  usó en el intercambio, no se recuperó a tiempo — sin
  `recovers_within_sequence` declarado para su slot, no se asume
  disponible de nuevo); Death's Grasp de Mordekaiser `ready`. Ambas
  definitivas `ready` (precondición del escenario 6, igual que 6a).
- **`ActionContext` por acción (`shared.action_contexts`)** — rango e
  aislamiento declarados por acción, no como un campo global (§B.2 de
  diseño):
  - Auto-ataque de Darius y de Mordekaiser (rango 175, fila 1/20):
    `range_status: in_range` — continuación directa del intercambio previo,
    sin que ninguno se haya retirado. `target_isolation: contested` (ver
    abajo).
  - Death's Grasp de Mordekaiser (rango 700, fila 28): `range_status:
    in_range` desde esa misma posición.
  - Realm of Death de Mordekaiser (rango 650, fila 31): `range_status:
    in_range` desde esa misma posición; `invalidators`: no declarados en
    este checkpoint (`unknown`) — a diferencia del baseline de 6a, este
    escenario no afirma "objetivo legal, contexto normal" por defecto.
  - Noxian Guillotine de Darius (rango 460, fila 17 — dato de §2 no listado
    antes en este escenario): `range_status: in_range`.
- **`target_isolation`** (mismo valor para las acciones de contacto
  directo de esta lista, declarado una sola vez, no por actor):
  `contested` — no hay minions entre ambos que interrumpan el contacto
  directo, pero tampoco una zona que aísle a un tercero (no aplica en un
  1v1 puro). Que la oleada esté presente y empujando (siguiente punto) no
  es lo que determina este valor — se declara independientemente, como
  exige el diseño (§B.2: "`wave_state` no determina `target_isolation`
  automáticamente").
- **`wave_state` (shared)**: `{state: pushing, pushing_toward: enemy}` —
  usando los mismos roles `candidate`/`enemy` del `CombatState` (Darius
  como candidato en este dossier): la oleada avanza hacia el lado de
  Mordekaiser, heredada del intercambio. Una sola copia compartida, no una
  declaración por actor que pudiera contradecirse. Cualitativo: no
  modifica `MatchupScore` por sí solo, no determina rango ni aislamiento
  (ya declarados arriba, independientemente).

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
directo, como en las aperturas de 6a. Lo que sí cambia respecto al caso
neutral es que el `reserves[potential_shield] = near_max` de Mordekaiser
significa que Indestructible puede absorber/curar una porción mayor del
burst entrante que en 6a (donde esa banda parte en `unknown` salvo que se
declare).

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
5. El estado de oleada (`wave_state`) es contexto cualitativo compartido:
   no modifica `MatchupScore` por sí solo, puede alimentar precondiciones e
   interpretación, y no determina por sí solo rango, aislamiento ni ganador
   de ninguna acción — cada uno de esos tres se declara en su propio
   `ActionContext` (§B.2 del diseño), nunca se infiere de la oleada.
6. Un trade no siempre produce un ganador inequívoco ni requiere una
   muerte: la evaluación de un resultado admite lecturas neutrales,
   condicionales o no resueltas además de favorecer a un lado — ver
   `v1.7-sequence-state-design.md` §B.8.
