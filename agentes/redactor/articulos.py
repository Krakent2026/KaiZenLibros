"""Redactor de artículos para el blog: átomos verificados de un libro → artículo Markdown con cabecera.

    python -m agentes.redactor.articulos --libro no-es-pereza          # un artículo de ese libro
    python -m agentes.redactor.articulos --n 4                          # cuatro artículos, libros menos cubiertos primero
    python -m agentes.redactor.articulos --libro dopamina --tema motivación

Guardas: citas «…» solo de átomos literales (verificación exacta), vocabulario vetado con negación,
límites de longitud. Los ficheros salen en web/contenido/blog/ y la web los publica en el siguiente push.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import date
from pathlib import Path
from typing import Any

from agentes import db
from agentes.config import DB_POR_DEFECTO, RAIZ_REPO, Sello, cargar_sello, consola_utf8
from agentes.guardian.reglas import bloquea, revisar
from agentes.guardian.verificar_citas import normalizar
from agentes.ia import ClienteIA, cliente_para

RUTA_PROMPT = Path(__file__).with_name("prompt_articulo.md")
DIR_BLOG = RAIZ_REPO / "web" / "contenido" / "blog"
ESQUEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"titulo": {"type": "string"}, "slug": {"type": "string"}, "resumen": {"type": "string"},
                   "cuerpo_markdown": {"type": "string"}},
    "required": ["titulo", "slug", "resumen", "cuerpo_markdown"],
    "additionalProperties": False,
}
TIPOS = ("herramienta", "microleccion", "dato_honesto", "contraste", "cita", "escena", "pregunta")


def slugificar(s: str) -> str:
    s = s.lower()
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ñ", "n"), ("ü", "u")):
        s = s.replace(a, b)
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:60]


def libros_menos_cubiertos(con: sqlite3.Connection, serie_id: str) -> list[str]:
    cubiertos = {m.group(1) for f in DIR_BLOG.glob("*.md") for m in [re.search(r"^libro:\s*(\S+)", f.read_text(encoding="utf-8"), re.M)] if m}
    filas = con.execute("SELECT slug FROM libros WHERE serie = ? ORDER BY numero", (serie_id,)).fetchall()
    return sorted((f["slug"] for f in filas), key=lambda s: (s in cubiertos, s))


def elegir_atomos(con: sqlite3.Connection, libro_id: str, n: int = 8, tema: str | None = None) -> list[sqlite3.Row]:
    filas = con.execute(
        """SELECT * FROM atomos WHERE libro_id = ? AND verificado = 1
           ORDER BY CASE tipo WHEN 'herramienta' THEN 0 WHEN 'microleccion' THEN 1 WHEN 'dato_honesto' THEN 2 WHEN 'cita' THEN 3 ELSE 4 END,
                    RANDOM()""", (libro_id,)).fetchall()
    if tema:
        t = normalizar(tema)
        con_tema = [f for f in filas if t in normalizar(f["texto"] + " " + (f["temas"] or "") + " " + (f["capitulo"] or ""))]
        filas = con_tema + [f for f in filas if f not in con_tema]
    # equilibrio: al menos una herramienta, una cita literal y un dato honesto si existen
    elegidos: list[sqlite3.Row] = []
    for tipo in ("herramienta", "cita", "dato_honesto"):
        c = next((f for f in filas if f["tipo"] == tipo and f not in elegidos), None)
        if c:
            elegidos.append(c)
    for f in filas:
        if len(elegidos) >= n:
            break
        if f not in elegidos:
            elegidos.append(f)
    return elegidos


def construir_sistema(sello: Sello, serie_id: str) -> str:
    serie = sello.series[serie_id]
    return RUTA_PROMPT.read_text(encoding="utf-8").format(
        sello_nombre=sello.nombre, sello_voz=sello.datos["sello"].get("voz", "").strip(), serie_nombre=serie.nombre_amazon,
        serie_frase=serie.frase, nota_enfoque=" ".join(str(serie.datos.get("nota_enfoque", "")).split()))


def mensaje(atomos: list[sqlite3.Row], libro, serie, tema: str | None) -> str:
    L = [f"Libro: «{libro.titulo}» — {libro.subtitulo}. Libro {libro.numero} de {len(serie.libros)} de la serie {serie.nombre_amazon}. Para qué es: {libro.para_que}",
         f"Puerta de entrada de la serie: Libro 1, «{serie.libro(1).titulo}».", ""]
    if tema:
        L.append(f"Tema del artículo: {tema}.\n")
    L.append("ÁTOMOS (única fuente admitida):")
    for i, a in enumerate(atomos, 1):
        L.append(f"{i}. [{a['tipo']}{' · LITERAL' if a['es_literal'] else ''}] {a['texto']}\n   Pasaje del libro: «{a['ancla']}»  (capítulo: {a['capitulo'] or '—'})")
    L.append("\nEscribe el artículo.")
    return "\n".join(L)


def verificar(articulo: dict[str, Any], atomos: list[sqlite3.Row], sello: Sello, manuscrito: str | None) -> list[str]:
    motivos: list[str] = []
    cuerpo = articulo["cuerpo_markdown"]
    literales = [normalizar(a["texto"]) for a in atomos if a["es_literal"]] + [normalizar(a["ancla"]) for a in atomos]
    fuente = normalizar(manuscrito) if manuscrito else None
    for cita in re.findall(r"«([^»]{25,})»", cuerpo):
        n = normalizar(cita)
        if fuente is not None:
            ok = n in fuente
        else:
            ok = any(n in lit for lit in literales)
        if not ok:
            motivos.append(f"cita no verificada: «{cita[:60]}…»")
    palabras = len(cuerpo.split())
    if not 700 <= palabras <= 1600:
        motivos.append(f"{palabras} palabras (se piden 900-1300)")
    if len(articulo["titulo"]) > 80:
        motivos.append("título demasiado largo")
    for campo in ("titulo", "resumen", "cuerpo_markdown"):
        h = revisar(articulo[campo], sello.datos["sello"].get("idioma", "es"))
        if bloquea(h):
            motivos.append(f"{campo}: " + "; ".join(str(x) for x in h if x.nivel == "bloquea"))
    return motivos


def escribir_articulo(con: sqlite3.Connection, sello: Sello, ia: ClienteIA, libro_slug: str, tema: str | None = None,
                      reintentos: int = 1) -> Path | None:
    serie = next(s for s in sello.series_activas() if any(l.slug == libro_slug for l in s.libros))
    libro = serie.libro(libro_slug)
    atomos = elegir_atomos(con, libro.id, tema=tema)
    if len(atomos) < 4:
        print(f"  ! {libro.titulo}: pocos átomos")
        return None
    ruta_m = sello.ruta_manuscrito(libro)
    manuscrito = ruta_m.read_text(encoding="utf-8") if ruta_m.exists() else None
    sistema = construir_sistema(sello, serie.id)
    usuario = mensaje(atomos, libro, serie, tema)
    for intento in range(reintentos + 1):
        art = ia.json(sistema, usuario, ESQUEMA, max_tokens=8000)
        if art is None:
            return None
        motivos = verificar(art, atomos, sello, manuscrito)
        if not motivos:
            break
        print(f"  ✗ intento {intento + 1}: " + " | ".join(motivos))
        usuario += "\n\nLa versión anterior tuvo estos problemas; corrígelos sin perder la idea: " + " | ".join(motivos)
    else:
        return None
    slug = slugificar(art.get("slug") or art["titulo"])
    ruta = DIR_BLOG / f"{date.today().isoformat()}-{slug}.md"
    DIR_BLOG.mkdir(parents=True, exist_ok=True)
    front = {"titulo": art["titulo"], "fecha": date.today().isoformat(), "resumen": art["resumen"].strip(),
             "serie": serie.id, "libro": libro.slug, "slug": slug}
    cab = "\n".join(f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in front.items())
    ruta.write_text(f"---\n{cab}\n---\n\n{art['cuerpo_markdown'].strip()}\n", encoding="utf-8")
    print(f"  ✓ {ruta.relative_to(RAIZ_REPO)} · {len(art['cuerpo_markdown'].split())} palabras · «{art['titulo']}»")
    return ruta


def main(argv: list[str] | None = None) -> int:
    consola_utf8()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sello", default="kaizen")
    p.add_argument("--db", type=Path, default=DB_POR_DEFECTO)
    p.add_argument("--libro", action="append")
    p.add_argument("--n", type=int, default=1)
    p.add_argument("--tema")
    a = p.parse_args(argv)
    sello = cargar_sello(a.sello)
    con = db.conectar(a.db)
    serie = sello.series_activas()[0]
    libros = a.libro or libros_menos_cubiertos(con, serie.id)[: a.n]
    ia = cliente_para(sello, "redactor")
    ej = db.abrir_ejecucion(con, "redactor_articulos", ia.modelo)
    hechos = 0
    for slug in libros:
        if escribir_articulo(con, sello, ia, slug, a.tema):
            hechos += 1
    db.cerrar_ejecucion(con, ej, ok=hechos > 0, detalle=json.dumps({"articulos": hechos, "libros": libros}),
                        tokens_entrada=ia.tokens["entrada"], tokens_salida=ia.tokens["salida"],
                        tokens_cache_lectura=ia.tokens["cache_lectura"], coste_usd=ia.coste_usd())
    print(ia.resumen())
    return 0 if hechos else 1


if __name__ == "__main__":
    sys.exit(main())
