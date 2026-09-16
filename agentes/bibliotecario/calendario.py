"""Bibliotecario: calendario rotatorio de promociones gratis y recordatorios semanales.

    python -m agentes.bibliotecario.calendario            # próximos 60 días + recordatorios
    python -m agentes.bibliotecario.calendario --dias 90

KDP Select permite 5 días gratis por libro cada 90 días. Con 12 libros y promociones de 2 días, la
serie tiene un libro gratis cada semana. El Bibliotecario no toca KDP: prepara la lista y avisa con
antelación; el humano programa la promoción en KDP (Bookshelf → Promocionar y anunciar → Promoción de
libro gratuito). El Estratega recibe el calendario para planificar piezas alrededor de cada promo.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from agentes import db
from agentes.config import DB_POR_DEFECTO, RAIZ_REPO, Sello, cargar_sello, cargar_yaml, consola_utf8


def calendario_promos(sello: Sello, desde: date, dias: int = 60) -> list[dict[str, Any]]:
    cfg = sello.datos.get("bibliotecario", {})
    periodo = int(cfg.get("periodo_dias", 90))
    duracion = int(cfg.get("duracion_promo_dias", 2))
    inicio = date.fromisoformat(str(cfg.get("fecha_inicio_rotacion", desde.isoformat())))
    libros = [l for s in sello.series_activas() for l in s.libros]
    if not libros:
        return []
    paso = max(periodo // len(libros), duracion + 1)  # 90 / 12 = 7 días entre promos
    promos: list[dict[str, Any]] = []
    fin_ventana = desde + timedelta(days=dias)
    for i, lib in enumerate(libros):
        primera = inicio + timedelta(days=i * paso)
        k = 0
        while True:
            ini = primera + timedelta(days=k * periodo)
            if ini > fin_ventana:
                break
            fin = ini + timedelta(days=duracion - 1)
            if fin >= desde:
                promos.append({"libro_slug": lib.slug, "titulo": lib.titulo, "numero": lib.numero, "serie": lib.serie_id,
                               "inicio": ini.isoformat(), "fin": fin.isoformat(), "dias": duracion})
            k += 1
    promos.sort(key=lambda p: p["inicio"])
    return promos


def _fechas_senaladas(desde: date, dias: int) -> list[dict[str, Any]]:
    salida = []
    for f in cargar_yaml("fechas_nicho.yaml").get("globales", []):
        try:
            mes, dia = (int(x) for x in str(f["fecha"]).split("-"))
            fecha = date(desde.year, mes, dia)
        except (ValueError, KeyError):
            continue
        if desde <= fecha <= desde + timedelta(days=dias):
            salida.append({**f, "fecha_iso": fecha.isoformat()})
    return salida


def recordatorios(con: sqlite3.Connection, sello: Sello, hoy: date | None = None) -> list[str]:
    hoy = hoy or date.today()
    cfg = sello.datos.get("bibliotecario", {})
    aviso = int(cfg.get("aviso_dias_antes", 14))
    avisos: list[str] = []

    promos = calendario_promos(sello, hoy, 60)
    db.kv_set(con, "bibliotecario:promos", json.dumps(promos, ensure_ascii=False))
    for p in promos:
        ini = date.fromisoformat(p["inicio"])
        if hoy <= ini <= hoy + timedelta(days=aviso):
            clave = f"bib_avisado:{p['libro_slug']}:{p['inicio']}"
            marca = "" if db.kv_get(con, clave) else " (NUEVO)"
            avisos.append(f"KDP: programar «{p['titulo']}» GRATIS del {p['inicio']} al {p['fin']}{marca}. "
                          f"Bookshelf → el libro → Promocionar y anunciar → Promoción de libro gratuito.")
            db.kv_set(con, clave, hoy.isoformat())

    tok = cfg.get("tokens", {})
    desde_txt = db.kv_get(con, "token_instagram_fecha")
    if not desde_txt:
        db.kv_set(con, "token_instagram_fecha", hoy.isoformat())
        desde_txt = hoy.isoformat()
    caduca = date.fromisoformat(desde_txt) + timedelta(days=int(tok.get("instagram_dias_validez", 60)))
    if caduca - hoy <= timedelta(days=int(tok.get("aviso_dias_antes", 10))):
        avisos.append(f"Token de Instagram: caduca el {caduca}. Renovar: python herramientas/comprobar_credenciales.py "
                      f"--renovar-instagram y actualizar el secret INSTAGRAM_TOKEN; luego kv token_instagram_fecha.")

    sin_asin = [l for s in sello.series_activas() for l in s.libros if not l.asin_ebook]
    if sin_asin:
        avisos.append(f"ASIN: {len(sin_asin)} libros sin ASIN en el YAML; los enlaces van a búsqueda en Amazon en vez de a la ficha. "
                      "Rellenar asin_ebook y regenerar enlaces y web.")

    for f in _fechas_senaladas(hoy, 21):
        avisos.append(f"Fecha señalada {f['fecha_iso']}: {f['nombre']}" + (f" — {f['gancho']}" if f.get("gancho") else ""))

    plan = None
    for k in con.execute("SELECT clave, valor FROM kv WHERE clave LIKE 'plan_semana:%' ORDER BY clave DESC LIMIT 1"):
        plan = json.loads(k["valor"])
    for s in (plan or {}).get("sugerencias_bibliotecario", []):
        avisos.append(f"Estratega sugiere: {s}")
    return avisos


def informe(con: sqlite3.Connection, sello: Sello, hoy: date | None = None, dias: int = 60) -> str:
    hoy = hoy or date.today()
    L = [f"# Bibliotecario · {hoy.isoformat()}", "", "## Recordatorios"]
    L += [f"- {a}" for a in recordatorios(con, sello, hoy)] or ["- nada pendiente"]
    L += ["", f"## Calendario de promociones gratis (próximos {dias} días)", "| Inicio | Fin | Libro |", "|---|---|---|"]
    for p in calendario_promos(sello, hoy, dias):
        L.append(f"| {p['inicio']} | {p['fin']} | {p['numero']}. {p['titulo']} |")
    L += ["", "Cada libro: 5 días gratis por periodo de 90 en KDP Select; aquí se usan 2 por periodo. Quedan 3 por libro para fechas señaladas."]
    texto = "\n".join(L)
    carpeta = RAIZ_REPO / "datos" / "salida"
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / f"bibliotecario_{hoy.isoformat()}.md").write_text(texto, encoding="utf-8")
    return texto


def main(argv: list[str] | None = None) -> int:
    consola_utf8()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sello", default="kaizen")
    p.add_argument("--db", type=Path, default=DB_POR_DEFECTO)
    p.add_argument("--dias", type=int, default=60)
    a = p.parse_args(argv)
    print(informe(db.conectar(a.db), cargar_sello(a.sello), dias=a.dias))
    return 0


if __name__ == "__main__":
    sys.exit(main())
