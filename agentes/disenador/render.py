"""Diseñador: piezas `pendiente_humano` sin imágenes → JPEG en web/static/piezas/<id>/.

    python -m agentes.disenador.render                 # produce lo pendiente
    python -m agentes.disenador.render --id 12
    python -m agentes.disenador.render --demo          # pieza de ejemplo en datos/salida/demo (para ver el diseño)

Requiere Playwright con Chromium:  pip install playwright && playwright install chromium
Salida: 01.jpg … 07.jpg (1080×1350, Instagram) y pin.jpg (1000×1500, Pinterest). JPEG porque
Instagram no admite PNG por URL y porque pesa la mitad en el repositorio.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from agentes import db
from agentes.config import DB_POR_DEFECTO, DIR_CONFIG, RAIZ_REPO, Sello, cargar_sello, consola_utf8

DIR = Path(__file__).parent
DIR_FUENTES = DIR / "fuentes"
DIR_PORTADAS = RAIZ_REPO / "web" / "static" / "portadas"
TAMANOS = {"instagram": (1080, 1350), "pin": (1000, 1500)}
PALETA_POR_DEFECTO = {"dominante": "#3f5a4c", "acento": "#c9773a", "texto_sobre_dominante": "#fafaf9", "tinta": "#1c1917"}

_env = Environment(loader=FileSystemLoader(DIR / "plantillas"), autoescape=select_autoescape(["html"]))


def paleta_de(serie_id: str) -> dict[str, str]:
    ruta = DIR_CONFIG / "paletas" / f"{serie_id}.json"
    if ruta.exists():
        return {**PALETA_POR_DEFECTO, **json.loads(ruta.read_text(encoding="utf-8"))}
    return dict(PALETA_POR_DEFECTO)


def dir_piezas(sello: Sello) -> Path:
    ruta = sello.datos.get("publicacion", {}).get("ruta_piezas_web", "static/piezas").strip("/")
    return RAIZ_REPO / "web" / ruta


def diapositivas_para(fila: sqlite3.Row, contenido: dict[str, Any], sello: Sello) -> list[dict[str, Any]]:
    """Traduce el contenido del Redactor a las diapositivas que se renderizan."""
    serie = sello.series[fila["serie"]]
    libro = serie.libro(fila["libro_slug"])
    base = {
        "serie_nombre": serie.nombre_amazon, "sello_nombre": sello.nombre,
        "libro_titulo": libro.titulo, "libro_subtitulo": libro.subtitulo,
        "portada": (DIR_PORTADAS / f"{libro.slug}.jpg").resolve().as_uri() if (DIR_PORTADAS / f"{libro.slug}.jpg").exists() else None,
    }
    d = contenido.get("diapositivas", [])
    salida: list[dict[str, Any]] = []
    if fila["formato"] == "cita":
        salida.append({**base, "tipo": "cita", "cuerpo": d[0]["cuerpo"] if d else fila["atomo_texto"], "clase": ""})
    elif fila["formato"] == "audio":
        titulo = contenido.get("titulo_episodio") or (d[0]["titulo"] if d else libro.titulo)
        salida.append({**base, "serie_nombre": f"{serie.nombre_amazon} · Pódcast", "tipo": "gancho", "titulo": titulo, "clase": "invertida"})
    elif fila["formato"] in ("sello", "serie"):
        cinta = f"{serie.nombre_amazon} · {len(serie.libros)} libros" if fila["formato"] == "serie" else f"Libros de {sello.nombre}"
        base_i = {**base, "serie_nombre": cinta, "libro_titulo": serie.nombre_amazon if fila["formato"] == "serie" else sello.nombre,
                  "libro_subtitulo": f"«{serie.frase}»" if fila["formato"] == "serie" else sello.datos["sello"].get("tagline", "")}
        portadas = [(DIR_PORTADAS / f"{l.slug}.jpg").resolve().as_uri() for l in serie.libros[:6] if (DIR_PORTADAS / f"{l.slug}.jpg").exists()]
        total = len(d)
        for i, x in enumerate(d, 1):
            if i == 1:
                salida.append({**base_i, "tipo": "gancho", "titulo": x["titulo"], "clase": "", "indice": i, "total": total})
            elif i == total:
                salida.append({**base_i, "tipo": "coleccion", "titulo": x["titulo"], "cuerpo": x["cuerpo"], "portadas": portadas,
                               "clase": "invertida", "indice": i, "total": total})
            else:
                salida.append({**base_i, "tipo": "texto", "titulo": x["titulo"], "cuerpo": x["cuerpo"], "clase": "", "indice": i, "total": total})
        base = base_i
    else:
        total = len(d)
        for i, x in enumerate(d, 1):
            if i == 1:
                salida.append({**base, "tipo": "gancho", "titulo": x["titulo"], "clase": "", "indice": i, "total": total})
            elif i == total:
                cuerpo = x["cuerpo"] or f"Está en «{libro.titulo}», libro {libro.numero} de la serie {serie.nombre_amazon}. Enlace en la bio."
                salida.append({**base, "tipo": "final", "titulo": x["titulo"], "cuerpo": cuerpo, "clase": "invertida", "indice": i, "total": total})
            else:
                salida.append({**base, "tipo": "texto", "titulo": x["titulo"], "cuerpo": x["cuerpo"], "clase": "", "indice": i, "total": total})
    # pin: gancho + descripción corta
    pin = contenido.get("pin", {})
    resumen = pin.get("descripcion", "")
    if len(resumen) > 230:
        resumen = resumen[:230].rsplit(" ", 1)[0] + "…"
    salida.append({**base, "tipo": "pin", "titulo": pin.get("titulo") or (contenido.get("ganchos") or [libro.titulo])[0],
                   "cuerpo": resumen, "clase": "pin", "_tamano": "pin", "_fichero": "pin.jpg"})
    return salida


class Renderizador:
    def __init__(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("Falta Playwright: pip install playwright && playwright install chromium") from e
        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.launch()
        self.tmp = Path(tempfile.mkdtemp(prefix="piezas_"))

    def cerrar(self) -> None:
        self.browser.close()
        self._pw.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def render(self, ctx: dict[str, Any], destino: Path, tamano: tuple[int, int], paleta: dict[str, str]) -> None:
        ancho, alto = tamano
        html = _env.get_template("pieza.html").render(**ctx, ancho=ancho, alto=alto, paleta=paleta,
                                                      fuentes=DIR_FUENTES.resolve().as_uri())
        f = self.tmp / f"{destino.stem}.html"
        f.write_text(html, encoding="utf-8")
        page = self.browser.new_page(viewport={"width": ancho, "height": alto}, device_scale_factor=1)
        try:
            page.goto(f.resolve().as_uri())
            page.wait_for_load_state("networkidle")
            page.evaluate("document.fonts.ready")
            destino.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(destino), type="jpeg", quality=88)
        finally:
            page.close()


def producir_pieza(fila: sqlite3.Row, contenido: dict[str, Any], sello: Sello, r: Renderizador, destino: Path) -> list[Path]:
    paleta = paleta_de(fila["serie"])
    ficheros: list[Path] = []
    for i, ctx in enumerate(diapositivas_para(fila, contenido, sello), 1):
        tamano = TAMANOS[ctx.pop("_tamano", "instagram")]
        nombre = ctx.pop("_fichero", f"{i:02d}.jpg")
        salida = destino / nombre
        r.render(ctx, salida, tamano, paleta)
        ficheros.append(salida)
    return ficheros


def producir_pendientes(con: sqlite3.Connection, sello: Sello, ids: list[int] | None = None) -> int:
    pendientes = [p for p in db.piezas(con, "pendiente_humano", "aprobada") if not p["ruta_activos"]]
    if ids:
        pendientes = [p for p in pendientes if p["id"] in ids]
    if not pendientes:
        return 0
    r = Renderizador()
    n = 0
    try:
        for fila in pendientes:
            destino = dir_piezas(sello) / str(fila["id"])
            ficheros = producir_pieza(fila, db.contenido_de(fila), sello, r, destino)
            db.actualizar_pieza(con, fila["id"], ruta_activos=str(destino.relative_to(RAIZ_REPO)).replace("\\", "/"))
            n += 1
            print(f"  ✓ pieza #{fila['id']}: {len(ficheros)} imágenes en {destino.relative_to(RAIZ_REPO)}")
    finally:
        r.cerrar()
    return n


def activos_de(fila: sqlite3.Row) -> list[Path]:
    if not fila["ruta_activos"]:
        return []
    return sorted((RAIZ_REPO / fila["ruta_activos"]).glob("*.jpg"))


def demo(sello: Sello) -> Path:
    """Renderiza una pieza de ejemplo con textos fijos para revisar el diseño."""
    serie = sello.series_activas()[0]
    libro = serie.libros[0]
    fila = {"formato": "carrusel", "serie": serie.id, "libro_slug": libro.slug, "atomo_texto": ""}
    contenido = {
        "diapositivas": [
            {"titulo": "No te falta voluntad", "cuerpo": ""},
            {"titulo": "Lo que te han dicho", "cuerpo": "«Vago». «Despistada». «Tiene mucho potencial, pero no se aplica». Media vida oyéndolo y, lo que es peor, creyéndotelo."},
            {"titulo": "", "cuerpo": "No es falta de atención: es atención que no obedece. Sabes perfectamente lo que tienes que hacer. Eso nunca fue el problema."},
            {"titulo": "La brecha", "cuerpo": "Entre saber y poder hay un hueco que la fuerza de voluntad no rellena. Apretar más funciona un día; el segundo, cobra intereses."},
            {"titulo": "Menos fricción, no más fuerza", "cuerpo": "Cuando apretar ya no funciona, lo que cambia las cosas es quitar pasos, no añadir castigo."},
            {"titulo": "Un paso hoy", "cuerpo": "Saca una sola cosa de tu cabeza y déjala escrita donde vayas a verla mañana. Solo una."},
            {"titulo": "No eras tú el problema.", "cuerpo": "Está en «No es pereza», libro 1 de la serie Mente distinta. Enlace en la bio."},
        ],
        "pin": {"titulo": "TDAH adulto: por qué no es falta de voluntad", "descripcion": "Qué es el TDAH en un adulto explicado sin jerga y sin culpa: por qué la atención no obedece, por qué cuesta arrancar y qué no es TDAH. Primer libro de la serie Mente distinta."},
        "ganchos": ["No te falta voluntad"],
    }
    destino = RAIZ_REPO / "datos" / "salida" / "demo"
    r = Renderizador()
    try:
        producir_pieza(fila, contenido, sello, r, destino)  # type: ignore[arg-type]
        fila_cita = {**fila, "formato": "cita", "atomo_texto": "No vas a encontrar aquí la promesa de que, si aplicas tal método, tu vida va a dar un vuelco radical en unas semanas."}
        producir_pieza(fila_cita, {"diapositivas": [{"titulo": "", "cuerpo": fila_cita["atomo_texto"]}], "pin": contenido["pin"]}, sello, r, destino / "cita")  # type: ignore[arg-type]
    finally:
        r.cerrar()
    return destino


def main(argv: list[str] | None = None) -> int:
    consola_utf8()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sello", default="kaizen")
    p.add_argument("--db", type=Path, default=DB_POR_DEFECTO)
    p.add_argument("--id", type=int, action="append")
    p.add_argument("--demo", action="store_true")
    a = p.parse_args(argv)
    sello = cargar_sello(a.sello)
    if a.demo:
        print(f"Demo en {demo(sello)}")
        return 0
    con = db.conectar(a.db)
    n = producir_pendientes(con, sello, a.id)
    print(f"{n} piezas producidas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
