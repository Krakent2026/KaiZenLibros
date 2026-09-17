# Promoción con agentes de IA — sello Kai Zen

Sistema de agentes que produce, verifica, publica y mide contenido para promocionar en Amazon las series del sello Kai Zen, con coste de plataformas cero. El plan completo está en [`PLAN_MARKETING_AGENTES_IA.md`](PLAN_MARKETING_AGENTES_IA.md); este README cubre la puesta en marcha.

**Estado: Fases 0, 1 y 2 implementadas.** Ciclo diario completo (planificar → redactar → guardián → imágenes y audio → aviso en Telegram → publicar en Telegram, Instagram, Pinterest, Bluesky, Threads, X y pódcast) y ciclo semanal (Bibliotecario → Analista → Estratega → resumen a Telegram). Lo que hay y lo que falta, en [`agentes/README.md`](agentes/README.md).

### Ciclo semanal y pódcast (Fase 2)

```bash
python -m agentes.pipeline semanal                  # recordatorios KDP + informe + plan de la semana (Estratega) + resumen a Telegram
python -m agentes.estratega.planificar --ver        # plan vigente
python -m agentes.bibliotecario.calendario          # calendario de días gratis y recordatorios
python -m agentes.analista.informe --dias 7         # informe (añade --enviar para mandarlo a Telegram)
python -m agentes.locutor.sintetizar --feed         # regenera feed.xml y episodios.json del pódcast
python herramientas/portada_podcast.py              # portada 3000×3000 para Apple/Spotify
```

- **Pódcast.** Los miércoles la plantilla planifica una pieza `audio`: el Redactor escribe un guion de 650-850 palabras, el Locutor lo sintetiza con Edge TTS (gratuito, voz `podcast.voz` del YAML) y el feed RSS sale con la web en `static/podcast/feed.xml`. Alta única en Spotify for Creators y Apple Podcasts Connect con esa URL; después los episodios llegan solos.
- **Días gratis.** Con 12 libros en KDP Select el Bibliotecario reparte una promoción de 2 días cada semana (5 días por libro y 90 días es el límite de Amazon). Avisa por Telegram 14 días antes; programar la promo en KDP es manual.
- **KDP.** Deja los CSV de KDP Reports en `datos/kdp/` (no se versionan) y el Analista los suma al informe.

## Qué hay en el repositorio

```
config/sellos/kaizen.yaml     series, libros, voz, tiendas Amazon, UTM, modelos de IA  ← todo sale de aquí
config/prohibido_es.txt       vocabulario vetado (bloquea / avisa); prohibido_en.txt para inglés
config/fechas_nicho.yaml      fechas señaladas por serie
config/paletas/*.json         colores extraídos de las portadas reales (generado)
agentes/config.py             carga del sello y rutas
agentes/db.py                 SQLite: libros, átomos, cola, publicaciones, métricas, ejecuciones
agentes/minero/               Minero: manuscrito → átomos verificados (API de Claude)
agentes/guardian/             verificación de citas y reglas de vocabulario
agentes/pipeline.py           lo que ejecutan los workflows (estado / diario / semanal)
web/                          generador estático de la web del sello (Jinja2) → web/dist
worker_enlaces/               Cloudflare Worker del enlace universal geolocalizado
herramientas/                 paleta desde portadas, copia de portadas, enlaces.json
datos/atomos.sqlite           la base de datos (se versiona; los manuscritos no)
.github/workflows/            web.yml (GitHub Pages), diario.yml, semanal.yml, tests.yml
```

Los manuscritos **no entran en el repositorio**. El Minero se ejecuta en local, lee de `KAIZEN_FUENTES` y solo sube a Git los átomos (fragmentos cortos ya verificados) en `datos/atomos.sqlite`. GitHub Actions trabaja sobre esa base de datos.

## Puesta en marcha en local

```bash
pip install -r requirements.txt
copy .env.example .env          # y rellenar ANTHROPIC_API_KEY y KAIZEN_FUENTES
python -m pytest -q             # 12 tests
```

Variables de entorno en Windows (PowerShell) para la sesión:

```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
$env:KAIZEN_FUENTES = "C:\Users\d.zaplana\OneDrive - SAES\Documentos\David\Libros\8.Espiritualidad"
```

Sin `KAIZEN_FUENTES`, se usa `../8.Espiritualidad` respecto al repositorio, que es donde está ahora.

