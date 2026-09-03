# lol_reasoner — copiloto estratégico de LoL (V0 / prueba de concepto)

## Visión del proyecto

El objetivo final es un copiloto estratégico con IA para League of Legends que
**razone** sobre matchups, no que repita winrates. La idea central:

> Las estadísticas indican qué suele suceder. El sistema debe intentar
> entender **por qué** sucede y qué debería hacer el jugador con esa
> información.

El diseño final será híbrido: conocimiento estructurado de campeones, reglas
de interacción mecánica, datos estadísticos (cuando existan), perfil del
jugador y una capa de IA/LLM. Esta V0 no construye eso: construye y valida
el **motor de razonamiento** que sostendría todo lo demás.

## Alcance exacto de esta primera implementación

Esta entrega es el primer hito de la V0: validar el flujo completo del motor
con **dos campeones** (Darius y Mordekaiser), en ambas direcciones de
matchup, antes de cargar los ocho restantes (Garen, Jax, Fiora, Renekton,
Malphite, Ornn, Gwen, Kennen).

**Sí incluye:**
- Propiedades semánticas de los campeones (ejes, tags, tipo de daño).
- Efectos de habilidades e interacciones entre kits.
- Patrones de trade, ventanas de cooldown, fortalezas/vulnerabilidades.
- Cambios entre 4 fases de progresión: `early_lane`, `level_6`, `first_item`,
  `side_lane_late`.
- Exigencia de ejecución y condiciones que podrían invertir la conclusión.
- Ranking global y personal (ajustado por dominio del usuario), desglose por
  factor, confianza, razones/riesgos/condiciones/información faltante, todo
  trazable a una `ReasoningTrace`.
- CLI con salida humana y JSON.

**No incluye (fuera de alcance deliberado de esta V0):**
- Runas, builds, objetos específicos, summoner spells.
- Composiciones 5v5, meta actual, elo, integraciones de red.
- Recomendaciones dependientes de un parche concreto.
- Los otros 8 campeones (quedan para el siguiente hito, tras revisión).
- Interfaz gráfica, overlay, scraping, base de datos, cuentas, fine-tuning,
  RAG, agentes autónomos.

`first_item` es una **fase aproximada de progresión de poder**, no asume qué
objeto compró cada campeón. Cuando una conclusión dependería de un objeto
concreto, el motor lo señala explícitamente como información faltante (ver
`ITEMGAP` en la traza) en vez de inventar un timing.

### Sobre el parche y `knowledge_version`

**El conocimiento mecánico cargado no fue auditado contra ningún parche
concreto de League of Legends.** Es una lectura cualitativa propia, pensada
para poner a prueba la arquitectura del motor de razonamiento — no para
ofrecer una recomendación competitiva actualizada. `knowledge_version`
(`"0.1.0"`) es la versión **interna de esta base de datos**, no un número de
parche de LoL. La validación de kits contra fuentes actuales y el soporte de
parches quedan como una etapa posterior independiente (ver
`docs/backlog-v1.md`).

## Arquitectura

```
src/lol_reasoner/
├── domain/            # Entidades: Champion, MatchupQuery, Recommendation...
│   ├── enums.py        # Vocabulario cerrado: Axis, Tag, EffectKind, Phase, Factor...
│   ├── champion.py      # Champion, AbilityEffect, PowerSpike, DamageProfile
│   ├── query.py          # MatchupQuery (entrada)
│   └── result.py          # Recommendation, RecommendationSet, ReasonItem... (salida)
│
├── knowledge/         # Base de conocimiento estructurada
│   ├── champions/*.yaml  # Un YAML por campeón, comentado
│   ├── schema.py          # Validación manual (sin dependencias extra)
│   └── loader.py           # YAML -> Champion
│
├── reasoning/         # El motor de razonamiento
│   ├── context.py       # ReasoningContext (candidato, enemigo, fase)
│   ├── trace.py           # TraceEntry, ReasoningTrace — la evidencia
│   ├── engine.py            # RuleEngine: reglas -> TraceEntry
│   └── rules/
│       ├── base.py           # Rule, RuleEffect
│       ├── general.py          # Reglas generales (sin nombres de campeón)
│       └── specific.py           # Excepciones puntuales, justificadas y acotadas
│
├── scoring/           # GlobalScore, PersonalScore, Confidence
│   ├── weights.py        # Pesos centralizados (config/weights.yaml)
│   ├── global_score.py     # Traza -> score sin leer mastery
│   ├── personal_score.py     # GlobalScore + mastery -> PersonalScore
│   └── confidence.py           # Cobertura de categorías, contradicción, huecos
│
├── explain/narrator.py # Traza -> reasons/risks/conditions/missing_info
├── recommend.py         # Orquestación: MatchupQuery -> RecommendationSet
├── cli.py                 # CLI (texto humano y JSON)
└── config/weights.yaml      # Pesos de factores, fases y ajuste personal
```

### El principio que organiza todo: la `ReasoningTrace`

Ninguna razón, riesgo, condición o número de score aparece en la salida si no
nació de un `TraceEntry`. El flujo es siempre:

```
YAML → Champion → ReasoningContext (por fase)
     → Rule.evaluate() → RuleEffect (0..n)
     → RuleEngine → TraceEntry (append-only en ReasoningTrace)
     → scoring/ (lee la traza, nunca al revés)
     → explain/narrator.py (lee la traza, arma texto con el id de cada entrada)
     → CLI / JSON
```

`explain/narrator.py` no genera texto libre: cada `ReasonItem` que produce
lleva el `id` del `TraceEntry` exacto del que salió. Eso es lo que permite
verificar, mirando cualquier recomendación, qué hechos y qué reglas la
sustentan (ver `tests/test_trace_integrity.py`).

