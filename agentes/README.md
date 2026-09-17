# Estado de los agentes

| Agente | Fase | Estado | Dónde |
|---|---|---|---|
| A2 Minero | 0 | **Hecho.** Extracción por API o importación de JSON de subagentes (`--importar-json`), verificación de ancla y cita, vocabulario | `agentes/minero/` |
| A6 Guardián · reglas | 0 | **Hecho.** Vocabulario ES/EN; localización tolerante de citas | `agentes/guardian/reglas.py`, `verificar_citas.py` |
| Base de datos | 0 | **Hecha.** Migraciones automáticas de columnas | `agentes/db.py` |
| Web del sello | 0 | **Hecha.** Inicio, series, libros, enlaces, blog, pódcast, `/ir/` | `web/` |
| Enlace universal | 0 | Worker listo; falta desplegar en Cloudflare | `worker_enlaces/` |
| Planificador diario | 1 | **Hecho.** Sigue el plan del Estratega si existe; si no, plantilla `plan.semana` | `agentes/planificador.py` |
| A3 Redactor | 1 | **Hecho.** Carrusel, cita, **audio (guion de 5 min)**; textos para Instagram, Pinterest, Telegram, **Bluesky, Threads, X** | `agentes/redactor/` |
| A6 Guardián · cola | 1 | **Hecho.** Determinista + criterio; modos manual/mixto/**auto** con ventana de cancelación | `agentes/guardian/cola.py` |
| A4 Diseñador | 1 | **Hecho.** JPEG por serie (Playwright, Lora); portada de episodio | `agentes/disenador/` |
| Aprobación Telegram | 1 | **Hecho.** Previas con botones; en modo auto, aviso con hora y ❌ Cancelar | `agentes/aprobacion/telegram.py` |
| A7 Publicador | 1-2 | **Hecho.** Telegram, Pinterest, Instagram, **Bluesky, Threads, X (texto), pódcast (feed)** | `agentes/publicador/` |
| A1 Estratega | 2 | **Hecho.** Plan semanal con criterio (libro, tipo de átomo, ángulo por pieza) a partir de inventario, fechas, promos gratis y métricas; validado contra la plantilla | `agentes/estratega/` |
| A5 Locutor | 2 | **Hecho.** Edge TTS (gratuito) → MP3 24 kHz; feed RSS con etiquetas iTunes; página web del pódcast. Vídeo para Shorts: Fase 3 | `agentes/locutor/` |
| A9 Analista | 2 | **Hecho.** Métricas por API (Instagram, Pinterest, Bluesky, Threads), seguidores, importación de CSV de KDP, informe semanal (Markdown + resumen a Telegram) | `agentes/analista/` |
| A10 Bibliotecario | 2 | **Hecho.** Calendario rotatorio de días gratis (KDP Select), recordatorios con antelación, caducidad de tokens, ASIN pendientes, fechas señaladas, sugerencias del Estratega | `agentes/bibliotecario/` |
| Pipeline | 1-2 | **Hecho.** `diario` (incluye audio, artículo del blog los jueves y métricas), `aprobaciones`, `semanal` (Bibliotecario → Analista → Estratega → resumen a Telegram), `encargar` | `agentes/pipeline.py` |
| Redactor de artículos | 2 | **Hecho.** Átomos de un libro → artículo Markdown de 900-1300 palabras; las citas «…» se verifican contra el manuscrito; vocabulario vetado; cabecera para la web | `agentes/redactor/articulos.py` |
| Piezas institucionales | 2 | **Hecho.** Formatos `sello` y `serie` sin átomo, plan de arranque y cadencia; diapositiva final con la colección | `agentes/planificador.py` |
| Publicador · Facebook, YouTube | 3 | Pendiente (YouTube exige verificación OAuth; Facebook, página y token de página) | — |
| A8 Escucha | 3 | Pendiente. Menciones y borradores de respuesta para el humano | `agentes/escucha/` |
| Guardián de cupos | 3 | Pendiente. Cupo mensual de X y de la API de Instagram | — |

## Ciclo de vida de una pieza

```
planificada ─Redactor─▶ redactada ─Guardián─▶ pendiente_humano ─┐
     ▲                       │                                  │ Diseñador (JPEG) · Locutor (MP3 si audio) · Telegram (previa)
     │ nota ✏️               └─ rechazada (motivo) ─▶ … ─▶ descartada
     └──────────────── modo auto: ─▶ aprobada (aviso ⏱, ❌ cancela) ─▶ Publicador a su hora (≥60 min tras el aviso) ─▶ publicada ─▶ Analista
```

## Ciclo semanal (domingo 05:00 UTC)

1. **Bibliotecario**: promos gratis de las próximas dos semanas (programar en KDP), tokens que caducan, ASIN pendientes, fechas señaladas.
2. **Analista**: importa CSV de `datos/kdp/`, recoge métricas, escribe `datos/salida/informe_<fecha>.md`.
3. **Estratega**: plan de la semana siguiente en kv `plan_semana:<lunes>`; el planificador diario lo sigue.
4. Resumen de los tres a Telegram.

## Convenciones

- Un agente creativo = un módulo con `prompt.md` y un `*.py` con CLI. El prompt se rellena desde el YAML del sello.
- Todo lo que llama a la API pasa por `agentes/ia.py` y registra tokens y coste.
- Los agentes de producción (Diseñador, Locutor, Publicador, Analista, Bibliotecario) no usan modelo de lenguaje.
- Nunca se publica desde un agente creativo. La cola es la frontera.
- Sin credenciales de un canal, ese canal simplemente no actúa; el resto sigue.