### Minero

```bash
python -m agentes.minero.extraer --serie mente_distinta --estimar            # coste aproximado, sin API
python -m agentes.minero.extraer --serie mente_distinta --libro no-es-pereza --max-tramos 3   # prueba corta
python -m agentes.minero.extraer --serie mente_distinta                      # los 12 libros
python -m agentes.minero.extraer --listar --serie mente_distinta             # muestra átomos
python -m agentes.pipeline estado                                            # inventario y coste
```

Cada átomo guarda un `ancla` (pasaje literal del manuscrito) con su offset y hash. Si el ancla, o la cita cuando es literal, no aparece en el fichero, el átomo queda como **no verificado** con el motivo y ningún agente posterior lo usa. El vocabulario vetado también se comprueba en ese momento.

Modelos y esfuerzo se cambian en `config/sellos/kaizen.yaml` → `ia`. Por defecto el Minero usa `claude-sonnet-5`; la extracción completa de *Mente distinta* (673.000 palabras) cuesta del orden de 4-6 USD una sola vez.

### Ciclo diario (Fase 1)

```bash
python -m playwright install chromium           # una vez; el Diseñador renderiza con Chromium
python -m agentes.disenador.render --demo       # ver el diseño en datos/salida/demo sin gastar
python -m agentes.pipeline diario               # planificar → redactar → guardián → imágenes → previas Telegram → publicar
python -m agentes.pipeline cola                 # qué hay vivo y en qué estado
python -m agentes.pipeline ver --id 12          # textos completos de una pieza
python -m agentes.pipeline aprobar --id 12      # aprobación manual (cuando aún no hay bot de Telegram)
python -m agentes.pipeline editar --id 12 --nota "Quita la segunda frase"   # vuelve al Redactor con la nota
python -m agentes.pipeline aprobaciones         # respuestas de Telegram + publicar lo aprobado y vencido
```

Qué se planifica cada día está en el YAML → `plan.semana` (formatos por día) y `plan.horas`. Además de las piezas de libro (`carrusel`, `cita`, `audio`) hay dos **institucionales** sin átomo, escritas desde la descripción del sello y de la serie en el YAML: `sello` (qué escribe Kai Zen, qué se niega a decir) y `serie` (mapa de lectura, itinerarios, puerta de entrada). `plan.arranque` lista las primeras (una al día, en el primer hueco); después sale una cada `plan.institucional_cada_dias`, alternando. Para meter una pieza a mano:

```bash
python -m agentes.pipeline encargar --formato sello --hora 16:00 --angulo "Qué escribe Kai Zen"
python -m agentes.pipeline encargar --formato serie --serie mente_distinta --hora 2026-09-20T12:30
python -m agentes.pipeline encargar --formato cita --libro no-es-pereza --hora 19:00
``` El Redactor usa `ia.modelo_redactor`; el Guardián de criterio, `ia.modelo_guardian`. Coste orientativo por pieza: 0,02-0,04 USD (redacción + revisión).

**Aprobación en Telegram.** Crear un bot con @BotFather, abrir un chat con él y anotar el id del chat (`TELEGRAM_CHAT_APROBACION`). Cada pieza llega con sus imágenes y botones. También valen mensajes de texto: `ok 12`, `no 12`, `ed 12 quita la última frase`. Las respuestas se recogen en cada corrida del workflow `aprobaciones.yml` (cada dos horas); no hace falta servidor.

**Modos de aprobación** (`publicacion.aprobacion` en el YAML):
- `manual`: nada sale sin ✅ del humano.
- `mixto`: se autoaprueban las citas literales sin avisos del Guardián; carruseles y piezas con avisos esperan al humano.
- `auto` (activo): todo lo que pasa el Guardián queda aprobado. La previa llega a Telegram con «⏱ se publica sola a las HH:MM» y botones ✏️ Editar / ❌ Cancelar. Red de seguridad: la pieza no se publica hasta `antelacion_minima_min` (60) minutos después del aviso, y una pieza que el Guardián rechazó alguna vez siempre pasa por el humano (`rechazadas_a_manual`).

