# Claves y credenciales: cómo obtener cada una

Todas van en `.env` (local, ignorado por git) y, cuando exista el repositorio, como **Secrets** de GitHub con el mismo nombre. Formato en `.env`: `CLAVE=valor`, sin comillas ni espacios.

Herramienta de ayuda: comprueba lo que hay, imprime los ids que faltan y renueva tokens.

```powershell
python herramientas/comprobar_credenciales.py                    # revisa todo
python herramientas/comprobar_credenciales.py --oauth-pinterest  # obtiene el token de Pinterest
python herramientas/comprobar_credenciales.py --renovar-instagram
```

| Variable | Fase | Para qué | Caduca |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | 0 | Minero, Redactor, Guardián | No |
| `KAIZEN_FUENTES` | 0 | Ruta local de los manuscritos (solo en tu PC) | — |
| `TELEGRAM_BOT_TOKEN` | 1 | Bot de aprobación y publicación en canal | No |
| `TELEGRAM_CHAT_APROBACION` | 1 | Tu chat con el bot, donde llegan las previas | No |
| `TELEGRAM_CANAL` | 1 | Canal público de lectores | No |
| `PINTEREST_APP_ID`, `PINTEREST_APP_SECRET` | 1 | Identifican la app | No |
| `PINTEREST_REFRESH_TOKEN` | 1 | Renueva el access token solo | ~1 año |
| `PINTEREST_TOKEN` | 1 | Publicar pins | 30 días (se renueva solo si hay refresh token) |
| `PINTEREST_TABLERO_ID` | 1 | Tablero destino | No |
| `INSTAGRAM_TOKEN` | 1 | Publicar en Instagram | 60 días (renovar a mano) |
| `INSTAGRAM_CUENTA_ID` | 1 | Id de la cuenta profesional | No |
| `MAILERLITE_TOKEN` | 2 | Newsletter | No |
| `THREADS_TOKEN` | 2 | Publicar en Threads | 60 días |
| `BLUESKY_USUARIO`, `BLUESKY_APP_PASSWORD` | 2 | Publicar en Bluesky | No |
| `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_SECRET` | 2 | Publicar en X | No |
| `YOUTUBE_CLIENT_SECRET_JSON` | 2 | Subir Shorts | Token de refresco no caduca si la app está en producción |

---

## Fase 0

### ANTHROPIC_API_KEY

1. https://console.anthropic.com → crear cuenta o entrar (independiente de la suscripción de claude.ai).
2. **Settings → Billing → Add credits.** Mínimo 5 USD; 20 USD cubren el Minero completo (~4,4 USD) y meses de piezas (~2 USD/mes).
3. **Settings → Limits** → límite mensual de gasto (p. ej. 15 USD).
4. **Settings → API Keys → Create Key**, nombre `Promocion_IA`. Empieza por `sk-ant-`. Se muestra una sola vez.
5. Pegar en `.env`. Comprobar: `python herramientas/comprobar_credenciales.py` → «Anthropic: clave válida».

Estado: **hecha y verificada.**

### KAIZEN_FUENTES

Ruta de la carpeta que contiene `1.Neurodivergente`, `3.Numerologia`, etc. Solo en local; en GitHub no existe (los manuscritos no se suben). Ya rellena.

---

## Fase 1

### Telegram

**TELEGRAM_BOT_TOKEN**
1. En Telegram, abrir **@BotFather** → `/newbot`.
2. Nombre visible: `Kai Zen Editorial`. Usuario: libre, acabado en `bot` (p. ej. `kaizen_editorial_bot`).
3. BotFather devuelve el token, formato `123456789:AAF…`. Pegar.

**TELEGRAM_CHAT_APROBACION**
4. Buscar el bot en Telegram y enviarle cualquier mensaje.
5. Ejecutar `python herramientas/comprobar_credenciales.py`: imprime `TELEGRAM_CHAT_APROBACION=<número> (tu nombre)`. Pegar.
6. Volver a ejecutar: el bot envía «conexión correcta».

**TELEGRAM_CANAL** (opcional hasta que exista el canal)
7. Telegram → Nuevo canal → **público**; nombre p. ej. `Kai Zen · Libros`; enlace `t.me/kaizenlibros`.
8. Administradores del canal → añadir el bot → permiso «Publicar mensajes».
9. `TELEGRAM_CANAL=@kaizenlibros`. La herramienta confirma que el bot es administrador.

### Pinterest

