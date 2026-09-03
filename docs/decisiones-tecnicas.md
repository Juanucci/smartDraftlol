# Decisiones técnicas — V0, primer hito (Darius vs Mordekaiser)

Documento breve de decisiones tomadas sin bloquear en el usuario, con su
justificación. Ninguna de estas decisiones es definitiva: son puntos de
partida razonables para validar la arquitectura.

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
