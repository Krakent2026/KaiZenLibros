"""Importa los CSV descargados de KDP Reports (datos/kdp/*.csv, no versionados) a la tabla `ventas_kdp`.

KDP cambia las columnas según el informe (Pedidos, KENP, Regalías) y el idioma del panel. El lector
busca las columnas por palabras clave y no exige ninguna en particular salvo el título.
    python -m agentes.analista.kdp
"""
from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import sys
from pathlib import Path

from agentes import db
from agentes.config import DB_POR_DEFECTO, RAIZ_REPO, cargar_sello, consola_utf8

CLAVES = {
    "titulo": ("title", "título", "titulo", "libro"),
    "fecha": ("royalty date", "fecha de regal", "date", "fecha", "month", "mes"),
    "tienda": ("marketplace", "tienda", "market"),
    "unidades": ("net units sold", "units sold", "paid units", "unidades vendidas", "unidades netas", "unidades pagadas", "units", "unidades"),
    "gratis": ("free units", "unidades gratuitas", "free"),
    "kenp": ("kenp",),
    "regalias": ("royalty", "regal", "royalties", "ganancias"),
}


def _num(v: str | None) -> float:
    if not v:
        return 0.0
    s = re.sub(r"[^\d,.\-]", "", str(v))
    if s.count(",") and s.count("."):
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif s.count(","):
        s = s.replace(",", ".") if len(s.split(",")[-1]) <= 2 else s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _columnas(cabeceras: list[str]) -> dict[str, str]:
    bajas = {h: h.strip().lower() for h in cabeceras}
    mapa: dict[str, str] = {}
    for campo, claves in CLAVES.items():
        for h, b in bajas.items():
            if any(c in b for c in claves) and h not in mapa.values():
                if campo == "unidades" and "free" in b:
                    continue
                mapa[campo] = h
                break
    return mapa


def importar_fichero(con: sqlite3.Connection, ruta: Path) -> int:
    texto = ruta.read_text(encoding="utf-8-sig", errors="replace")
    try:
        dialecto = csv.Sniffer().sniff(texto[:4000], delimiters=",;\t")
    except csv.Error:
        dialecto = csv.excel
    filas = list(csv.DictReader(texto.splitlines(), dialect=dialecto))
    if not filas:
        return 0
    mapa = _columnas(list(filas[0].keys()))
    if "titulo" not in mapa:
        print(f"  ✗ {ruta.name}: no encuentro la columna de título ({list(filas[0].keys())[:6]}…)")
        return 0
    n = 0
    for f in filas:
        titulo = (f.get(mapa["titulo"]) or "").strip()
        if not titulo:
            continue
        fecha = (f.get(mapa.get("fecha", ""), "") or "").strip()[:10] or ruta.stem[-10:]
        con.execute(
            """INSERT OR IGNORE INTO ventas_kdp (fecha, titulo, tienda, unidades, gratis, kenp, regalias, fichero)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (fecha, titulo, (f.get(mapa.get("tienda", ""), "") or "").strip(), _num(f.get(mapa.get("unidades", ""))),
             _num(f.get(mapa.get("gratis", ""))), _num(f.get(mapa.get("kenp", ""))), _num(f.get(mapa.get("regalias", ""))), ruta.name),
        )
        n += 1
    con.commit()
    return n


def importar_dir(con: sqlite3.Connection, carpeta: Path) -> int:
    if not carpeta.exists():
        return 0
    total = 0
    for f in sorted(carpeta.glob("*.csv")):
        n = importar_fichero(con, f)
        total += n
        if n:
            print(f"  ✓ {f.name}: {n} filas")
    return total


def resumen_kdp(con: sqlite3.Connection, dias: int = 30) -> list[sqlite3.Row]:
    return con.execute(
        """SELECT titulo, SUM(unidades) AS unidades, SUM(gratis) AS gratis, SUM(kenp) AS kenp, SUM(regalias) AS regalias
           FROM ventas_kdp WHERE fecha >= date('now', ?) GROUP BY titulo ORDER BY regalias DESC, unidades DESC""",
        (f"-{int(dias)} days",)).fetchall()


def main(argv: list[str] | None = None) -> int:
    consola_utf8()
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sello", default="kaizen")
    p.add_argument("--db", type=Path, default=DB_POR_DEFECTO)
    a = p.parse_args(argv)
    sello = cargar_sello(a.sello)
    carpeta = RAIZ_REPO / sello.datos.get("analista", {}).get("dir_kdp", "datos/kdp")
    print(f"{importar_dir(db.conectar(a.db), carpeta)} filas importadas de {carpeta}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
