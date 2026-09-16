"""Extrae la paleta de cada serie a partir de sus portadas de ebook.

    python herramientas/paleta_desde_portadas.py [--sello kaizen] [--serie mente_distinta]

Escribe config/paletas/<serie>.json con: color dominante, color de acento, color de texto
recomendado (claro/oscuro según luminancia) y los cinco colores más frecuentes por libro.
La web y el Diseñador (Fase 1) leen ese JSON: la identidad visual sale de las portadas reales,
no de una elección a ojo.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image  # noqa: E402

from agentes.config import DIR_CONFIG, cargar_sello, consola_utf8  # noqa: E402

consola_utf8()


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % rgb


def _luminancia(rgb: tuple[int, int, int]) -> float:
    r, g, b = (c / 255 for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _saturacion(rgb: tuple[int, int, int]) -> float:
    mx, mn = max(rgb), min(rgb)
    return 0 if mx == 0 else (mx - mn) / mx


def colores_de(ruta: Path, n: int = 6) -> list[tuple[int, int, int]]:
    im = Image.open(ruta).convert("RGB")
    im.thumbnail((160, 256))
    cuant = im.quantize(colors=16, method=Image.Quantize.MEDIANCUT)
    paleta = cuant.getpalette()[: 16 * 3]
    datos = cuant.get_flattened_data() if hasattr(cuant, "get_flattened_data") else cuant.getdata()
    cuenta = Counter(datos)
    salida = []
    for idx, _ in cuenta.most_common():
        rgb = tuple(paleta[idx * 3: idx * 3 + 3])
        salida.append(rgb)  # type: ignore[arg-type]
        if len(salida) >= n:
            break
    return salida


def paleta_serie(colores_por_libro: dict[str, list[tuple[int, int, int]]]) -> dict:
    todos = Counter()
    for cols in colores_por_libro.values():
        for peso, c in enumerate(reversed(cols), 1):
            todos[c] += peso
    ordenados = [c for c, _ in todos.most_common()]
    dominante = ordenados[0]
    # acento: el color más saturado que contraste con el dominante
    candidatos = sorted(ordenados[1:], key=lambda c: (_saturacion(c), abs(_luminancia(c) - _luminancia(dominante))), reverse=True)
    acento = candidatos[0] if candidatos else dominante
    texto = "#1c1917" if _luminancia(dominante) > 0.55 else "#fafaf9"
    return {
        "dominante": _hex(dominante),
        "acento": _hex(acento),
        "texto_sobre_dominante": texto,
        "fondo_claro": "#faf7f2",
        "tinta": "#1c1917",
        "por_libro": {slug: [_hex(c) for c in cols] for slug, cols in colores_por_libro.items()},
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--sello", default="kaizen")
    p.add_argument("--serie")
    a = p.parse_args()
    sello = cargar_sello(a.sello)
    series = [sello.series[a.serie]] if a.serie else sello.series_activas()
    destino = DIR_CONFIG / "paletas"
    destino.mkdir(exist_ok=True)
    for s in series:
        por_libro = {}
        for lib in s.libros:
            ruta = sello.ruta_portada(lib)
            if not ruta.exists():
                print(f"  ✗ {lib.slug}: falta {ruta}")
                continue
            por_libro[lib.slug] = colores_de(ruta)
        if not por_libro:
            print(f"{s.id}: sin portadas accesibles")
            continue
        pal = paleta_serie(por_libro)
        (destino / f"{s.id}.json").write_text(json.dumps(pal, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"{s.id}: dominante {pal['dominante']} · acento {pal['acento']} → {destino / (s.id + '.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
