# Backlog corto para V1

Ordenado aproximadamente por lo que desbloquea más valor primero. Nada de
esto está implementado en el hito actual (Darius vs Mordekaiser).

## Inmediato (siguiente hito de esta misma V0)

1. **Cargar los 8 campeones restantes**: Garen, Jax, Fiora, Renekton,
   Malphite, Ornn, Gwen, Kennen. Validar que las reglas generales existentes
   produzcan razonamiento razonable sin escribir reglas nuevas por campeón;
   agregar excepciones específicas solo donde de verdad haga falta (manteniendo
   el tope y la justificación obligatoria).
2. **Casos de validación adicionales**: Kennen vs Darius, Gwen vs Ornn,
   Malphite vs Jax, Renekton vs Fiora, Jax vs Fiora — con foco en matchups
   condicionales (Jax vs Fiora, Renekton vs Fiora) donde no se espera un
   "ganador" limpio.
3. **Revisar cobertura de categorías** con 10 campeones: puede que aparezcan
   patrones (poke real, disengage real, waveclear extremo) que las reglas
   actuales no cubren bien porque Darius/Mordekaiser no los ejercitan.

## Derivar lo que hoy es editorial (abierto en v1.6.1)

Estos ítems son la contracara de `Provenance.EDITORIAL_PRIOR`: no se
trata de borrar los ejes escritos a mano, sino de reemplazarlos
progresivamente por algo derivado del kit.

A. **Derivar `sustain` de efectos reales**: curación, escudo, condición
   de activación, disponibilidad por fase y frecuencia (cooldown). En
   v1.6.1 se eliminó toda inferencia de score desde `axes.sustain`
   porque un solo punto editorial movía el GlobalScore doce veces más
   que la diferencia entre los dos candidatos. La regla actual
   (`TradeSustainRule`) solo lee efectos `HEAL`; falta el resto.
B. **Derivar `early_pressure`**: hoy entra como prior editorial con peso
   CERO — se muestra, no puntúa. Una derivación posible: densidad de efectos de daño
   disponibles en `early_lane`, fuentes de acumulación alcanzables y
   coste de recurso. Cuidado con reemplazar un número editorial por una
   fórmula editorial disfrazada.
C. **Modelo genérico de `PowerSpike`**: el factor que hoy se llama
   `stacking_payoff` solo sabe de mecánicas de acumulación. Un campeón
   sin acumulaciones también tiene spikes por desbloqueo de habilidad,
   transformación, nivel, breakpoint de estadísticas o cooldown, y
   sinergia concreta. `Champion.spikes` sigue siendo descriptivo y
   ninguna regla lo lee.
D. **Separar los ejes de juego tardío**, hoy colapsados en un único
   `scaling` editorial que no puntúa: `duel_scaling`, `side_lane_duel`,
   `wave_pressure`, `structure_pressure`, `collapse_resistance`,
   `map_response`, `splitpush_value`, `teamfight_value`.
   `splitpush_value` en particular deberá derivarse de capacidades
   concretas (waveclear, duelo 1v1, resistencia a un colapso, movilidad
   de rotación) y no ser otro número universal escrito a mano.

## Objetos: qué habría que modelar (documentado, NO implementado)

Nada de esto entra en v1.6.1. Se documenta para que, cuando se implemente,
no se reduzca a "tiene un objeto, sube el score".

**Timing y economía**
- Quién completa primero su primer objeto, y con cuánta ventaja.
- Coste y timing estimado de compra; el recall que lo hace posible.
- Diferencia entre un componente y el objeto terminado: un componente
  temprano puede cambiar un intercambio sin ser todavía el spike.
- Spike DISCRETO al completar el objeto, no una rampa continua.
- Estado de la partida en ese momento (oro, oleada, presión).
- Builds completas válidas para el parche, no un objeto suelto.

**Interacción con el matchup**
- Cómo interactúa el objeto con ESTE matchup, no su fuerza en abstracto.
- Coste de oportunidad: elegir una respuesta defensiva sacrifica otra
  cosa, y eso también debe pesar.

**Efectos contextuales a representar** (cada uno con su propia relación
causal, no como un tag global): reducción de curación, penetración,
resistencias, reducción o interacción con escudos, movilidad, tenacidad,
anti-burst.

