# Formato de benchmark externo — propuesta (no implementada)

Objetivo E del diseño v1.7. Un almacén de datos observacionales externos
(winrate, gold/CS/XP diff temprano, muestra), **separado del runtime de
razonamiento**, versionado por parche/rol/rango. Sirve para contrastar la
conclusión del motor contra la realidad agregada — nunca para alimentarla.

## Por qué separado, no una tabla más del KB

`knowledge/champions/*.yaml` es conocimiento **mecánico** (qué hace un kit),
validado por `knowledge/schema.py` y consumido por `RuleEngine`. Un
benchmark es conocimiento **empírico** (qué pasó, en agregado, en partidas
reales) — otra `Provenance` conceptual, más externa todavía que
`EDITORIAL_PRIOR`: es un dato de terceros con su propia metodología, sesgo
de muestreo y ventana temporal. Mezclarlo en el mismo árbol invitaría a que
algún día una regla lo lea "por comodidad" — el resultado exacto que v1.6.1
pasó dos rondas corrigiendo (un prior con peso, por chico que sea, termina
decidiendo el veredicto). La separación de directorio y de loader es la
garantía estructural, no una convención de nombres.

## Ubicación propuesta

```
knowledge/
├── champions/*.yaml          # mecánico — SIN CAMBIOS
└── ...

benchmarks/                    # NUEVO, top-level, fuera de knowledge/
└── matchups/
    └── darius__mordekaiser.yaml
```

`benchmarks/` no lo toca `knowledge/loader.py`. Un módulo aparte
(`benchmarks/loader.py`, a diseñar en el hito que lo implemente) lo lee para
un reporte/CLI de comparación, nunca para `RuleEngine.build_trace`.

## Esquema (un archivo por par candidato/enemigo, ambas direcciones)

Campos por entrada, con su unidad:

| Campo | Unidad / dominio | Obligatorio |
|---|---|---|
| `source` | identificador corto de la fuente (`mobalytics`, `ugg`, `lolalytics`, ...) | sí |
| `source_url` | URL completa consultada | sí |
| `retrieved_at` | fecha ISO de la consulta | sí |
| `patch` | tal como lo declara la fuente, sin normalizar | sí |
| `rank_bracket` | banda de rango declarada por la fuente, o `null` | no |
| `sample_size` | número de partidas, o `null` | no |
| `observed_direction` | `favors_candidate` \| `favors_enemy` \| `even` | sí |
| `win_rate_raw` | fracción 0–1, tal como la reporta la fuente | sí |
| `win_rate_normalized` | fracción 0–1, solo si la fuente publica su propia normalización; si no, `null` | no |
| `gold_diff_at_15` | oro, diferencia del candidato menos el enemigo a los 15:00 de juego; `null` si no está disponible | no |
| `cs_diff_at_15` | creep score (unidades de last-hit), diferencia del candidato menos el enemigo a los 15:00; `null` si no está disponible | no |
| `xp_diff_at_15` | puntos de experiencia, diferencia del candidato menos el enemigo a los 15:00; `null` si no está disponible | no |
| `normalized_delta_pp` | puntos porcentuales por encima/debajo de lo "esperado" según la metodología propia de la fuente; **solo** si la fuente publica esa normalización, nunca calculado por este proyecto; `null` si no aplica | no |
| `uncertainty_note` | texto libre: limitaciones de procedencia, metodología no auditada, etc. | sí |

`cs_diff_at_15` y `xp_diff_at_15` son los nombres canónicos (siguen el
mismo patrón que `gold_diff_at_15`) — cualquier fuente futura que reporte
"CSD@15"/"XPD@15" con otro nombre se mapea a estos dos campos, no se
agregan alias nuevos.

