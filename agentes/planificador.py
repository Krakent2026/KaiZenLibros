"""Planificador diario: crea las piezas del día en la cola.

Si el Estratega ha dejado plan para la semana (kv `plan_semana:<lunes>`), lo sigue: libro, tipo de
átomo preferido y ángulo por pieza. Si no hay plan, aplica la plantilla `plan.semana` del YAML con
reparto determinista (átomos menos usados, sin repetir libro reciente).
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
    "audio": ("herramienta", "microleccion", "dato_honesto", "escena"),
}
FORMATOS = tuple(TIPOS_POR_FORMATO)


def hora_utc(fecha: date, hhmm: str, zona: str) -> str:
    h, m = (int(x) for x in hhmm.split(":"))
    local = datetime.combine(fecha, time(h, m), tzinfo=ZoneInfo(zona))
    return local.astimezone(timezone.utc).isoformat(timespec="minutes")


def canales_para(sello: Sello, formato: str) -> str:
    pub = sello.datos.get("publicacion", {})
    lista = (pub.get("canales_por_formato", {}) or {}).get(formato) or pub.get("canales", ["telegram"])
    return ",".join(lista)


def _libros_recientes(con: sqlite3.Connection, n: int = 6) -> list[str]:
    return [f["libro_id"] for f in con.execute(
        "SELECT libro_id FROM cola WHERE estado != 'descartada' ORDER BY id DESC LIMIT ?", (n,))]


def elegir_atomo(con: sqlite3.Connection, serie_id: str, formato: str, evitar_libros: list[str],
                 libro_slug: str | None = None, tipo_preferido: str | None = None) -> sqlite3.Row | None:
    tipos = TIPOS_POR_FORMATO[formato]
    if tipo_preferido and tipo_preferido in tipos:
        tipos = (tipo_preferido,) + tuple(t for t in tipos if t != tipo_preferido)
    elif tipo_preferido and tipo_preferido != "cualquiera" and tipo_preferido not in tipos:
        tipos = (tipo_preferido,) + tipos  # el Estratega manda, aunque salga de lo habitual
    candidatos = db.atomos_candidatos(con, serie_id, tipos, limite=120)
    if not candidatos:
        return None
    if libro_slug:
        del_libro = [c for c in candidatos if c["libro_slug"] == libro_slug]
        if del_libro:
            # dentro del libro, el tipo preferido primero; luego menos usados (ya vienen así)
            del_libro.sort(key=lambda c: (c["tipo"] != tipos[0], c["usos"]))
            return del_libro[0]
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
    horas = plan.get("horas", ["12:30", "19:00"])
    series = sello.series_activas()
    if not series:
        db.kv_set(con, clave, "sin piezas")
        return []

    encargos: list[dict] = []
    if plan.get("usar_plan_estratega", True):
        from agentes.estratega.planificar import piezas_planificadas_para

        encargos = piezas_planificadas_para(con, fecha) or []
        if encargos:
            print(f"  · {fecha}: siguiendo el plan del Estratega ({len(encargos)} piezas)")
    if not encargos:
        for i, formato in enumerate(plan.get("semana", {}).get(fecha.weekday(), [])):
            serie = series[(fecha.toordinal() + i) % len(series)]
            encargos.append({"formato": formato, "serie": serie.id, "libro_slug": None, "tipo_preferido": None, "angulo": None})

    creadas: list[int] = []
    for i, e in enumerate(encargos):
        formato = e.get("formato")
        if formato not in FORMATOS:
            continue
        serie_id = e.get("serie") or series[0].id
        atomo = elegir_atomo(con, serie_id, formato, _libros_recientes(con), e.get("libro_slug"), e.get("tipo_preferido"))
        if atomo is None:
            print(f"  · {fecha} {formato}: sin átomos verificados en {serie_id}; se omite")
            continue
        hora = horas[min(i, len(horas) - 1)]
        id_pieza = db.nueva_pieza(con, atomo_id=atomo["id"], libro_id=atomo["libro_id"], serie=serie_id,
                                  canal=canales_para(sello, formato), formato=formato,
                                  programado_para=hora_utc(fecha, hora, zona), fecha_plan=fecha.isoformat(),
                                  angulo=e.get("angulo"))
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
