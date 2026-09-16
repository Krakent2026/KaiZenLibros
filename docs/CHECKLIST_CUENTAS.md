# Checklist de cuentas y accesos (Fase 0, tarea manual)

Todo gratuito. Marcar y anotar el usuario final en `config/sellos/kaizen.yaml` → `canales`.

## 1. Nombre de usuario

Comprobar que el mismo nombre está libre en todos los sitios antes de registrar ninguno. Candidatos: `kaizenlibros`, `kaizen.libros`, `librosdekaizen`. Evitar `kaizen` a secas (marca genérica, colisiona con consultoría y productividad).

| Plataforma | Tipo de cuenta | Usuario | Hecho |
|---|---|---|---|
| Instagram | **Profesional → Creador** (necesario para la API) | | ☐ |
| Facebook | Página (no perfil). Enlazar con la cuenta de Instagram | | ☐ |
| Threads | Se crea desde la cuenta de Instagram | | ☐ |
| Pinterest | **Cuenta de empresa** (Business); crear tableros por serie | | ☐ |
| YouTube | Canal de marca (no personal) | | ☐ |
| TikTok | Cuenta normal; pasar a «Empresa» si se pide la API | | ☐ |
| Bluesky | Cuenta normal; crear **app password** (Settings → App passwords) | | ☐ |
| X | Cuenta normal + portal de desarrolladores (capa gratuita) | | ☐ |
| Telegram | Canal público de lectores + bot con @BotFather (para aprobación) | | ☐ |
| MailerLite | Plan gratuito (500 suscriptores). Crear grupo «Kai Zen» y formulario incrustado | | ☐ |
| Spotify for Creators | Para el pódcast (Fase 2). Se puede dejar | | ☐ |
| Cloudflare | Cuenta gratuita para el Worker de enlaces | | ☐ |
| GitHub | Repositorio privado `Promocion_IA` | | ☐ |
| Dominio (opcional) | ~10 €/año. Sugerencia: `kaizenlibros.com` o `.es` | | ☐ |

## 2. Accesos de API que tardan días (arrancar ya)

| Trámite | Dónde | Qué pedir | Nota |
|---|---|---|---|
| App de Meta | developers.facebook.com → Crear app → Empresa | Producto **Instagram** (API con inicio de sesión de Instagram) y **Threads API** | Permisos: `instagram_business_basic`, `instagram_business_content_publish`, `threads_basic`, `threads_content_publish`. Para uso en cuenta propia basta el modo desarrollo con la cuenta como tester |
| Pinterest | developers.pinterest.com → Crear app | Acceso de prueba (trial) | Permite publicar en la cuenta propia; el acceso estándar requiere revisión gratuita |
| Google Cloud | console.cloud.google.com | Proyecto + YouTube Data API v3 + credenciales OAuth (app de escritorio) | Hasta verificar la app, los vídeos subidos por API quedan privados; publicar a mano mientras tanto |
| X Developer | developer.x.com | Capa gratuita | Solo escritura, cupo mensual reducido; comprobar el límite vigente |
| TikTok for Developers | developers.tiktok.com | Content Posting API | Sin auditoría, publica en privado. Semiautomático hasta entonces |

## 3. Amazon (no requiere cuentas nuevas)

- Author Central: biografía de sello, foto o logotipo, enlace a la web.
- KDP: comprobar que los 12 títulos de *Mente distinta* están en **KDP Select** (imprescindible para días gratis y ofertas relámpago).
- Anotar los **ASIN** de ebook y papel en `config/sellos/kaizen.yaml` y regenerar enlaces y web.
- Amazon Afiliados (opcional): alta en amazon.es y amazon.com; leer las condiciones sobre enlazar libros propios en cada país antes de rellenar `amazon.afiliados`.

## 4. Secretos a guardar

Una vez obtenidos, en local en `.env` y en GitHub con `gh secret set NOMBRE`: los nombres están en `.env.example`. Nunca en el YAML ni en el código.