**Regla de diseño que este backlog fija de antemano**: el motor NO debe
recomendar un corta-curaciones solo porque el rival tenga una curación.
Tiene que comparar cuánto healing relevante hay, qué parte de la defensa
rival es ESCUDO —que el antiheal no reduce— y qué se sacrifica al comprar
ese objeto. Es exactamente el mismo error de forma que v1.6.1 corrigió en
otro lado: inferir una consecuencia desde la mera presencia de una
etiqueta, sin medir la magnitud ni el contexto.

## Scores por fase (documentado, NO implementado)

Hoy `PhaseNote` reporta las causas NUEVAS que cada fase desbloquea, no un
score independiente por fase: una fase sin causas nuevas muestra cero
aportes aunque las interacciones anteriores sigan vigentes. Un modelo
completo por fase (score propio, con las causas heredadas revaluadas bajo
las condiciones de esa fase) requiere decidir qué significa "seguir
vigente" para cada tipo de causa y evitar volver a multiplicar una misma
ventaja por cuatro. Queda para después de los 10 campeones.

## Después de validar los 10 campeones

4. **Puertos de estadísticas reales** (`stats/ports.py` con un `Protocol`):
   fuerza del campeón en el parche, stats de matchup, tamaño de muestra, elo,
   rol, fecha/fuente, confianza del dato. Deben **calibrar** la conclusión
   mecánica (mover el score dentro de un rango acotado, nunca reemplazarla), y
   una muestra pequeña no debe poder convertir una hipótesis en una certeza.
5. **Versionado de parche real**: separar `knowledge_version` (interno) de un
   futuro campo de parche de LoL, con su propio proceso de auditoría/revisión
   por parche.
6. **Calibración de pesos**: reemplazar los pesos heurísticos de
   `config/weights.yaml` y la curva de `required_skill` por algo validado —
   aunque sea con criterio experto explícito, documentado como tal.
7. **Champion pool / perfil del jugador más rico**: hoy `mastery` es un
   entero 0-100 por campeón. V1 podría separar "cuántas partidas jugadas" de
   "qué tan bien le fue" y de "hace cuánto no lo juega".
8. **Recomendar candidatos fuera del pool declarado** con una señal explícita
   de "esto no está en tu pool, pero resuelve mejor el problema" — hoy el
   sistema no distingue candidatos dentro/fuera de pool porque `mastery`
   ausente ya se trata como neutral.
9. **Plan de partida más largo**: hoy el "plan corto de early lane" surge
   implícito de `reasons`/`conditions` de la fase `early_lane`; V1 podría
   armar un objeto `EarlyPlan` explícito a partir de la misma traza.

## Más adelante (fuera de alcance de V1 también)

10. Capa LLM que consuma la `ReasoningTrace` estructurada para generar
    prosa más natural, sin reemplazar el cálculo mecánico subyacente.
11. Analizar drafts incompletos / composiciones parciales (no solo 1v1 de
    lane).
12. Integración con Riot API / fuentes de datos en vivo — recién después de
    que los puertos de estadísticas (#4) estén definidos y probados con datos
    mock.
13. **Mecánica avanzada/contextual: Death's Grasp en reversa** (hito 1.6,
    sigue abierto en v1.6.1).
    Mordekaiser puede lanzar Death's Grasp hacia atrás para halarse a sí
    mismo lejos del rival (reposicionamiento defensivo/de escape), en vez
    de halar al rival hacia él. Esta V0 modela solo el uso ofensivo
    (`DISPLACE_ENEMY`, penetración) porque el uso en reversa depende de
    contexto direccional/posicional (hacia dónde apunta el cast) que esta
    base de conocimiento no representa — modelarlo bien requeriría noción
    de posición/orientación relativa, no solo `effects` y `axes` planos.
    No inferir esto vía `interrupt` ni generalizarlo como "herramienta de
    disengage" genérica: es un uso condicional y direccional de una
    habilidad concreta, documentado acá para no perderlo de vista al
    diseñar el modelo de posición/geometría de V1. v1.6.1 sí modeló la
    DIRECCIÓN del desplazamiento (`Effect.displacement_vector`:
    `toward_self` / `away`), que es lo que permite distinguir un pull de
    un knockback y habilita `PullTowardEngageRule`. Lo que sigue sin
    modelarse es el uso invertido: castear el pull hacia atrás para
    reposicionarse uno mismo depende de hacia dónde apunta el casteo, no
    solo de qué efecto tiene la habilidad.
