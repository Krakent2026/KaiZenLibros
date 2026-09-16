"""Planificador de Fase 1: determinista, sin modelo.

Para cada día crea las piezas que marca `plan.semana` en el YAML, eligiendo átomos verificados
poco usados y repartiendo entre libros. El Estratega (Fase 2) sustituirá esta lógica por un plan
con criterio; la interfaz (filas en `cola` con estado `planificada`) es la misma.
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from agentes import db
from agentes.config import Sello

TIPOS_POR_FORMATO = {
    "carrusel": ("microleccion", "herramienta", "contraste", "dato_honesto", "escena"),
    "cita": ("cita", "contraste", "dato_honesto"),
}
FORMATOS = tuple(TIPOS_POR_FORMATO)


def hora_utc(fecha: date, hhmm: str, zona: str) -> str:
    h, m = (int(x) for x in hhmm.split(":"))
    local = datetime.combine(fecha, time(h, m), tzinfo=ZoneInfo(zona))
    return local.astimezone(timezone.utc).isoformat(timespec="minutes")


def _libros_recientes(con: sqlite3.Connection, n: int = 6) -> list[str]:
    return [f["libro_id"] for f in con.execute(
        "SELECT libro_id FROM cola WHERE estado != 'descartada' ORDER BY id DESC LIMIT ?", (n,))]


def elegir_atomo(con: sqlite3.Connection, serie_id: str, formato: str, evitar_libros: list[str]) -> sqlite3.Row | None:
    candidatos = db.atomos_candidatos(con, serie_id, TIPOS_POR_FORMATO[formato])
    if not candidatos:
        return None
    # primero los que no repiten libro reciente; dentro de ellos ya vienen ordenados por usos
    for c in candidatos:
        if c["libro_id"] not in evitar_libros:
            return c
    return candidatos[0]


def planificar_dia(con: sqlite3.Connection, sello: Sello, fecha: date) -> list[int]:
    clave = f"plan:{sello.id}:{fecha.isoformat()}"
    if db.kv_get(con, clave):
        return []
    plan = sello.datos.get("plan", {})
    zona = plan.get("zona_horaria", "Europe/Madrid")
    formatos = plan.get("semana", {}).get(fecha.weekday(), [])
    horas = plan.get("horas", ["12:30", "19:00"])
    canales = ",".join(sello.datos.get("publicacion", {}).get("canales", ["telegram"]))
    series = sello.series_activas()
    if not series or not formatos:
        db.kv_set(con, clave, "sin piezas")
        return []
    creadas: list[int] = []
    for i, formato in enumerate(formatos):
        if formato not in FORMATOS:
            continue
        serie = series[(fecha.toordinal() + i) % len(series)]  # alterna series si hay varias
        atomo = elegir_atomo(con, serie.id, formato, _libros_recientes(con))
        if atomo is None:
            print(f"  · {fecha} {formato}: sin átomos verificados en {serie.id}; se omite")
            continue
        hora = horas[min(i, len(horas) - 1)]
        id_pieza = db.nueva_pieza(con, atomo_id=atomo["id"], libro_id=atomo["libro_id"], serie=serie.id,
                                  canal=canales, formato=formato, programado_para=hora_utc(fecha, hora, zona),
                                  fecha_plan=fecha.isoformat())
        db.marcar_uso_atomo(con, atomo["id"])
        creadas.append(id_pieza)
        print(f"  · pieza #{id_pieza} {fecha} {hora} {formato:<8} L{atomo['libro_numero']} «{atomo['texto'][:60]}»")
    db.kv_set(con, clave, ",".join(map(str, creadas)) or "sin piezas")
    return creadas


def planificar(con: sqlite3.Connection, sello: Sello, hoy: date | None = None) -> list[int]:
    """Planifica hoy y los `dias_adelanto` siguientes."""
    zona = sello.datos.get("plan", {}).get("zona_horaria", "Europe/Madrid")
    hoy = hoy or datetime.now(ZoneInfo(zona)).date()
    adelanto = int(sello.datos.get("plan", {}).get("dias_adelanto", 1))
    creadas: list[int] = []
    for d in range(adelanto + 1):
        creadas += planificar_dia(con, sello, hoy + timedelta(days=d))
    return creadas
