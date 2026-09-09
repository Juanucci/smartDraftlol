# Formato de benchmark externo — propuesta (no implementada)

Objetivo E del diseño v1.7. Un almacén de datos observacionales externos
(winrate, gold/CS diff temprano, muestra), **separado del runtime de
razonamiento**, versionado por parche/rol/rango. Sirve para contrastar la
conclusión del motor contra la realidad agregada — nunca para alimentarla.

## Por qué separado, no una tabla más del KB

`knowledge/champions/*.yaml` es conocimiento **mecánico** (qué hace un kit),
validado por `knowledge/schema.py` y consumido por `RuleEngine`. Un
benchmark es conocimiento **empírico** (qué pasó, en agregado, en partidas
reales) — otra `Provenance` conceptual, más externa todavía que
`EDITORIAL_PRIOR`: no es ni siquiera una valoración de quien escribió el
YAML, es un dato de terceros con su propia metodología, sesgo de muestreo y
ventana temporal. Mezclarlo en el mismo árbol invitaría a que algún día una
regla lo lea "por comodidad" — el resultado exacto que v1.6.1 pasó dos
rondas corrigiendo (un prior con peso, por chico que sea, termina decidiendo
el veredicto). La separación de directorio y de loader es la garantía
estructural, no una convención de nombres.

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

## Esquema propuesto (un archivo por par candidato/enemigo, ambas direcciones)

```yaml
schema_version: 1
candidate_id: darius
enemy_id: mordekaiser
role: top
entries:
  - source: mobalytics
    source_url: "https://mobalytics.gg/lol/champions/darius/counters/top/vs-mordekaiser"
    retrieved_at: "2026-09-08"
    patch: "26.17"          # tal como lo declara la fuente; NO normalizado
    rank_bracket: "emerald_plus"
    sample_size: 4314
    observed_direction: favors_candidate   # favors_candidate | favors_enemy | even
    win_rate_raw: 0.532                    # tal como lo reporta la fuente
    win_rate_normalized: null              # si la fuente no publica metodología de normalización, null — no inventarla
    gold_diff_at_15: null                  # no disponible en esta consulta
    cs_diff_at_15: null
    uncertainty_note: >
      Metodología de agregación de Mobalytics no verificada por esta
      investigación; no se leyó la página completa (bloqueo de red de la
      sesión que la generó).
  - source: lolalytics
    source_url: "https://lolalytics.com/lol/darius/vs/mordekaiser/build/"
    retrieved_at: "2026-09-08"
    patch: "26.17"
    rank_bracket: null       # no confirmado en esta consulta
    sample_size: null
    observed_direction: favors_candidate
    win_rate_raw: 0.5446
    win_rate_normalized: null
    gold_diff_at_15: null
    cs_diff_at_15: null
    uncertainty_note: "Fragmento de búsqueda, no página completa."
# agregado NO calculado por este esquema: cada entrada queda cruda,
# trazable a su fuente. Cualquier "consenso" es responsabilidad de quien
# LEE el archivo (el reporte de comparación), no un campo que el formato
# precalcule y que alguien pueda confundir con un hecho.
```

## Reglas de uso (para cuando exista el módulo que lo consuma)

1. **Nunca** se carga junto a `champions/*.yaml` en la misma pasada de
   `RuleEngine`. Ningún `Rule.evaluate()` puede importar este módulo — se
   verificaría con el mismo estilo de test AST que ya usa
   `test_no_hardcoded_pairs.py` (una regla general no puede importar
   `benchmarks.*`).
2. El reporte de comparación es de solo lectura: toma el
   `MatchupScore`/`Lean` del motor y las entradas del benchmark, y **marca
   desacuerdos** (p. ej. "el motor da leve ventaja a Mordekaiser; 3 fuentes
   externas agregadas dan ventaja a Darius") como texto informativo. No
   ajusta ningún peso, no genera un `RuleEffect`, no puede tocar
   `ReasoningTrace`.
3. Ningún test de este benchmark puede congelar un ganador — el equivalente
   del guardrail que ya existe en `tests/test_v161_final_invariants.py`
   para los tests del motor. Un test legítimo sobre el benchmark verifica
   forma (que el archivo valide contra el schema, que cite fuente y fecha),
   no que "Darius gane".
4. Cada entrada es inmutable una vez guardada (append-only por
   `retrieved_at`): una consulta nueva agrega una entrada, no sobrescribe la
   anterior. Esto permite ver si el consenso cambió entre parches sin perder
   el historial.
5. `sample_size` y `rank_bracket` ausentes (`null`) son honestos: mejor un
   campo vacío marcado que un valor inventado para completar la fila.

## Qué falta para implementarlo (no es parte de esta ronda)

- El módulo `benchmarks/loader.py` + su validación (análogo a
  `knowledge/schema.py` pero mucho más chico: no hay vocabulario cerrado que
  cruzar, solo tipos y rangos).
- El comando de CLI o reporte que lee ambos lados y arma el contraste.
- Una decisión sobre qué fuentes se consideran aceptables como
  `source:` (lista cerrada o abierta) — para esta ronda, Mobalytics,
  LoLalytics y CounterStats aparecieron con metodologías propias no
  auditadas; no hay razón para preferir una sobre otra sin más
  investigación.
