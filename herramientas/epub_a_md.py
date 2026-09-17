"""Extrae el texto de un EPUB a Markdown sencillo, para los libros que no conservan 11_Version_Definitiva.md.

    python herramientas/epub_a_md.py "<ruta.epub>" datos/fuentes_derivadas/<slug>.md

Sigue el orden del spine del OPF; h1/h2/h3 → #, ##, ###; párrafos separados por línea en blanco.
No toca la carpeta del libro: el resultado va al repositorio (datos/fuentes_derivadas, sin versionar).
"""
from __future__ import annotations

import html
import re
import sys
import zipfile
from pathlib import Path


def texto_de_xhtml(x: str) -> str:
    x = re.sub(r"(?is)<(script|style|head)[^>]*>.*?</\1>", "", x)
    x = re.sub(r"(?is)<h1[^>]*>(.*?)</h1>", lambda m: "\n\n# " + re.sub(r"<[^>]+>", "", m.group(1)).strip() + "\n\n", x)
    x = re.sub(r"(?is)<h2[^>]*>(.*?)</h2>", lambda m: "\n\n## " + re.sub(r"<[^>]+>", "", m.group(1)).strip() + "\n\n", x)
    x = re.sub(r"(?is)<h3[^>]*>(.*?)</h3>", lambda m: "\n\n### " + re.sub(r"<[^>]+>", "", m.group(1)).strip() + "\n\n", x)
    x = re.sub(r"(?is)<(br|/p|/div|/li|/blockquote)[^>]*>", "\n\n", x)
    x = re.sub(r"(?is)<(em|i)[^>]*>(.*?)</\1>", r"*\2*", x)
    x = re.sub(r"(?is)<(strong|b)[^>]*>(.*?)</\1>", r"**\2**", x)
    x = re.sub(r"<[^>]+>", "", x)
    x = html.unescape(x)
    x = re.sub(r"[ \t\xa0]+", " ", x)
    x = re.sub(r"\n{3,}", "\n\n", x)
    return "\n".join(l.strip() for l in x.splitlines()).strip()


def epub_a_md(epub: Path) -> str:
    with zipfile.ZipFile(epub) as z:
        contenedor = z.read("META-INF/container.xml").decode("utf-8", "replace")
        opf_ruta = re.search(r'full-path="([^"]+)"', contenedor).group(1)
        opf = z.read(opf_ruta).decode("utf-8", "replace")
        base = opf_ruta.rsplit("/", 1)[0] + "/" if "/" in opf_ruta else ""
        items = {m.group(1): m.group(2) for m in re.finditer(r'<item[^>]+id="([^"]+)"[^>]+href="([^"]+)"', opf)}
        items.update({m.group(2): m.group(1) for m in re.finditer(r'<item[^>]+href="([^"]+)"[^>]+id="([^"]+)"', opf)})
        spine = re.findall(r'<itemref[^>]+idref="([^"]+)"', opf)
        partes = []
        for idref in spine:
            href = items.get(idref)
            if not href or not re.search(r"\.x?html?$", href, re.I):
                continue
            partes.append(texto_de_xhtml(z.read(base + href).decode("utf-8", "replace")))
    return "\n\n".join(p for p in partes if p)


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    origen, destino = Path(sys.argv[1]), Path(sys.argv[2])
    destino.parent.mkdir(parents=True, exist_ok=True)
    md = epub_a_md(origen)
    destino.write_text(md, encoding="utf-8")
    print(f"{destino} · {len(md.split()):,} palabras · {md.count(chr(10))} líneas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
