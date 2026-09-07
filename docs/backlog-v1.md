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
13. **Mecánica avanzada/contextual: Death's Grasp en reversa** (hito 1.6).
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
    diseñar el modelo de posición/geometría de V1.