**Canales.** Cada conector actúa solo si tiene credenciales (ver `.env.example`). Telegram publica en el canal `TELEGRAM_CANAL` (el bot debe ser administrador). Pinterest sube la imagen en base64 al tablero `PINTEREST_TABLERO_ID`. Instagram necesita que las imágenes sean públicas: se guardan en `web/static/piezas/<id>/` y salen con la web; si al publicar aún no responden, la pieza espera a la siguiente corrida. Las imágenes de piezas publicadas o descartadas se retiran del repositorio a los 21 días (`publicacion.dias_conservar_piezas`).

**Importante sobre GitHub Pages.** En el plan gratuito de GitHub, Pages solo funciona con repositorios **públicos**. Opciones: (a) repositorio público (los manuscritos nunca están en él; sí los átomos, que son fragmentos cortos ya publicados en los libros); (b) repositorio privado + **Cloudflare Pages** conectado a GitHub (gratuito): comando de build `pip install -r requirements.txt && python -m web.generar --base-url /`, directorio `web/dist`; poner esa URL en `sello.web`.

### Web

```bash
python herramientas/paleta_desde_portadas.py     # config/paletas/mente_distinta.json
python herramientas/copiar_portadas.py           # web/static/portadas/*.jpg (600 px)
python -m web.generar --base-url /               # web/dist
python -m http.server -d web/dist 8000           # http://localhost:8000
```

Artículos del blog: `web/contenido/blog/*.md` con cabecera YAML (ver `LEEME.md` allí).

### Enlace universal

```bash
python herramientas/generar_enlaces.py           # worker_enlaces/enlaces.json
cd worker_enlaces && npx wrangler login && npx wrangler deploy
```

Después, poner la URL del Worker en `config/sellos/kaizen.yaml` → `enlaces.base_url`. Hasta entonces la web usa sus propias páginas `/ir/<slug>/` (sin geolocalización, con enlaces a las otras tiendas). Cuando haya ASIN, rellenar `asin_ebook` en el YAML y regenerar.

## Puesta en marcha en GitHub (opción B)

```bash
git init -b main && git add -A && git commit -m "Fase 0: cimientos del sistema de agentes"
gh repo create Promocion_IA --private --source=. --push
gh secret set ANTHROPIC_API_KEY
gh variable set BASE_URL --body "/Promocion_IA/"       # con dominio propio: "/"
```

Secretos adicionales cuando existan las cuentas: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_APROBACION`, `TELEGRAM_CANAL`, `PINTEREST_TOKEN`, `PINTEREST_TABLERO_ID`, `INSTAGRAM_TOKEN`, `INSTAGRAM_CUENTA_ID`.

En el repositorio: **Settings → Pages → Source: GitHub Actions** (o Cloudflare Pages, ver arriba). Workflows:

| Workflow | Cuándo | Qué hace |
|---|---|---|
| `web.yml` | push que toque `web/` o `config/` | Genera y publica la web (y con ella las imágenes de las piezas) |
| `diario.yml` | 06:00 UTC | Planifica, redacta, revisa, produce imágenes, envía previas a Telegram, publica lo vencido; guarda `datos/` y `web/static/piezas/` |
| `aprobaciones.yml` | cada 2 h | Recoge respuestas de Telegram, publica lo aprobado cuya hora llegó, limpia piezas antiguas |
| `semanal.yml` | domingos | Fase 2 (Estratega, Analista, Bibliotecario); por ahora solo registra la corrida |
| `tests.yml` | push / PR | pytest + generación de la web |

Repositorio privado: 2.000 minutos/mes gratuitos de Actions. El diario tarda 3-4 minutos (instala Chromium); las aprobaciones, menos de 1. Total estimado: unos 250 minutos/mes.

## Qué hacer a mano

- Reservar nombres de usuario: [`docs/CHECKLIST_CUENTAS.md`](docs/CHECKLIST_CUENTAS.md).
- Obtener cada clave, paso a paso, y pasarlas a GitHub: [`docs/CLAVES.md`](docs/CLAVES.md). Comprobación: `python herramientas/comprobar_credenciales.py`.

## Reglas que el código hace cumplir

- Ninguna cita sale sin encontrarse en el manuscrito.
- Nada con vocabulario de promesa de salud, «bestseller», premios inventados, tests o diagnósticos.
- Ningún agente publica directamente: publica un script tras la aprobación humana (Fase 1).
- Sin interacción automática con terceros, sin reseñas incentivadas, sin datos personales en el registro de clics.
