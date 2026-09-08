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

Esta entrega cubre los hitos 1, 1.5 y 1.6 de la V0: validar el flujo
completo del motor con **dos campeones** (Darius y Mordekaiser), en ambas
direcciones de matchup, antes de cargar los ocho restantes (Garen, Jax,
Fiora, Renekton, Malphite, Ornn, Gwen, Kennen). El hito 1.5 refactorizó el
modelo de conocimiento (schema v2, ver `docs/decisiones-tecnicas.md` §11)
porque el del hito 1 era demasiado limitado: una habilidad solo podía
tener un efecto, y dos afirmaciones del conocimiento resultaron
directamente falsas. El hito 1.6 (`docs/decisiones-tecnicas.md` §12)
corrigió un bug de reciprocidad en cuatro reglas generales, eliminó una
inferencia falsa (`INTERRUPT` negando cargas de acumulación), introdujo
`causal_key` para deduplicar score sin perder trazabilidad, y separó
confianza epistémica de volatilidad/condicionalidad. **v1.6.1** (§13)
encontró tres escaneos unidireccionales que habían sobrevivido dentro de
la regla de daño, separó certeza (`Support`) y procedencia
(`Provenance`) de la dirección (`Polarity`), sacó del score a los ejes
editoriales (se muestran, no deciden), partió la regla monolítica de daño en tres y reemplazó la
suma de magnitudes ordinales de la carrera de acumulaciones por una
comparación de capacidades estructurales.

**Sí incluye:**
- Propiedades semánticas de los campeones (ejes, mecánicas de acumulación,
  recurso de lanzamiento).
- Habilidades con **múltiples efectos estructurados** (`Effect`: tipo,
  magnitud, condiciones, tipo de daño) e interacciones entre kits derivadas
  de esos efectos, no de tags precargados.
- Mecánicas de acumulación (`StackingMechanic`: umbral, fuentes, recompensa)
  como objeto de primera clase, comparables entre campeones sin nombrarlos.
- Patrones de trade (`tactical_uses` por habilidad) y ventanas de cooldown.
- Cambios entre 4 fases de progresión: `early_lane`, `level_6`, `first_item`,
  `side_lane_late`, con `available_from` cumplido estructuralmente.
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
(`"0.2.1"`) es la versión **interna de esta base de datos**, no un número de
parche de LoL. La validación de kits contra fuentes actuales y el soporte de
parches quedan como una etapa posterior independiente (ver
`docs/backlog-v1.md`).

## Arquitectura

