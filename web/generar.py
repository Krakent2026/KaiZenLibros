"""Generador estático de la web del sello.

    python -m web.generar [--sello kaizen] [--salida web/dist] [--base-url /Promocion_IA/]

Todo sale del YAML del sello, de la paleta extraída de las portadas y de los artículos en
web/contenido/blog/*.md. Sin JavaScript obligatorio, sin dependencias externas en el navegador.
Páginas: inicio, una por serie (mapa de lectura, itinerarios), una por libro, «enlaces» (para la
bio de redes), blog, redirecciones /ir/<slug>/ y sitemap.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import quote_plus

import markdown
import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from agentes.config import DB_POR_DEFECTO, DIR_CONFIG, RAIZ_REPO, Libro, Sello, Serie, cargar_sello, consola_utf8

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


# ---- gráficos de una línea (el lenguaje de las portadas) ------------------------------
def hilo_path() -> str:
    """Ovillo que se deshace en una recta: el hilo rojo de las portadas, para la cabecera de inicio (viewBox 600×240)."""
    pts = []
    cx, cy = 175, 125
    for i in range(361):
        t = i / 360 * 5.6 * math.pi
        r = 5 + 24 * t / (2 * math.pi)
        pts.append((cx + 1.15 * r * math.cos(t), cy + 0.95 * r * math.sin(t)))
    d = f"M{pts[0][0]:.1f},{pts[0][1]:.1f} " + " ".join(f"L{x:.1f},{y:.1f}" for x, y in pts[1:])
    fx, fy = pts[-1]
    d += f" C{fx+40:.1f},{fy-30:.1f} {fx+60:.1f},{fy+40:.1f} {fx+110:.1f},{fy-6:.1f}"
    d += f" C{fx+150:.1f},{fy-40:.1f} {fx+170:.1f},{fy+8:.1f} {fx+210:.1f},{fy-4:.1f} L420,{fy-4:.1f}"
    return d, f"{fy-4:.1f}"


# Un dibujo por serie (viewBox 150×60): trazo principal, trazo rojo, punto final.
MOTIVOS = {
    "mente_distinta": ("M4,40 C20,10 30,50 46,30 S70,10 84,32 S110,48 124,28", "M124,28 L146,28", (146, 28)),
    "crecimiento_personal": ("M4,52 H30 V44 H56 V36 H82 V28 H108 V20 H134", "M134,20 V12", (134, 10)),
    "los_mensajeros": ("M4,42 H146 M52,42 A23,23 0 0 1 98,42", "", (75, 30)),
    "numeros_del_alma": ("M10,48 L40,14 L70,48 L100,14 L130,48", "M130,48 L146,48", (146, 48)),
    "espiritualidad_sin_doctrina": ("M4,30 H100", "M100,30 C115,30 120,20 130,20 S146,30 146,30", (146, 30)),
}


def motivo_svg(serie_id: str, clase: str = "motivo") -> Markup:
    trazo, rojo, (px, py) = MOTIVOS.get(serie_id, ("M4,30 H124", "M124,30 H146", (146, 30)))
    rojo_svg = f'<path class="rojo" d="{rojo}"/>' if rojo else ""
    return Markup(f'<svg class="{clase}" viewBox="0 0 150 60" aria-hidden="true" focusable="false">'
                  f'<path d="{trazo}"/>{rojo_svg}<circle class="punto" cx="{px}" cy="{py}" r="2.4"/></svg>')


def cabecera_svg(semilla: str, fondo: str, trazo: str, acento: str = "#c8553d") -> Markup:
    """Cabecera de artículo generada a partir del título: siempre la misma para el mismo texto, distinta entre artículos."""
    rnd = random.Random(int(hashlib.sha1(semilla.encode("utf-8")).hexdigest(), 16))
    w, h = 800, 200
    lineas = []
    for k in range(rnd.randint(2, 3)):
        y0 = rnd.uniform(60, 150)
        d = f"M0,{y0:.0f}"
        x = 0
        while x < w:
            paso = rnd.uniform(90, 180)
            d += f" C{x+paso*0.35:.0f},{rnd.uniform(30,170):.0f} {x+paso*0.65:.0f},{rnd.uniform(30,170):.0f} {x+paso:.0f},{rnd.uniform(50,160):.0f}"
            x += paso
        op = 0.95 if k == 0 else rnd.uniform(0.35, 0.6)
        lineas.append(f'<path d="{d}" opacity="{op:.2f}"/>')
    px, py = rnd.uniform(480, 720), rnd.uniform(60, 140)
    return Markup(f'<svg class="cabecera-post" viewBox="0 0 {w} {h}" preserveAspectRatio="xMidYMid slice" aria-hidden="true">'
                  f'<rect width="{w}" height="{h}" fill="{fondo}"/><g fill="none" stroke="{trazo}" stroke-width="1.4" stroke-linecap="round">'
                  f'{"".join(lineas)}</g><circle cx="{px:.0f}" cy="{py:.0f}" r="3.2" fill="{acento}"/></svg>')


def cita_del_dia(sello: Sello, ruta_db: Path = DB_POR_DEFECTO) -> dict | None:
    """Una cita literal verificada, elegida por la fecha: cambia cada día sin que nadie la toque."""
    if not ruta_db.exists():
        return None
    activas = {s.id for s in sello.series_activas()}
    try:
        con = sqlite3.connect(f"file:{ruta_db}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        filas = con.execute(
            """SELECT a.texto, l.titulo, l.slug, l.serie FROM atomos a JOIN libros l ON l.id = a.libro_id
               WHERE a.tipo = 'cita' AND a.verificado = 1 AND a.es_literal = 1
                 AND length(a.texto) BETWEEN 50 AND 150 ORDER BY a.id""").fetchall()
        con.close()
    except sqlite3.Error:
        return None
    filas = [f for f in filas if f["serie"] in activas]
    if not filas:
        return None
    f = filas[date.today().toordinal() % len(filas)]
    return {"texto": f["texto"].strip().rstrip("."), "libro": f["titulo"], "slug": f["slug"], "serie": f["serie"]}


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
        s = sello.datos["sello"]
        self.env.globals.update(
            redes={k: v for k, v in (s.get("redes") or {}).items() if v}, sobre=s.get("sobre", {"entrada": "", "secciones": []}),
            otras_series=[x for x in sello.series.values() if not x.activa], sitio=self.sitio_absoluto(),
            u=self.u, sello=sello.datos["sello"], series=sello.series_activas(), posts=self.posts,
            hay_blog=bool(self.posts), hay_podcast=bool(self.episodios), podcast=sello.datos.get("podcast", {}),
            episodios=self.episodios, ruta_podcast=self.ruta_podcast,
            anio=date.today().year, newsletter=sello.datos.get("newsletter", {}),
            canales=sello.datos.get("canales", {}), enlace_compra=self.enlace_compra,
            portada=self.portada, serie_slug=self.serie_slug, paleta=self.paleta_sello,
            hilo=hilo_path(), motivo=motivo_svg, cabecera_post=self.cabecera_post, cita_dia=cita_del_dia(sello),
            libros_cinta=[l for s_ in sello.series_activas() for l in sorted(s_.libros, key=lambda x: x.numero)[:8]],
        )

    # ---- utilidades de plantilla -------------------------------------------
    def u(self, ruta: str = "") -> str:
        return self.base_url + ruta.lstrip("/")

    @staticmethod
    def serie_slug(serie: Serie) -> str:
        return serie.id.replace("_", "-")

    def portada(self, libro: Libro) -> str | None:
        for ext in ("webp", "jpg"):
            if (DIR_ESTATICO / "portadas" / f"{libro.slug}.{ext}").exists():
                return self.u(f"static/portadas/{libro.slug}.{ext}")
        return None

    def cabecera_post(self, post: "Post") -> Markup:
        pal = self.paletas.get(post.serie or "", self.paleta_sello)
        return cabecera_svg(post.titulo, pal["acento"], pal["dominante"])

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
            # las portadas .jpg solo las usa el Diseñador; la web sirve los .webp
            def _ignorar(carpeta, nombres):
                return {n for n in nombres if n.endswith(".jpg")} if Path(carpeta).name == "portadas" else set()
            shutil.copytree(DIR_ESTATICO, self.salida / "static", dirs_exist_ok=True, ignore=_ignorar)
        (self.salida / "static").mkdir(exist_ok=True)
        (self.salida / "static" / "variables.css").write_text(self.css_variables(), encoding="utf-8")

        self.escribir("index.html", "index.html", titulo=self.sello.nombre)
        self.escribir("sobre/index.html", "sobre.html", titulo=f"Sobre {self.sello.nombre}")
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