### Reglas generales vs. excepciones específicas

Las reglas de `reasoning/rules/general.py` **no pueden mencionar un campeón
por nombre**: solo leen ejes (`axes`), tags cualitativos (`tags`), tipo de
daño (`damage_profile`) y efectos de habilidad (`kind`, `counters`,
`countered_by`, `cooldown_class`). Esto es lo que impide que el motor
degenere en una tabla de 90 resultados hardcodeados: `tests/test_no_hardcoded_pairs.py`
escanea el AST del archivo y falla si aparece un literal con el id o nombre
de un campeón, o una comparación contra `.id`.

`reasoning/rules/specific.py` permite un número acotado (≤10, hoy hay 2) de
excepciones entre **habilidades concretas** de dos campeones concretos,
cuando existe una interacción real que las reglas genéricas no pueden
capturar (p. ej.: el daño verdadero de *Noxian Guillotine* ignora por
definición el escudo de *Indestructible*, aunque el tag general
`defensive_stance` sugeriría que sí lo mitiga). Cada excepción exige una
`justification` explicando por qué el cruce genérico no alcanza, y una
`condition` bajo la cual se sostiene.

### GlobalScore vs. PersonalScore

- **GlobalScore**: suma, por fase y por factor, los deltas de la traza
  (`PRO`=+1, `CONTRA`=-1, `CONDITIONAL`=0 — una ventaja puramente condicional
  no debe inflar el número, solo aparecer como condición textual), ponderados
  por `config/weights.yaml`. **Nunca lee `mastery`.**
- **PersonalScore**: parte del GlobalScore y lo ajusta comparando el
  `mastery` (0-100) contra una `required_skill` derivada del propio
  candidato (`execution_demand` + cantidad de entradas condicionales de su
  plan). Un counter teórico con mastery 0 puede seguir siendo el mejor pick
  *global* sin ser el mejor pick *personal*.

Ninguno de los dos números es una probabilidad de victoria: son un índice de
adecuación mecánica de esta V0, y la CLI lo aclara en cada salida.

### Confianza

La confianza **no sube porque se dispararon muchas reglas**. Se calcula a
partir de:
1. **Cobertura de categorías mecánicas distintas** (no cantidad de entradas:
   dos reglas de la misma categoría no suman cobertura extra).
2. **Contradicción**: evidencia PRO y CONTRA de magnitud comparable en el
   mismo factor (eso es, literalmente, un matchup condicional).
3. **Información faltante** señalada por el motor (`invalidated_if`).
4. **Densidad de entradas condicionales** (cuánto depende la conclusión de
   una circunstancia particular).

## Cómo ejecutarlo

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

python -m pytest tests/ -v

python -m lol_reasoner recommend --enemy Darius --candidates Mordekaiser --mastery Mordekaiser=80
python -m lol_reasoner recommend --enemy Mordekaiser --candidates Darius --mastery Darius=15 --json
```

Si se omite `--candidates`, se evalúan todos los demás campeones cargados.
`--phases` acepta una lista separada por comas entre
`early_lane,level_6,first_item,side_lane_late` (por defecto, las cuatro).

## Ejemplos

```bash
python -m lol_reasoner recommend --enemy Darius --candidates Mordekaiser --mastery Mordekaiser=80
```

Produce, entre otras cosas: el `GlobalScore` y `PersonalScore` de
Mordekaiser, el desglose por factor, el nivel de confianza y por qué, las
ventajas mecánicas (p. ej. que *Indestructible* niega el patrón de daño
sostenido de Darius) con el id de traza que las respalda, los riesgos (que
*Darkness Rise* es específicamente vulnerable al daño verdadero de Darius),
las condiciones que podrían cambiar la conclusión, y cómo cambia el panorama
fase a fase.

```bash
python -m lol_reasoner recommend --enemy Mordekaiser --candidates Darius --mastery Darius=15
```

La misma pareja, evaluada en la dirección opuesta: el motor no espeja el
resultado — recalcula desde cero con Darius como candidato y Mordekaiser
como enemigo, y produce razones, riesgos y confianza distintos.

## Limitaciones (honestas)

- **Conocimiento no auditado**: los valores de ejes, tags y power spikes son
  una lectura cualitativa propia sin validar contra parche, fuente estadística
  ni comunidad. Ver `docs/decisiones-tecnicas.md`.
- **Pesos sin calibrar**: `config/weights.yaml` refleja intuición de diseño,
  no datos. La curva de `required_skill` en `personal_score.py` es
  igualmente heurística.
- **Solo 2 campeones**: Darius y Mordekaiser. El resto del roster (Garen,
  Jax, Fiora, Renekton, Malphite, Ornn, Gwen, Kennen) queda para el próximo
  hito, tras revisión de este primero.
- **Sin objetos, runas, summoners ni composición**: `first_item` es una fase
  aproximada; cualquier conclusión que dependiera de un objeto puntual se
  marca como información faltante en vez de inventarse.
- **Sin datos estadísticos**: no hay integración con ninguna fuente externa;
  los puertos para agregarlos después (fuerza de parche, stats de matchup,
  tamaño de muestra, elo, confianza del dato) todavía no existen como código
  en este hito — están descritos como trabajo futuro en el backlog.
- **Confianza heurística**: la fórmula de `scoring/confidence.py` es una
  primera aproximación razonable, no una calibración estadística.

## Documentos relacionados

- `docs/decisiones-tecnicas.md` — decisiones de diseño y por qué.
- `docs/backlog-v1.md` — qué sigue después de este hito.