```
src/lol_reasoner/
├── domain/            # Entidades: Champion, MatchupQuery, Recommendation...
│   ├── enums.py        # Vocabulario cerrado: Axis, EffectType, TacticalUse, Phase, Factor...
│   ├── champion.py      # Champion, Ability, Effect, StackingMechanic, PowerSpike
│   ├── query.py          # MatchupQuery (entrada)
│   └── result.py          # Recommendation, RecommendationSet, ReasonItem... (salida)
│
├── knowledge/         # Base de conocimiento estructurada
│   ├── champions/*.yaml  # Un YAML por campeón, comentado — schema v3
│   ├── schema.py          # Validación manual (sin dependencias extra)
│   └── loader.py           # YAML -> Champion
│
├── reasoning/         # El motor de razonamiento
│   ├── context.py       # ReasoningContext: candidate_abilities()/enemy_abilities() filtradas por fase
│   ├── trace.py           # TraceEntry, ReasoningTrace — la evidencia
│   ├── engine.py            # RuleEngine: reglas -> TraceEntry
│   └── rules/
│       ├── base.py           # Rule, RuleEffect
│       ├── general.py          # Reglas generales (sin nombres de campeón)
│       ├── stacking.py           # StackRaceRule + derivación de StackingMechanic
│       ├── specific.py             # Excepciones puntuales, justificadas y acotadas (hoy: vacío)
│       └── registry.py               # Registro combinado + universo de categorías
│
├── scoring/           # MatchupScore, PersonalScore, Confidence
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

Las reglas de `reasoning/rules/general.py` y `reasoning/rules/stacking.py`
**no pueden comparar el `.id` de un campeón contra un literal**: leen ejes
(`axes`), `casting_resource`, y sobre todo `effects`/`tactical_uses` de las
habilidades disponibles en la fase actual — siempre a través de
`ctx.candidate_abilities()`/`ctx.enemy_abilities()`, nunca
`champion.abilities` directo. Esto es lo que impide que el motor degenere
en una tabla de 90 resultados hardcodeados: `tests/test_no_hardcoded_pairs.py`
escanea el AST de ambos archivos y falla si aparece un literal con el id o
nombre de un campeón, o una comparación contra `.id`; `tests/test_phase_availability.py`
hace lo mismo para el acceso directo a `.abilities`.

`reasoning/rules/specific.py` permite un número acotado (≤10) de
excepciones entre **habilidades concretas** de dos campeones concretos,
cuando existe una interacción real que las reglas genéricas no pueden
capturar. Hoy está **vacío**: las dos excepciones del hito 1 (que el daño
verdadero ignora escudos, que un escudo revierte cargas de acumulación)
resultaron ser afirmaciones falsas, no interacciones que las reglas
generales no pudieran capturar. Al modelar `Effect.damage_type` y
`SHIELD_FROM_STORED`/`CONVERT_SHIELD_TO_HEAL` estructuralmente, ambas
quedaron cubiertas por reglas generales sin necesitar ninguna excepción —
que el módulo pueda quedar vacío es, en sí, la validación del principio
"primero las reglas generales". Sigue vacío en el hito 1.6: la inferencia
falsa "un `INTERRUPT`/pull niega una carga de acumulación rival"
(`MitigationAndDisruptionRule`) se eliminó por ser incorrecta, no
reemplazada por una excepción puntual (ver `docs/decisiones-tecnicas.md`
§12.2).

### GlobalScore vs. PersonalScore

- **GlobalScore**: suma, por fase y por factor, los deltas de la traza ya
  **deduplicados por `causal_key`** (`ReasoningTrace.deduped_for_scoring`:
  cuando dos `TraceEntry` describen la misma fuente mecánica exacta —
  misma habilidad, mismo efecto, aunque las cuente una regla distinta o la
  misma regla en otra fase — se colapsan a una sola contribución de
  score, sin perder ninguna de las dos en la traza completa que ve el
  usuario). `PRO`=+1, `CONTRA`=-1, `CONDITIONAL`=0 — una ventaja puramente
  condicional no debe inflar el número, solo aparecer como condición
  textual —, ponderados por `config/weights.yaml`. Sobre ese signo se
  aplican dos multiplicadores configurables y visibles entrada por
  entrada en la traza: `Support` (cuánta certeza respalda la
  inclinación: `STRUCTURAL` entera, `CONDITIONED` amortiguada,
  `AMBIGUOUS` cero) y `Provenance` (si el hecho se derivó del kit o es un
  prior editorial de un eje escrito a mano). **Nunca lee `mastery` ni
  `execution_demand`.**
- **PersonalScore**: parte del GlobalScore y lo ajusta comparando el
  `mastery` de un `PlayerProfile` (hoy solo ese campo; interfaz pensada
  para agregar después partidas jugadas, winrate personal, recencia,
  experiencia en el rol) contra una `required_skill` derivada del
  `execution_demand` del propio candidato y de cuántas condiciones
  **`ConditionKind.EXECUTION`** distintas trae su plan — nunca de
  información faltante ni de incertidumbre estratégica (ver Confianza,
  abajo). Un counter teórico con mastery 0 puede seguir siendo el mejor
  pick *global* sin ser el mejor pick *personal*.

Ninguno de los dos números es una probabilidad de victoria: son un índice de
adecuación mecánica de esta V0, y la CLI lo aclara en cada salida. Los
GlobalScore de las dos direcciones de un mismo matchup son hoy
**antisimétricos** respecto de 50 (suman 100) como consecuencia del
invariante de reciprocidad — toda causa compartida pesa igual con signo
opuesto —, no porque sean probabilidades complementarias. Dejarán de
sumar 100 exactamente en cuanto un hecho propio del candidato mueva el
score.

La explicación cierra con un `Lean`: dirección, intensidad, confianza,
factores principales y condiciones que podrían reducirla o invertirla.
Cuando hay evidencia suficiente el motor se inclina; no se refugia en una
lista de condiciones.

### Dirección, condición y certeza son tres cosas distintas

Un motor que solo tiene `Polarity` para expresarlas termina obligando a
elegir entre afirmar una ventaja entera o no afirmarla: en el hito 1.6,
casi la mitad de las entradas que sobrevivían a la deduplicación
aportaban cero al score. v1.6.1 las separa en tres ejes ortogonales:

| Eje | Pregunta | Valores |
|---|---|---|
| `Polarity` | ¿hacia qué lado se inclina? | PRO / CONTRA / CONDITIONAL |
| `condition` + `ConditionKind` | ¿de qué depende? | EXECUTION / STRATEGIC / KNOWLEDGE_GAP |
| `Support` | ¿cuánta certeza hay? | STRUCTURAL / CONDITIONED / AMBIGUOUS |

Una ventaja condicionada (`PRO` + `CONDITIONED`) inclina el score de
forma amortiguada **y** aumenta la volatilidad; una interacción de doble
filo real (`AMBIGUOUS`) aporta cero pero se conserva entera en la
explicación. A eso se suma `Provenance`, que distingue un hecho derivado
del kit de un prior editorial: los ejes escritos a mano se muestran
íntegros y etiquetados, en su propio canal de salida, pero **aportan cero**
al MatchupScore. Un eje 0..4 escrito a mano no puede decidir un veredicto
mecánico; ocultarlo tampoco sería honesto.

### Confianza: epistémica vs. volatilidad

Desde el hito 1.6, "cuánto sabemos" y "cuánto puede cambiar la
recomendación" son dos números independientes, clasificados por
`domain.enums.ConditionKind`:

- **Confianza epistémica** (`ConfidenceResult.score`): cobertura de
  categorías mecánicas aplicables a este matchup — el denominador se
  calcula con una **traza espejo** (candidato/enemigo invertidos), usada
  solo para saber qué categorías eran relevantes, nunca expuesta ni
  mezclada con el resultado del candidato — penalizada por
  `ConditionKind.KNOWLEDGE_GAP` (información que el motor reconoce no
  tener, p. ej. `ITEMGAP`). Una traza vacía da confianza epistémica 0.0 /
  BAJA, sin piso artificial.
- **Volatilidad estratégica compartida** (`ConfidenceResult.volatility_score`):
  contradicción real (evidencia PRO y CONTRA de magnitud comparable en el
  mismo `(fase, factor)`, contada sobre la vista causal deduplicada) más
  densidad de condiciones `ConditionKind.STRATEGIC` que también aparecen
  al invertir la consulta. Una tensión del matchup —la geometría del
  duelo, el ritmo del intercambio, la carrera de acumulaciones— no puede
  evaporarse porque cambie quién es el candidato. Las condiciones
  estratégicas cuentan **sin importar la polaridad** de la entrada que
  las lleva.
- **Exigencia de ejecución del candidato** (`execution_condition_count`):
  condiciones `EXECUTION`, que sí pueden ser asimétricas porque dependen
  del kit del candidato. Alimentan `required_skill` en PersonalScore y no
  se mezclan con la volatilidad del matchup.

Que exista evidencia PRO y CONTRA sobre un mismo matchup **no** se
interpreta automáticamente como ignorancia: es volatilidad, una señal
distinta de "no tenemos el dato".

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
ventajas mecánicas (p. ej. que *Indestructible* puede absorber parte del
daño de Darius, incluido su componente verdadero) con el id de traza que
las respalda, los riesgos (que Mordekaiser llega después que Darius a su
propio umbral de acumulación), las condiciones que podrían cambiar la
conclusión, y cómo cambia el panorama fase a fase.

```bash
python -m lol_reasoner recommend --enemy Mordekaiser --candidates Darius --mastery Darius=15
```

La misma pareja, evaluada en la dirección opuesta: el motor no espeja el
resultado — recalcula desde cero con Darius como candidato y Mordekaiser
como enemigo, y produce razones, riesgos y confianza distintos.

## Limitaciones (honestas)

- **Conocimiento no auditado**: los valores de ejes, efectos, mecánicas de
  acumulación y power spikes son una lectura cualitativa propia sin validar
  contra parche, fuente estadística ni comunidad. Ver `docs/decisiones-tecnicas.md`.
- **Los ejes de fase (`early_pressure`, `scaling`) son valoraciones
  manuales**, no conclusiones derivadas del kit, y no mueven el score:
  se muestran etiquetados en un canal aparte. Derivarlos está en
  `docs/backlog-v1.md`.
- **La penetración física y la mágica se registran pero no puntúan**:
  compartir un ordinal cualitativo no demuestra igual intensidad ni
  relevancia. Cuantificarlas exige valores numéricos, escalado por nivel,
  resistencias del objetivo y contexto de parche.
- **`DisplacementVsMobilityRule` (G15) no dispara para este par**: tanto
  Darius como Mordekaiser tienen `mobility=0`/`disengage=0`, así que la
  regla que valora negar espacio al rival correctamente no encuentra nada
  que negar. Es un resultado honesto (no hay ventaja marginal real ahí), no
  vocabulario muerto — se espera que se active con campeones más móviles.
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