```yaml
schema_version: 1
candidate_id: darius
enemy_id: mordekaiser
role: top
entries:
  - source: mobalytics
    source_url: "https://mobalytics.gg/lol/champions/darius/counters/top/vs-mordekaiser"
    retrieved_at: "2026-09-08"
    patch: "26.17"
    rank_bracket: "emerald_plus"
    sample_size: 4314
    observed_direction: favors_candidate
    win_rate_raw: 0.532
    win_rate_normalized: null
    gold_diff_at_15: null
    cs_diff_at_15: null
    xp_diff_at_15: null
    normalized_delta_pp: null
    uncertainty_note: >
      Metodología de agregación de Mobalytics no verificada por esta
      investigación; no se leyó la página completa (bloqueo de red de la
      sesión que la generó).
  - source: lolalytics
    source_url: "https://lolalytics.com/lol/darius/vs/mordekaiser/build/"
    retrieved_at: "2026-09-08"
    patch: "26.17"
    rank_bracket: null
    sample_size: null
    observed_direction: favors_candidate
    win_rate_raw: 0.5446
    win_rate_normalized: null
    gold_diff_at_15: null
    cs_diff_at_15: null
    xp_diff_at_15: null
    normalized_delta_pp: null
    uncertainty_note: "Fragmento de búsqueda, no página completa."
  - source: mobalytics
    source_url: "https://mobalytics.gg/lol/champions/darius/counters/top/vs-mordekaiser"
    retrieved_at: "2026-09-09"
    patch: "26.17"          # la página muestra "26.17" en el título y "16.17" en filtros/texto — mismo parche
    rank_bracket: "emerald_plus"
    sample_size: 6149
    observed_direction: favors_candidate
    win_rate_raw: 0.527
    win_rate_normalized: null
    gold_diff_at_15: 260
    cs_diff_at_15: 8.5
    xp_diff_at_15: -13.6
    normalized_delta_pp: 2.7
    uncertainty_note: >
      Recuperado vía paquete de evidencia auditable del usuario
      (lol_matchup_source_pack_26.17_2026-09-09), no por acceso directo de
      esta sesión (egress bloqueado). Hash del paquete verificado; el
      contenido de la página en sí no fue releído en vivo por este agente.
  - source: ugg
    source_url: "https://u.gg/lol/champions/mordekaiser/counter"
    retrieved_at: "2026-09-09"
    patch: "26.17"
    rank_bracket: null
    sample_size: 3362
    observed_direction: favors_candidate
    win_rate_raw: 0.5318
    win_rate_normalized: null
    gold_diff_at_15: 163
    cs_diff_at_15: null
    xp_diff_at_15: null
    normalized_delta_pp: null
    uncertainty_note: >
      Misma limitación de procedencia que la entrada de mobalytics de
      2026-09-09. La tabla de counters de Mordekaiser en la página lista a
      Darius como matchup favorable (dirección cualitativa, sin más detalle
      numérico capturado).
  - source: lolalytics
    source_url: "https://lolalytics.com/lol/darius/vs-mordekaiser/build/"
    retrieved_at: "2026-09-09"
    patch: "26.17"
    rank_bracket: null
    sample_size: 6228
    observed_direction: favors_candidate
    win_rate_raw: 0.5409
    win_rate_normalized: null
    gold_diff_at_15: null
    cs_diff_at_15: null
    xp_diff_at_15: null
    normalized_delta_pp: 3.91
    uncertainty_note: >
      Misma limitación de procedencia. `normalized_delta_pp` es la
      "diferencia normalizada publicada" que la propia página de LoLalytics
      calcula con su metodología (no auditada por este proyecto).
# agregado NO calculado por este esquema: cada entrada queda cruda,
# trazable a su fuente. Cualquier "consenso" es responsabilidad de quien
# LEE el archivo (el reporte de comparación), no un campo que el formato
# precalcule y que alguien pueda confundir con un hecho.
```

Dos snapshots a un día de diferencia con números distintos en la misma
página (p. ej. Mobalytics 53.2% el 08-09 vs. 52.7% el 09-09) no es una
contradicción a resolver — es el comportamiento esperado de un "snapshot
vivo", y es la razón por la que el esquema es `append-only` en primer
lugar (regla 4 más abajo).

