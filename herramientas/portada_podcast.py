"""Genera la portada cuadrada del pódcast (3000×3000, requisito de Apple/Spotify) con la paleta de la serie.

    python herramientas/portada_podcast.py [--sello kaizen] [--serie mente_distinta]
Salida: web/static/podcast/portada.jpg
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from agentes.config import DIR_CONFIG, RAIZ_REPO, cargar_sello, consola_utf8  # noqa: E402

consola_utf8()
FUENTE = RAIZ_REPO / "agentes" / "disenador" / "fuentes" / "Lora.ttf"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--sello", default="kaizen")
    p.add_argument("--serie")
    a = p.parse_args()
    sello = cargar_sello(a.sello)
    serie_id = a.serie or sello.series_activas()[0].id
    pal = {"dominante": "#3f5a4c", "acento": "#c9773a", "texto_sobre_dominante": "#fafaf9"}
    ruta_pal = DIR_CONFIG / "paletas" / f"{serie_id}.json"
    if ruta_pal.exists():
        pal.update(json.loads(ruta_pal.read_text(encoding="utf-8")))
    pod = sello.datos.get("podcast", {})
    L = 3000
    im = Image.new("RGB", (L, L), pal["acento"])
    d = ImageDraw.Draw(im)
    f_titulo = ImageFont.truetype(str(FUENTE), 300)
    f_sub = ImageFont.truetype(str(FUENTE), 120)
    f_marca = ImageFont.truetype(str(FUENTE), 110)
    # banda superior con la marca
    d.rectangle([0, 0, L, 360], fill=pal["dominante"])
    d.text((180, 110), sello.nombre.upper(), font=f_marca, fill=pal["texto_sobre_dominante"], spacing=10)
    # título en dos líneas
    titulo = pod.get("titulo", sello.nombre)
    partes = titulo.replace(",", ",\n").split("\n") if "," in titulo else [titulo]
    y = 900
    for parte in partes:
        d.text((180, y), parte.strip(), font=f_titulo, fill="#ffffff")
        y += 360
    d.rectangle([180, y + 60, 620, y + 72], fill="#ffffff")
    d.text((180, y + 160), pod.get("descripcion", "")[:60], font=f_sub, fill="#ffffff")
    destino = RAIZ_REPO / "web" / pod.get("ruta_web", "static/podcast").strip("/") / "portada.jpg"
    destino.parent.mkdir(parents=True, exist_ok=True)
    im.save(destino, "JPEG", quality=88, optimize=True)
    print(f"{destino.relative_to(RAIZ_REPO)} ({destino.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
