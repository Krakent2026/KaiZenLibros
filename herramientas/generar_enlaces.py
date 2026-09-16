"""Genera worker_enlaces/enlaces.json a partir del YAML del sello.

    python herramientas/generar_enlaces.py [--sello kaizen]

El Worker de Cloudflare lee ese JSON para resolver /<slug> → Amazon del país del visitante.
Mientras un libro no tenga ASIN, el destino es una búsqueda en Amazon por título y autor,
que funciona igual en todas las tiendas.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import quote_plus

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentes.config import RAIZ_REPO, cargar_sello, consola_utf8  # noqa: E402

consola_utf8()


def construir(sello) -> dict:
    am = sello.datos["amazon"]
    libros = {}
    for s in sello.series_activas():
        for lib in s.libros:
            libros[lib.slug] = {
                "titulo": lib.titulo,
                "serie": s.nombre_amazon,
                "numero": lib.numero,
                "asin_ebook": lib.asin_ebook,
                "asin_papel": lib.asin_papel,
                "busqueda": quote_plus(f"{lib.titulo} {sello.datos['sello']['autor_amazon']}"),
            }
        # alias de serie: /<serie> lleva al libro 1
        if s.libros:
            primero = min(s.libros, key=lambda l: l.numero)
            libros[s.id.replace("_", "-")] = {**libros[primero.slug], "alias_de": primero.slug}
    return {
        "sello": sello.id,
        "web": sello.datos["sello"]["web"].rstrip("/"),
        "por_defecto": am["por_defecto"],
        "marketplaces": am["marketplaces"],
        "afiliados": {k: v for k, v in am.get("afiliados", {}).items() if v},
        "utm_medium": sello.datos["utm"]["medium_por_defecto"],
        "canales": sello.datos["utm"]["canales"],
        "libros": libros,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--sello", default="kaizen")
    a = p.parse_args()
    sello = cargar_sello(a.sello)
    datos = construir(sello)
    salida = RAIZ_REPO / "worker_enlaces" / "enlaces.json"
    salida.parent.mkdir(exist_ok=True)
    salida.write_text(json.dumps(datos, indent=2, ensure_ascii=False), encoding="utf-8")
    con_asin = sum(1 for l in datos["libros"].values() if l.get("asin_ebook"))
    print(f"{salida.relative_to(RAIZ_REPO)}: {len(datos['libros'])} entradas, {con_asin} con ASIN (el resto resuelve por búsqueda)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
