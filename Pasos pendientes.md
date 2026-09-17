Sincronizado con GitHub: el workflow publicó la pieza #2 anoche (Telegram + Instagram); hoy salen la #3 (12:30) y la #4 (19:00) solas. Herramienta de comprobación ampliada a Bluesky y Threads.

2. Alta del pódcast

Cuándo: a partir del miércoles 23, cuando el feed tenga su primer episodio. Spotify y Apple rechazan feeds vacíos.

Antes (hoy, 1 minuto): Apple exige un correo del propietario dentro del feed. Abre config/sellos/kaizen.yaml, sección podcast, y pon email: "tu-correo". Será visible en el feed público; vale uno del sello. Guarda; lo subo yo o haces git commit+push.

Spotify for Creators (gratis, 10 min):
1. https://creators.spotify.com → Empezar → inicia sesión con una cuenta de Spotify (o créala).
2. «Ya tengo un pódcast» → Añadir con RSS.
3. Pega el feed: https://krakent2026.github.io/KaiZenLibros/static/podcast/feed.xml
4. Te envía un código al correo que figura en el feed. Introdúcelo.
5. Revisa nombre, categoría e idioma (vienen del feed) → Enviar. Aparece en Spotify en 24-48 h. Los episodios nuevos entran solos cada vez que el feed cambia.

Apple Podcasts Connect (gratis, 15 min + revisión de 1-5 días):
1. https://podcastsconnect.apple.com → inicia sesión con un Apple ID (si no tienes, créalo en appleid.apple.com).
2. Botón + → Añadir programa → «Añadir un programa con feed RSS».
3. Pega la misma URL del feed → Añadir. Comprueba que lee la portada (3000×3000, ya generada) y el episodio.
4. Enviar para revisión. Apple valida el feed; si algo falla, lo indica en la misma pantalla.

Otras plataformas que leen el mismo feed sin trámite: Pocket Casts, Overcast, Amazon Music for Podcasters (https://podcasters.amazon.com, alta con RSS, gratis).

3. Bluesky y Threads

Bluesky (5 min, sin trámite):
1. https://bsky.app → Crear cuenta. Usuario: kaizenlibros (queda kaizenlibros.bsky.social). Correo y contraseña normales.
2. Rellena perfil: nombre «Kai Zen · Libros», bio con la frase paraguas y enlace https://krakent2026.github.io/KaiZenLibros/enlaces/.
3. Ajustes → Privacidad y seguridad → Contraseñas de aplicación → Añadir. Nombre Promocion_IA. Copia la contraseña (formato xxxx-xxxx-xxxx-xxxx); se muestra una vez.
4. En .env:
BLUESKY_USUARIO=kaizenlibros.bsky.social
BLUESKY_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
5. Dime «ejecuta» y compruebo la sesión y subo los secrets.

Threads (10 min, en la misma app de Meta que Instagram):
1. Abre la app de Threads en el móvil con la cuenta del sello (se crea desde Instagram si no existe: perfil de Instagram → Threads).
2. https://developers.facebook.com/apps → tu app Promocion Kai Zen → Casos de uso → Añadir caso de uso → «Acceder a la API de Threads» (o Añadir producto → Threads).
3. Dentro del caso de uso → Personalizar: activa los permisos threads_basic y threads_content_publish.
4. Roles de la app → Roles → Añadir personas → Probador de Threads → tu usuario de Threads → Añadir.
5. En la app de Threads: Configuración → Cuenta → Sitios web y permisos → Invitaciones → Aceptar la invitación.
6. Vuelve al panel → caso de uso Threads → Generar tokens de acceso → Añadir cuenta → inicia sesión → Generar token. Es de larga duración (60 días).
7. .env: THREADS_TOKEN=… y dime «ejecuta».

Renovación del token de Threads: cada 60 días, igual que Instagram (te avisará el Bibliotecario cuando lo añada a su lista; lo hago en Fase 3).

4. Pinterest (30 min)

Cuenta y tablero:
1. https://pinterest.es → cuenta nueva de empresa (en el registro: «Crear una cuenta de empresa») o convierte una existente: Ajustes → Gestión de cuenta → Convertir en cuenta de empresa. Gratis.
2. Usuario kaizenlibros. Perfil con enlace a la web.
3. Crea un tablero «Mente distinta» (público).

App de desarrollador:
4. https://developers.pinterest.com/apps/ → Connect app → nombre Promocion Kai Zen, descripción «Publicación de pins de mis propios libros», sitio web la URL del sello.
5. En la app: copia App ID y App secret → .env:
PINTEREST_APP_ID=…
PINTEREST_APP_SECRET=…
6. En la misma pantalla, Redirect URIs → añade exactamente https://localhost/ → Guardar.
7. Acceso: aparece como Trial. Basta para tu cuenta.

Token (este paso lo ejecutas tú, porque pide pegar un código):
8. En la terminal de Claude Code escribe:
! python herramientas/comprobar_credenciales.py --oauth-pinterest
9. Te da una URL. Ábrela en el navegador con la cuenta de Pinterest, Autorizar. El navegador irá a https://localhost/?code=XXXX y mostrará error de página: normal. Copia el valor de code de la barra de direcciones y pégalo en la terminal.
10. Imprime PINTEREST_REFRESH_TOKEN= y PINTEREST_TOKEN=. Pégalos en .env.
11. Dime «ejecuta»: listo los tableros con su id, guardo PINTEREST_TABLERO_ID y subo los cinco secrets.

El access token caduca a los 30 días; el sistema lo renueva solo con el refresh token (válido un año).

Orden sugerido

Bluesky hoy (5 min, cero fricción) → Threads (ya tienes la app de Meta) → Pinterest → el 23, alta del pódcast.