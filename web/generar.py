"""Generador estático de la web del sello.

    python -m web.generar [--sello kaizen] [--salida web/dist] [--base-url /Promocion_IA/]

Todo sale del YAML del sello, de la paleta extraída de las portadas y de los artículos en
web/contenido/blog/*.md. Sin JavaScript obligatorio, sin dependencias externas en el navegador.
Páginas: inicio, una por serie (mapa de lectura, itinerarios), una por libro, «enlaces» (para la
bio de redes), blog, redirecciones /ir/<slug>/ y sitemap.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import quote_plus

import markdown
import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape

from agentes.config import DIR_CONFIG, RAIZ_REPO, Libro, Sello, Serie, cargar_sello, consola_utf8

DIR_WEB = RAIZ_REPO / "web"
DIR_PLANTILLAS = DIR_WEB / "plantillas"
DIR_ESTATICO = DIR_WEB / "static"
DIR_BLOG = DIR_WEB / "contenido" / "blog"

PALETA_POR_DEFECTO = {
    "dominante": "#3f5a4c", "acento": "#c9773a", "texto_sobre_dominante": "#fafaf9",
    "fondo_claro": "#faf7f2", "tinta": "#1c1917",
}


@dataclass
class Post:
    slug: str
    titulo: str
    fecha: date
    resumen: str
    serie: str | None
    libro: str | None
    html: str

    @property
    def ruta(self) -> str:
        return f"blog/{self.slug}/"


def slugificar(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[áàä]", "a", s); s = re.sub(r"[éèë]", "e", s); s = re.sub(r"[íìï]", "i", s)
    s = re.sub(r"[óòö]", "o", s); s = re.sub(r"[úùü]", "u", s); s = s.replace("ñ", "n")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


def cargar_posts() -> list[Post]:
    posts: list[Post] = []
    if not DIR_BLOG.exists():
        return posts
    for ruta in sorted(DIR_BLOG.glob("*.md")):
        texto = ruta.read_text(encoding="utf-8")
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", texto, re.S)
        if not m:
            continue  # sin front matter no es un artículo (p. ej. LEEME.md)
        meta = yaml.safe_load(m.group(1)) or {}
        if "titulo" not in meta or "fecha" not in meta:
            continue
        cuerpo = markdown.markdown(m.group(2), extensions=["extra", "sane_lists", "toc"])
        fecha = meta["fecha"] if isinstance(meta["fecha"], date) else date.fromisoformat(str(meta["fecha"]))
        posts.append(Post(
            slug=meta.get("slug") or slugificar(meta["titulo"]),
            titulo=meta["titulo"], fecha=fecha, resumen=meta.get("resumen", ""),
            serie=meta.get("serie"), libro=meta.get("libro"), html=cuerpo,
        ))
    posts.sort(key=lambda p: p.fecha, reverse=True)
    return posts


def cargar_paleta(serie_id: str) -> dict:
    ruta = DIR_CONFIG / "paletas" / f"{serie_id}.json"
    if ruta.exists():
        return {**PALETA_POR_DEFECTO, **json.loads(ruta.read_text(encoding="utf-8"))}
    return dict(PALETA_POR_DEFECTO)


def limpiar_directorio(ruta: Path, intentos: int = 5) -> None:
    """Vacía el directorio de salida. En OneDrive/Windows el borrado de carpetas puede fallar
    mientras se sincroniza: se reintenta y, si sigue fallando, se borran solo los ficheros."""
    import os
    import time

    if not ruta.exists():
        return
    for i in range(intentos):
        try:
            shutil.rmtree(ruta)
            return
        except PermissionError:
            time.sleep(0.4 * (i + 1))
    for base, _dirs, ficheros in os.walk(ruta):
        for f in ficheros:
            try:
                (Path(base) / f).unlink()
            except PermissionError:
                pass


class Generador:
    def __init__(self, sello: Sello, salida: Path, base_url: str):
        self.sello = sello
        self.salida = salida
        self.base_url = base_url if base_url.endswith("/") else base_url + "/"
        self.env = Environment(loader=FileSystemLoader(DIR_PLANTILLAS), autoescape=select_autoescape(["html"]))
        self.posts = cargar_posts()
        self.paletas = {s.id: cargar_paleta(s.id) for s in sello.series_activas()}
        primera = sello.series_activas()[0].id if sello.series_activas() else None
        self.paleta_sello = self.paletas.get(primera, PALETA_POR_DEFECTO)
        self.enlaces_base = (sello.datos.get("enlaces", {}) or {}).get("base_url", "").rstrip("/")
        self.ruta_podcast = sello.datos.get("podcast", {}).get("ruta_web", "static/podcast").strip("/")
        ruta_eps = DIR_WEB / self.ruta_podcast / "episodios.json"
        self.episodios = json.loads(ruta_eps.read_text(encoding="utf-8")) if ruta_eps.exists() else []
        self.env.globals.update(
            u=self.u, sello=sello.datos["sello"], series=sello.series_activas(), posts=self.posts,
            hay_blog=bool(self.posts), hay_podcast=bool(self.episodios), podcast=sello.datos.get("podcast", {}),
            episodios=self.episodios, ruta_podcast=self.ruta_podcast,
            anio=date.today().year, newsletter=sello.datos.get("newsletter", {}),
            canales=sello.datos.get("canales", {}), enlace_compra=self.enlace_compra,
            portada=self.portada, serie_slug=self.serie_slug, paleta=self.paleta_sello,
        )

    # ---- utilidades de plantilla -------------------------------------------
    def u(self, ruta: str = "") -> str:
        return self.base_url + ruta.lstrip("/")

    @staticmethod
    def serie_slug(serie: Serie) -> str:
        return serie.id.replace("_", "-")

    def portada(self, libro: Libro) -> str | None:
        if (DIR_ESTATICO / "portadas" / f"{libro.slug}.jpg").exists():
            return self.u(f"static/portadas/{libro.slug}.jpg")
        return None

    def enlace_compra(self, libro: Libro, canal: str = "web") -> str:
        if self.enlaces_base:
            return f"{self.enlaces_base}/{libro.slug}?c={canal}"
        return self.u(f"ir/{libro.slug}/?c={canal}")

    def url_amazon(self, libro: Libro, tienda: str, canal: str = "web") -> str:
        utm = f"utm_source={canal}&utm_medium=web&utm_campaign={libro.slug}"
        if libro.asin_ebook:
            return f"https://www.{tienda}/dp/{libro.asin_ebook}?{utm}"
        q = quote_plus(f"{libro.titulo} {self.sello.datos['sello']['autor_amazon']}")
        return f"https://www.{tienda}/s?k={q}&i=digital-text&{utm}"

    # ---- escritura -----------------------------------------------------------
    def escribir(self, ruta_rel: str, plantilla: str, **ctx) -> None:
        destino = self.salida / ruta_rel
        destino.parent.mkdir(parents=True, exist_ok=True)
        html = self.env.get_template(plantilla).render(**ctx)
        destino.write_text(html, encoding="utf-8")
        self.rutas.append(ruta_rel)

    def generar(self) -> list[str]:
        self.rutas: list[str] = []
        limpiar_directorio(self.salida)
        self.salida.mkdir(parents=True, exist_ok=True)
        if DIR_ESTATICO.exists():
            shutil.copytree(DIR_ESTATICO, self.salida / "static", dirs_exist_ok=True)
        (self.salida / "static").mkdir(exist_ok=True)
        (self.salida / "static" / "variables.css").write_text(self.css_variables(), encoding="utf-8")

        self.escribir("index.html", "index.html", titulo=self.sello.nombre)
        self.escribir("enlaces/index.html", "enlaces.html", titulo=f"Enlaces · {self.sello.nombre}")
        self.escribir("404.html", "404.html", titulo="Página no encontrada")
        for s in self.sello.series_activas():
            pal = self.paletas[s.id]
            self.escribir(f"series/{self.serie_slug(s)}/index.html", "serie.html",
                          titulo=f"{s.nombre_amazon} · {self.sello.nombre}", serie=s, paleta=pal,
                          posts_serie=[p for p in self.posts if p.serie == s.id])
            for lib in s.libros:
                tiendas = self.sello.datos["amazon"]["marketplaces"]
                self.escribir(f"libros/{lib.slug}/index.html", "libro.html",
                              titulo=f"{lib.titulo} · {self.sello.nombre}", serie=s, libro=lib, paleta=pal,
                              siguiente=next((l for l in s.libros if l.numero == lib.numero + 1), None),
                              anterior=next((l for l in s.libros if l.numero == lib.numero - 1), None),
                              posts_libro=[p for p in self.posts if p.libro == lib.slug])
                por_defecto = self.sello.datos["amazon"]["por_defecto"]
                alternativas = sorted({t for t in tiendas.values() if t != por_defecto})
                self.escribir(f"ir/{lib.slug}/index.html", "ir.html", titulo=f"Ir a {lib.titulo}",
                              libro=lib, destino=self.url_amazon(lib, por_defecto), tienda=por_defecto,
                              alternativas=[(t, self.url_amazon(lib, t)) for t in alternativas])
        if self.episodios:
            self.escribir("podcast/index.html", "podcast.html", titulo=f"{self.sello.datos.get('podcast', {}).get('titulo', 'Pódcast')} · {self.sello.nombre}")
        if self.posts:
            self.escribir("blog/index.html", "blog_index.html", titulo=f"Blog · {self.sello.nombre}")
            for p in self.posts:
                self.escribir(f"{p.ruta}index.html", "post.html", titulo=f"{p.titulo} · {self.sello.nombre}", post=p)
        self.sitemap()
        (self.salida / "robots.txt").write_text(
            f"User-agent: *\nAllow: /\nSitemap: {self.sitio_absoluto()}sitemap.xml\n", encoding="utf-8")
        (self.salida / ".nojekyll").write_text("", encoding="utf-8")
        return self.rutas

    def sitio_absoluto(self) -> str:
        web = self.sello.datos["sello"].get("web", "").rstrip("/")
        return (web + "/") if web else self.base_url

    def sitemap(self) -> None:
        base = self.sitio_absoluto()
        urls = [base + r.removesuffix("index.html") for r in self.rutas if not r.startswith(("ir/", "404"))]
        xml = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
        xml += [f"  <url><loc>{u}</loc></url>" for u in urls]
        xml.append("</urlset>")
        (self.salida / "sitemap.xml").write_text("\n".join(xml), encoding="utf-8")

    def css_variables(self) -> str:
        p = self.paleta_sello
        lineas = [":root{", f"  --dominante:{p['dominante']};", f"  --acento:{p['acento']};",
                  f"  --sobre-dominante:{p['texto_sobre_dominante']};", f"  --fondo:{p['fondo_claro']};",
                  f"  --tinta:{p['tinta']};", "}"]
        for sid, pal in self.paletas.items():
            lineas += [f".serie-{sid.replace('_', '-')}{{", f"  --dominante:{pal['dominante']};",
                       f"  --acento:{pal['acento']};", f"  --sobre-dominante:{pal['texto_sobre_dominante']};", "}"]
        return "\n".join(lineas) + "\n"


def main(argv: list[str] | None = None) -> int:
    consola_utf8()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sello", default="kaizen")
    p.add_argument("--salida", type=Path, default=DIR_WEB / "dist")
    p.add_argument("--base-url", default="/")
    a = p.parse_args(argv)
    sello = cargar_sello(a.sello)
    rutas = Generador(sello, a.salida, a.base_url).generar()
    print(f"{len(rutas)} páginas en {a.salida} (base {a.base_url})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