Requisito: cuenta **de empresa** (Ajustes → Gestión de cuenta → Convertir en cuenta de empresa; gratis). Crear un tablero «Mente distinta».

1. https://developers.pinterest.com/apps/ → crear app: nombre `Promocion Kai Zen`, descripción «publicación de pins propios». Acceso **Trial** (inmediato; sirve para la cuenta propia).
2. Copiar **App ID** → `PINTEREST_APP_ID`; **App secret** → `PINTEREST_APP_SECRET`.
3. En la app, **Redirect URIs** → añadir exactamente `https://localhost/`.
4. Ejecutar `python herramientas/comprobar_credenciales.py --oauth-pinterest`. Da una URL: abrirla, autorizar; el navegador va a `https://localhost/?code=XXXX` (error de página, normal). Copiar el valor de `code` y pegarlo en la terminal.
5. La herramienta imprime `PINTEREST_REFRESH_TOKEN` y `PINTEREST_TOKEN`. Pegar ambos.
6. Ejecutar sin argumentos: lista los tableros con su id → `PINTEREST_TABLERO_ID`.

Renovación: automática. El Publicador pide un access token nuevo con el refresh token en cada corrida. Cuando el refresh token caduque (~1 año), repetir el paso 4.

### Instagram

Requisito: cuenta de Instagram **profesional** (Ajustes → Tipo de cuenta → Cambiar a profesional → **Creador**). Gratis. No hace falta página de Facebook con este método.

1. https://developers.facebook.com → Mis apps → **Crear app** → caso de uso «Otro» → tipo **Empresa**. Nombre `Promocion Kai Zen`.
2. Panel de la app → **Añadir producto → Instagram** → «API setup with Instagram business login».
3. **Generate access tokens → Add account**: iniciar sesión con la cuenta del sello y aceptar los permisos (`instagram_business_basic`, `instagram_business_content_publish`).
4. Junto a la cuenta aparece **Generate token**: copiar → `INSTAGRAM_TOKEN`.
5. Ejecutar la herramienta: imprime `INSTAGRAM_CUENTA_ID=…`. Pegar.

La app puede quedarse en **modo desarrollo**: para publicar en la cuenta propia no hace falta revisión de Meta.

Renovación: el token dura 60 días. Cada ~50 días:
```powershell
python herramientas/comprobar_credenciales.py --renovar-instagram
gh secret set INSTAGRAM_TOKEN
```
Pegar el nuevo token en `.env` y en GitHub. Solo se puede renovar un token que tenga más de 24 h y no haya caducado; si caduca, repetir el paso 4.

---

## Fase 2 (cuando existan los conectores)

### MAILERLITE_TOKEN
1. https://app.mailerlite.com → registro gratuito (500 suscriptores, 12.000 correos/mes).
2. **Integrations → MailerLite API → Generate new token**. Nombre `Promocion_IA`. Se muestra una vez.
3. Crear grupo «Kai Zen» y un formulario incrustado; el HTML del formulario va en `config/sellos/kaizen.yaml → newsletter.embed_html`.

### THREADS_TOKEN
1. En la misma app de Meta del paso de Instagram: **Añadir producto → Threads API**.
2. Permisos `threads_basic`, `threads_content_publish`. Añadir la cuenta de Threads como tester y aceptar la invitación en la app de Threads (Ajustes → Cuenta → Sitio web y permisos → Invitaciones).
3. Generar token de larga duración desde el panel (60 días; se renueva con `GET https://graph.threads.net/refresh_access_token`).

### BLUESKY_USUARIO y BLUESKY_APP_PASSWORD
1. Cuenta en https://bsky.app. `BLUESKY_USUARIO=kaizenlibros.bsky.social`.
2. **Settings → Privacy and security → App passwords → Add App Password**. Nombre `Promocion_IA`. Formato `xxxx-xxxx-xxxx-xxxx`. Nunca usar la contraseña real.

### X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET
1. https://developer.x.com → registrarse en la capa **Free** (solo escritura, cupo mensual reducido; comprobar el límite vigente).
2. Crear proyecto y app. **User authentication settings**: permisos **Read and write**, tipo «Web App, Automated App or Bot», callback `https://localhost/`.
3. **Keys and tokens**: API Key y Secret → `X_API_KEY`, `X_API_SECRET`. Generar **Access Token and Secret** (deben mostrar «Read and Write») → `X_ACCESS_TOKEN`, `X_ACCESS_SECRET`.

