"""Copia las portadas de ebook al repositorio, reducidas para web.

    python herramientas/copiar_portadas.py [--sello kaizen] [--ancho 600]

Destino: web/static/portadas/<slug>.jpg. Las portadas sí viajan en el repositorio (son públicas
en Amazon); los manuscritos no. Se reescalan para que la web cargue rápido.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image  # noqa: E402

from agentes.config import RAIZ_REPO, cargar_sello, consola_utf8  # noqa: E402

consola_utf8()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--sello", default="kaizen")
    p.add_argument("--ancho", type=int, default=600)
    a = p.parse_args()
    sello = cargar_sello(a.sello)
    destino = RAIZ_REPO / "web" / "static" / "portadas"
    destino.mkdir(parents=True, exist_ok=True)
    n = 0
    for lib in sello.libros_activos():
        origen = sello.ruta_portada(lib)
        if not origen.exists():
            print(f"  ✗ {lib.slug}: falta {origen}")
            continue
        im = Image.open(origen).convert("RGB")
        if im.width > a.ancho:
            im = im.resize((a.ancho, round(im.height * a.ancho / im.width)), Image.Resampling.LANCZOS)
        salida = destino / f"{lib.slug}.jpg"
        im.save(salida, "JPEG", quality=82, optimize=True, progressive=True)
        n += 1
        print(f"  ✓ {salida.relative_to(RAIZ_REPO)} ({salida.stat().st_size // 1024} KB)")
    print(f"{n} portadas copiadas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
