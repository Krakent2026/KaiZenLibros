"""Redactor: piezas `planificada` (o `rechazada` con reintentos) → `redactada`.

    python -m agentes.redactor.redactar            # redacta todo lo pendiente
    python -m agentes.redactor.redactar --id 12    # una pieza
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from agentes import db
from agentes.config import DB_POR_DEFECTO, Sello, cargar_sello, consola_utf8
from agentes.ia import ClienteIA, cliente_para

RUTA_PROMPT = Path(__file__).with_name("prompt.md")

ESQUEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "ganchos": {"type": "array", "items": {"type": "string"}},
        "diapositivas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"titulo": {"type": "string"}, "cuerpo": {"type": "string"}},
                "required": ["titulo", "cuerpo"],
                "additionalProperties": False,
            },
        },
        "caption_instagram": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
        "pin": {
            "type": "object",
            "properties": {"titulo": {"type": "string"}, "descripcion": {"type": "string"}},
            "required": ["titulo", "descripcion"],
            "additionalProperties": False,
        },
        "telegram": {"type": "string"},
        "alt_texto": {"type": "string"},
    },
    "required": ["ganchos", "diapositivas", "caption_instagram", "hashtags", "pin", "telegram", "alt_texto"],
    "additionalProperties": False,
}


def construir_sistema(sello: Sello, serie_id: str) -> str:
    serie = sello.series[serie_id]
    d = serie.datos
    return RUTA_PROMPT.read_text(encoding="utf-8").format(
        sello_nombre=sello.nombre,
        sello_voz=sello.datos["sello"].get("voz", "").strip(),
        serie_nombre=serie.nombre_amazon,
        serie_frase=serie.frase,
        serie_promesa=d.get("promesa", ""),
        nota_enfoque=" ".join(str(d.get("nota_enfoque", "")).split()),
        hashtags_max=sello.datos.get("publicacion", {}).get("hashtags_max", 8),
    )


def mensaje_usuario(fila: sqlite3.Row, sello: Sello) -> str:
    serie = sello.series[fila["serie"]]
    libro = serie.libro(fila["libro_slug"])
    temas = ", ".join(json.loads(fila["temas"] or "[]"))
    partes = [
        f"Formato de la pieza: **{fila['formato']}**.",
        "",
        f"Libro: «{libro.titulo}» — {libro.subtitulo}. Libro {libro.numero} de {len(serie.libros)} de la serie {serie.nombre_amazon}. Para qué es: {libro.para_que}",
        f"Átomo (tipo {fila['atomo_tipo']}{', LITERAL del libro' if fila['es_literal'] else ''}):",
        f"«{fila['atomo_texto']}»",
        f"Pasaje del libro que lo respalda: «{fila['ancla']}»",
        f"Capítulo: {fila['capitulo'] or '—'}. Temas: {temas or '—'}. Gancho sugerido por el Minero: {fila['atomo_gancho'] or '—'}",
    ]
    if fila["nota_humano"]:
        partes += ["", f"NOTA DEL EDITOR HUMANO (obligatoria): {fila['nota_humano']}"]
    if fila["motivo_rechazo"]:
        partes += ["", f"La versión anterior fue rechazada por el Guardián. Motivo: {fila['motivo_rechazo']}. Corrígelo sin perder la idea."]
    partes += ["", "Escribe la pieza."]
    return "\n".join(partes)


def redactar_pieza(con: sqlite3.Connection, sello: Sello, fila: sqlite3.Row, ia: ClienteIA) -> bool:
    sistema = construir_sistema(sello, fila["serie"])
    datos = ia.json(sistema, mensaje_usuario(fila, sello), ESQUEMA)
    if datos is None:
        return False
    contenido = {**datos, "formato": fila["formato"], "modelo": ia.modelo}
    if fila["formato"] == "cita":
        # la cita es sagrada: se fuerza el texto exacto del átomo aunque el modelo lo haya tocado
        contenido["diapositivas"] = [{"titulo": "", "cuerpo": fila["atomo_texto"]}]
    db.actualizar_pieza(con, fila["id"], contenido=contenido, estado="redactada", motivo_rechazo=None)
    return True


def redactar_pendientes(con: sqlite3.Connection, sello: Sello, ia: ClienteIA | None = None,
                        ids: list[int] | None = None) -> dict[str, int]:
    ia = ia or cliente_para(sello, "redactor")
    max_int = int(sello.datos.get("plan", {}).get("max_reintentos_redaccion", 2))
    pendientes = db.piezas(con, "planificada", "rechazada")
    if ids:
        pendientes = [p for p in pendientes if p["id"] in ids]
    r = {"redactadas": 0, "descartadas": 0, "fallidas": 0}
    for fila in pendientes:
        if fila["estado"] == "rechazada" and fila["intentos"] > max_int:
            db.actualizar_pieza(con, fila["id"], estado="descartada")
            r["descartadas"] += 1
            print(f"  ✗ pieza #{fila['id']} descartada tras {fila['intentos']} intentos: {fila['motivo_rechazo']}")
            continue
        ok = redactar_pieza(con, sello, fila, ia)
        if ok:
            r["redactadas"] += 1
            print(f"  ✓ pieza #{fila['id']} redactada ({fila['formato']}, L{fila['libro_numero']})")
        else:
            r["fallidas"] += 1
    return r


def main(argv: list[str] | None = None) -> int:
    consola_utf8()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sello", default="kaizen")
    p.add_argument("--db", type=Path, default=DB_POR_DEFECTO)
    p.add_argument("--id", type=int, action="append")
    a = p.parse_args(argv)
    sello = cargar_sello(a.sello)
    con = db.conectar(a.db)
    ia = cliente_para(sello, "redactor")
    ej = db.abrir_ejecucion(con, "redactor", ia.modelo)
    r = redactar_pendientes(con, sello, ia, a.id)
    db.cerrar_ejecucion(con, ej, ok=r["fallidas"] == 0, detalle=json.dumps(r), tokens_entrada=ia.tokens["entrada"],
                        tokens_salida=ia.tokens["salida"], tokens_cache_lectura=ia.tokens["cache_lectura"],
                        coste_usd=ia.coste_usd())
    print(ia.resumen())
    return 0 if r["fallidas"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