**Correlación, no independencia**: las 5 entradas de arriba **no** son 5
observaciones independientes. Las dos de Mobalytics (08-09 y 09-09) son el
mismo proveedor, un día de diferencia — altamente correlacionadas entre sí,
no dos fuentes distintas. De las 3 fuentes reales (Mobalytics, U.GG,
LoLalytics), solo la de 08-09 (Mobalytics) y las dos de 09-09 (Mobalytics
otra vez, U.GG, LoLalytics) se solapan parcialmente en proveedor. El número
total de entradas guardadas (5, o el que sea con el tiempo) **no debe
describirse como "N fuentes independientes"** ni usarse para inflar la
confianza de una dirección — lo que cuenta como evidencia direccional es el
número de **proveedores distintos** que coinciden (acá: 3), no el número de
consultas guardadas. Cualquier reporte de comparación que lea este archivo
debe agrupar por `source` antes de contar cuántas fuentes coinciden en
dirección.

## Reglas de uso (para cuando exista el módulo que lo consuma)

1. **Nunca** se carga junto a `champions/*.yaml` en la misma pasada de
   `RuleEngine`. Ningún `Rule.evaluate()` puede importar este módulo — se
   verificaría con el mismo estilo de test AST que ya usa
   `test_no_hardcoded_pairs.py` (una regla general no puede importar
   `benchmarks.*`).
2. El reporte de comparación es de solo lectura: toma el
   `MatchupScore`/`Lean` del motor y las entradas del benchmark, y **marca
   desacuerdos** (p. ej. "el motor da leve ventaja a Mordekaiser; las
   fuentes externas agregadas dan ventaja a Darius") como texto
   informativo. No ajusta ningún peso, no genera un `RuleEffect`, no puede
   tocar `ReasoningTrace`.
3. Dos cosas distintas, una permitida y otra prohibida:
   - **Permitido**: un test de **integridad de snapshot** — verificar que
     una entrada ya guardada conserva exactamente los valores, la fuente,
     la fecha y el patch con los que se registró (que nadie la editó
     silenciosamente, que el schema sigue validando). Esto es un test
     sobre el propio archivo de benchmark, no sobre el motor.
   - **Prohibido**: cualquier test que obligue al **motor** (`RuleEngine`/
     `MatchupScore`) a reproducir el winrate, el ganador o el score de un
     benchmark externo — el equivalente del guardrail que ya existe en
     `tests/test_v161_final_invariants.py`. Un test del motor nunca puede
     importar `benchmarks.*` como oráculo de su resultado esperado.
4. Cada entrada es inmutable una vez guardada (append-only por
   `retrieved_at`): una consulta nueva agrega una entrada, no sobrescribe
   la anterior. Esto permite ver si el consenso cambió entre parches sin
   perder el historial, y es lo que le da sentido a coexistir con
   snapshots de fechas distintas (ver ejemplo arriba).
5. Campos ausentes (`null`) son honestos: mejor un campo vacío marcado que
   un valor inventado para completar la fila.
6. La lectura permitida de un benchmark es: (a) diagnóstico — si el motor
   contradice de forma estable varias fuentes, revisar hechos/secuencias;
   (b) validación de dirección y sensibilidad en un conjunto de matchups;
   (c) calibración futura, solo con dataset versionado y separación
   train/validation/test. Está prohibido: cambiar pesos hasta que un caso
   produzca un número esperado, convertir winrate en causalidad mecánica,
   o congelar en tests el ganador/score exacto de un matchup real.

## Qué falta para implementarlo (no es parte de esta ronda)

- El módulo `benchmarks/loader.py` + su validación (análogo a
  `knowledge/schema.py` pero mucho más chico: no hay vocabulario cerrado
  que cruzar, solo tipos y rangos).
- El comando de CLI o reporte que lee ambos lados y arma el contraste.
- Una lista cerrada o abierta de `source:` aceptables — con dos snapshots
  que ya traen conjuntos de fuentes parcialmente distintos (Mobalytics/
  LoLalytics/MetaBot vs. Mobalytics/U.GG/LoLalytics), decidir esto necesita
  más de un matchup, no solo Darius/Mordekaiser.
