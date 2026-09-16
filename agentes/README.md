# Estado de los agentes

| Agente | Fase | Estado | Dónde |
|---|---|---|---|
| A2 Minero | 0 | **Hecho.** Troceado por capítulos, extracción con salida estructurada, verificación de ancla y cita, vocabulario, coste por corrida, `--sin-ia` y `--estimar` | `agentes/minero/` |
| A6 Guardián · reglas | 0 | **Hecho.** Vocabulario vetado ES/EN por niveles; localización tolerante de citas | `agentes/guardian/reglas.py`, `verificar_citas.py` |
| Base de datos | 0 | **Hecha.** Esquema completo; migración de columnas | `agentes/db.py` |
| Web del sello | 0 | **Hecha** v1 | `web/` |
| Enlace universal | 0 | **Hecho** el Worker; falta desplegar (cuenta Cloudflare) | `worker_enlaces/` |
| Planificador (provisional) | 1 | **Hecho.** Determinista: formatos por día de la semana, átomos menos usados, reparto entre libros, hora local → UTC. El Estratega (Fase 2) lo sustituye | `agentes/planificador.py` |
| A3 Redactor | 1 | **Hecho.** Átomo → 7 diapositivas o cita, caption, hashtags, pin, Telegram, alt, 3 ganchos. Reintenta con el motivo del Guardián y con la nota del humano. La cita literal se fuerza al texto exacto | `agentes/redactor/` |
| A6 Guardián · cola | 1 | **Hecho.** Capa determinista (vocabulario, límites, estructura, cita intacta, libro nombrado) + criterio con modelo (`modelo_guardian`). Avisos viajan al humano | `agentes/guardian/cola.py`, `criterio.md` |
| A4 Diseñador | 1 | **Hecho.** HTML/CSS por serie con paleta de las portadas, fuente Lora embebida, Playwright → JPEG 1080×1350 y pin 1000×1500. `--demo` para ver el diseño. Vídeo: Fase 2 | `agentes/disenador/` |
| Aprobación Telegram | 1 | **Hecho.** Previas con fotos + botones; respuestas por sondeo en cada corrida (sin servidor); nota de edición devuelve la pieza al Redactor; comandos de texto `ok N`, `no N`, `ed N nota` | `agentes/aprobacion/telegram.py` |
| A7 Publicador | 1 | **Hecho.** Telegram (canal), Pinterest (imagen en base64), Instagram (carrusel/imagen por URL pública, espera a que la web sirva las imágenes). Solo publica `aprobada` y vencida; parcial por canal; reintento en la siguiente corrida | `agentes/publicador/` |
| Pipeline | 1 | **Hecho.** `diario`, `aprobaciones`, `cola`, `ver`, `aprobar`, `rechazar`, `editar`, `estado` | `agentes/pipeline.py` |
| A1 Estratega | 2 | Pendiente. Plan semanal con criterio a partir de inventario, fechas y métricas | `agentes/estratega/` |
| A5 Locutor | 2 | Pendiente. Edge TTS → pódcast (RSS) y Shorts | `agentes/locutor/` |
| A9 Analista | 2 | Pendiente. Recogida por API + CSV de KDP → informe y panel | `agentes/analista/` |
| A10 Bibliotecario Amazon | 2 | Pendiente. Calendario de días gratis, palabras clave, A+ | `agentes/bibliotecario/` |
| Publicador · Threads, Bluesky, Facebook, X, YouTube | 2 | Pendiente | `agentes/publicador/` |
| A8 Escucha | 3 | Pendiente | `agentes/escucha/` |

## Ciclo de vida de una pieza (Fase 1)

```
planificada ─Redactor─▶ redactada ─Guardián─▶ pendiente_humano ─Diseñador─▶ (imágenes) ─Telegram─▶ humano
     ▲                       │                                                                   │
     │ nota de edición       └─ rechazada (motivo, intentos+1) ─▶ planificada … ─▶ descartada     ├─ ✅ aprobada ─Publicador (a su hora)─▶ publicada
     └───────────────────────────────────────────────────────────────────────────────────────────┤─ ✏️ editar → planificada con nota
                                                                                                  └─ ❌ descartada
```

## Convenciones

- Un agente creativo = un módulo con `prompt.md` (texto del sistema con huecos) y un `*.py` con CLI. El prompt se rellena desde el YAML del sello; nada de voz o reglas escritas en el código.
- Todo lo que llama a la API pasa por `agentes/ia.py` y registra tokens y coste en `ejecuciones`.
- Los agentes de producción (Diseñador, Publicador) no usan modelo de lenguaje.
- Nunca se publica desde un agente creativo. La cola es la frontera: `aprobada` la pone el humano.
- Sin credenciales de un canal, ese canal simplemente no actúa; el resto sigue.