### YOUTUBE_CLIENT_SECRET_JSON
1. https://console.cloud.google.com → nuevo proyecto `Promocion Kai Zen`.
2. **APIs y servicios → Biblioteca → YouTube Data API v3 → Habilitar**.
3. **Pantalla de consentimiento OAuth**: tipo externo, añadir tu correo como usuario de prueba.
4. **Credenciales → Crear credenciales → ID de cliente OAuth → Aplicación de escritorio**. Descargar el JSON; pegar su contenido en una sola línea como valor de la variable.
5. La primera vez, el conector abrirá el navegador para autorizar y guardará el refresh token en `datos/` (excluido de git). Hasta verificar la app en Google, los vídeos subidos por API quedan **privados**; mientras tanto, subida manual.

---

## Pasar las claves a GitHub

Tras crear el repositorio (`gh repo create Promocion_IA --private --source=. --push`):

```powershell
# una a una
gh secret set ANTHROPIC_API_KEY

# todas las que estén rellenas en .env, menos la ruta local
Get-Content .env | Where-Object { $_ -match '^[A-Z_]+=.+' -and $_ -notmatch '^KAIZEN_FUENTES' } | ForEach-Object { $k,$v = $_ -split '=',2; gh secret set $k --body $v }

gh secret list
```

Los workflows ya declaran todas las variables de Fase 1 en `env:`. Las de Fase 2 se añadirán con sus conectores.

---

## Seguridad

- `.env` está en `.gitignore`. Comprobar siempre antes del primer commit: `git status` no debe listarlo.
- El repositorio vive en OneDrive, así que `.env` se sincroniza a la nube de Microsoft. Alternativa fuera de OneDrive: `C:\Users\d.zaplana\.promocion_ia.env`, mismo formato; el sistema lee los dos.
- Ninguna clave en el YAML, en el código ni en mensajes de commit. Si una clave se filtra: revocarla en su panel y generar otra; no basta con borrarla del fichero.
- Un bot de Telegram solo atiende al chat configurado en `TELEGRAM_CHAT_APROBACION`; los mensajes de otros chats se ignoran.
- Límite de gasto en la consola de Anthropic: la única factura variable del sistema.


## Azure Speech (voz HD del pódcast, opcional)

Sin clave, el pódcast usa Edge TTS (gratis, sin cuenta). Con clave usa la **misma voz en versión HD** de Azure, bastante más natural. Gratis hasta 500.000 caracteres al mes (unos 100 episodios); hace falta una cuenta de Azure con tarjeta, pero el nivel F0 no cobra.

1. https://portal.azure.com → crea una cuenta (o entra) → «Crear un recurso» → busca **Speech** (Servicios de voz) → Crear.
2. Suscripción: la gratuita. Grupo de recursos: nuevo, `kaizen`. Región: **West Europe** (`westeurope`) o **Sweden Central** (`swedencentral`), que son las que tienen voces HD en Europa. Plan de tarifa: **Free F0**.
3. Cuando esté creado: «Claves y punto de conexión» → copia **CLAVE 1** y la **Región**.
4. En `.env`:
```
AZURE_SPEECH_KEY=…
AZURE_SPEECH_REGION=westeurope
```
5. `python herramientas/comprobar_credenciales.py` te dice qué voces HD en español hay en tu región. Después, subir los dos secrets al repo con `gh secret set`.

Si la voz HD (`podcast.voz_azure` en el YAML) no existe en tu región, el Locutor lo detecta y graba con Edge TTS: el episodio sale igual.


## Gemini TTS (voz del pódcast, gratis)

Voz dirigida por instrucciones («acento castellano, cálida, ritmo tranquilo»), nivel gratuito de Google AI Studio (pocas peticiones al día; un episodio es una). Sin tarjeta.

1. https://aistudio.google.com → «Get API key» → «Create API key in new project». La clave empieza por `AQ.` (las antiguas por `AIza`).
2. `.env`: `GEMINI_API_KEY=…` y subirla al repo: `gh secret set GEMINI_API_KEY --body "$GEMINI_API_KEY"`.
3. Voz, modelo e instrucción de estilo en `config/sellos/kaizen.yaml` → `podcast.voz_gemini`, `modelo_gemini`, `estilo_gemini`.
4. `python herramientas/comprobar_credenciales.py` confirma la clave y lista los modelos de voz.

En el nivel gratuito Google puede usar los textos enviados para mejorar sus modelos: solo se envían guiones que ya se publican. Si la cuota se agota o el modelo en preview cambia, el Locutor graba con Edge TTS (Elvira).
