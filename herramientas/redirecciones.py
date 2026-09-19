"""Genera un árbol de redirecciones para el alojamiento antiguo (GitHub Pages) hacia el dominio nuevo.

    python herramientas/redirecciones.py --dist web/dist --salida web/dist_redirect --destino https://kaizenlibros.com

Por cada página de `dist` escribe una página mínima con <meta refresh> y <link rel=canonical> al mismo camino en el
dominio nuevo. Copia además el feed del pódcast y episodios.json (que ya apuntan al dominio nuevo) para que las apps
suscritas a la URL antigua sigan recibiendo episodios mientras se cambia la URL en Spotify.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from html import escape
from pathlib import Path

PLANTILLA = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<title>Redirigiendo…</title><link rel="canonical" href="{destino}">
<meta http-equiv="refresh" content="0; url={destino}"><meta name="robots" content="noindex">
<style>body{{font-family:Georgia,serif;padding:3rem 1.2rem;max-width:40rem;margin:0 auto;color:#1c1917;background:#faf7f2}}</style>
</head><body><p>Esta página se ha movido a <a href="{destino}">{destino_texto}</a>.</p></body></html>
"""


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dist", type=Path, default=Path("web/dist"))
    p.add_argument("--salida", type=Path, default=Path("web/dist_redirect"))
    p.add_argument("--destino", required=True, help="dominio nuevo, p. ej. https://kaizenlibros.com")
    a = p.parse_args(argv)
    destino = a.destino.rstrip("/")
    if a.salida.exists():
        shutil.rmtree(a.salida, ignore_errors=True)
    n = 0
    for html in a.dist.rglob("*.html"):
        rel = html.relative_to(a.dist)
        camino = "/" + rel.as_posix().removesuffix("index.html")
        if rel.name == "404.html":
            camino = "/"
        url = destino + camino
        salida = a.salida / rel
        salida.parent.mkdir(parents=True, exist_ok=True)
        salida.write_text(PLANTILLA.format(destino=escape(url), destino_texto=escape(url.removeprefix("https://"))), encoding="utf-8")
        n += 1
    for extra in ("static/podcast/feed.xml", "static/podcast/episodios.json", "robots.txt", ".nojekyll"):
        origen = a.dist / extra
        if origen.exists():
            (a.salida / extra).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origen, a.salida / extra)
    (a.salida / ".nojekyll").write_text("", encoding="utf-8")
    print(f"{n} redirecciones en {a.salida} → {destino}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
