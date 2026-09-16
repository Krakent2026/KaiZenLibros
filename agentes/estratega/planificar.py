"""Estratega: genera el plan de la semana y lo deja en kv (`plan_semana:<lunes>`) para el planificador diario.

    python -m agentes.estratega.planificar                # plan de la próxima semana
    python -m agentes.estratega.planificar --lunes 2026-09-28 --rehacer
    python -m agentes.estratega.planificar --ver           # muestra el plan vigente
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from agentes import db
from agentes.config import DB_POR_DEFECTO, Sello, cargar_sello, cargar_yaml, consola_utf8
from agentes.ia import ClienteIA, cliente_para

RUTA_PROMPT = Path(__file__).with_name("prompt.md")
FORMATOS = ("carrusel", "cita", "audio")
TIPOS = ("cita", "microleccion", "pregunta", "contraste", "herramienta", "escena", "dato_honesto", "cualquiera")

ESQUEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "resumen": {"type": "string"},
        "dias": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "fecha": {"type": "string"},
                    "piezas": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "formato": {"type": "string", "enum": list(FORMATOS)},
                                "libro_slug": {"type": "string"},
                                "tipo_preferido": {"type": "string", "enum": list(TIPOS)},
                                "angulo": {"type": "string"},
                                "motivo": {"type": "string"},
                            },
                            "required": ["formato", "libro_slug", "tipo_preferido", "angulo", "motivo"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["fecha", "piezas"],
                "additionalProperties": False,
            },
        },
        "sugerencias_bibliotecario": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["resumen", "dias", "sugerencias_bibliotecario"],
    "additionalProperties": False,
}


def proximo_lunes(hoy: date | None = None, zona: str = "Europe/Madrid") -> date:
    hoy = hoy or datetime.now(ZoneInfo(zona)).date()
    return hoy + timedelta(days=(7 - hoy.weekday()) % 7 or 7) if hoy.weekday() != 0 else hoy


def clave_plan(lunes: date) -> str:
    return f"plan_semana:{lunes.isoformat()}"


def plan_vigente(con: sqlite3.Connection, fecha: date) -> dict[str, Any] | None:
    lunes = fecha - timedelta(days=fecha.weekday())
    crudo = db.kv_get(con, clave_plan(lunes))
    return json.loads(crudo) if crudo else None


def piezas_planificadas_para(con: sqlite3.Connection, fecha: date) -> list[dict[str, Any]] | None:
    plan = plan_vigente(con, fecha)
    if not plan:
        return None
    for d in plan.get("dias", []):
        if d.get("fecha") == fecha.isoformat():
            return d.get("piezas", [])
    return None


# ---- contexto para el modelo ----------------------------------------------------------
def fechas_proximas(lunes: date, dias: int = 21) -> list[dict[str, Any]]:
    salida = []
    for f in cargar_yaml("fechas_nicho.yaml").get("globales", []):
        try:
            mes, dia = (int(x) for x in str(f["fecha"]).split("-"))
            fecha = date(lunes.year, mes, dia)
        except (ValueError, KeyError):
            continue
        if lunes <= fecha <= lunes + timedelta(days=dias):
            salida.append({"fecha": fecha.isoformat(), "nombre": f["nombre"], "series": f.get("series", []), "gancho": f.get("gancho", "")})
    return salida


def contexto(con: sqlite3.Connection, sello: Sello, serie_id: str, lunes: date) -> dict[str, Any]:
    plan_cfg = sello.datos.get("plan", {})
    semana = plan_cfg.get("semana", {})
    dias = []
    for i in range(7):
        f = lunes + timedelta(days=i)
        dias.append({"fecha": f.isoformat(), "dia": ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"][i],
                     "formatos": semana.get(i, [])})
    libros = [dict(r) for r in db.uso_por_libro(con, serie_id)]
    recientes = [{"fecha": r["publicado_en"][:10], "libro": r["libro_titulo"], "formato": r["formato"], "canal": r["canal"]}
                 for r in db.publicaciones_recientes(con, 14)]
    metricas = [{"libro": m["libro_titulo"], "formato": m["formato"], "canal": m["canal"], "alcance": m["alcance"] or m["impresiones"],
                 "guardados": m["guardados"], "me_gusta": m["me_gusta"], "tipo_atomo": m["atomo_tipo"], "gancho": m["gancho"]}
                for m in db.ultimas_metricas(con, 30)][:30]
    gratis = json.loads(db.kv_get(con, "bibliotecario:promos") or "[]")
    gratis = [g for g in gratis if lunes.isoformat() <= g["inicio"] <= (lunes + timedelta(days=14)).isoformat()]
    return {"semana_del": lunes.isoformat(), "dias": dias, "libros": libros, "publicaciones_ultimos_14_dias": recientes,
            "metricas_recientes": metricas, "fechas_senaladas": fechas_proximas(lunes), "libros_gratis_programados": gratis}


def construir_sistema(sello: Sello) -> str:
    return RUTA_PROMPT.read_text(encoding="utf-8").format(
        sello_nombre=sello.nombre, sello_voz=sello.datos["sello"].get("voz", "").strip())


def validar_plan(plan: dict[str, Any], sello: Sello, serie_id: str, lunes: date) -> dict[str, Any]:
    """Recorta a lo que el sistema puede ejecutar: fechas de la semana, slugs reales, formatos de la plantilla."""
    serie = sello.series[serie_id]
    slugs = {l.slug for l in serie.libros}
    semana = sello.datos.get("plan", {}).get("semana", {})
    dias_ok = []
    for i in range(7):
        f = lunes + timedelta(days=i)
        formatos_dia = list(semana.get(i, []))
        piezas = []
        for d in plan.get("dias", []):
            if d.get("fecha") != f.isoformat():
                continue
            for p in d.get("piezas", []):
                if p.get("libro_slug") not in slugs or p.get("formato") not in FORMATOS:
                    continue
                piezas.append({**p, "serie": serie_id})
        # el número de piezas y los formatos los fija la plantilla; el Estratega aporta libro y ángulo
        ajustadas = []
        for k, fmt in enumerate(formatos_dia):
            cand = next((p for p in piezas if p["formato"] == fmt and p not in ajustadas), None) or (piezas[k] if k < len(piezas) else None)
            if cand:
                ajustadas.append({**cand, "formato": fmt})
        dias_ok.append({"fecha": f.isoformat(), "piezas": ajustadas})
    return {"semana": lunes.isoformat(), "resumen": plan.get("resumen", ""), "dias": dias_ok,
            "sugerencias_bibliotecario": plan.get("sugerencias_bibliotecario", []), "generado_en": db.ahora()}


def generar_plan(con: sqlite3.Connection, sello: Sello, ia: ClienteIA, lunes: date, *, rehacer: bool = False) -> dict[str, Any] | None:
    if not rehacer and db.kv_get(con, clave_plan(lunes)):
        print(f"  = ya hay plan para la semana del {lunes}; usa --rehacer para sustituirlo")
        return json.loads(db.kv_get(con, clave_plan(lunes)) or "{}")
    series = sello.series_activas()
    if not series:
        return None
    serie = series[0]  # Fase 2: una serie activa; con varias, el Estratega recibirá todas en Fase 3
    ctx = contexto(con, sello, serie.id, lunes)
    usuario = ("Planifica la semana con estos datos. Los `formatos` de cada día son la plantilla que hay que respetar "
               "(una pieza por formato, en ese orden).\n\n" + json.dumps(ctx, ensure_ascii=False, indent=1))
    crudo = ia.json(construir_sistema(sello), usuario, ESQUEMA, max_tokens=6000)
    if crudo is None:
        return None
    plan = validar_plan(crudo, sello, serie.id, lunes)
    db.kv_set(con, clave_plan(lunes), json.dumps(plan, ensure_ascii=False))
    n = sum(len(d["piezas"]) for d in plan["dias"])
    print(f"  ✓ plan de la semana del {lunes}: {n} piezas")
    for d in plan["dias"]:
        for p in d["piezas"]:
            print(f"    {d['fecha']} {p['formato']:<8} {p['libro_slug']:<30} [{p['tipo_preferido']}] {p['angulo'][:70]}")
    return plan


def main(argv: list[str] | None = None) -> int:
    consola_utf8()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sello", default="kaizen")
    p.add_argument("--db", type=Path, default=DB_POR_DEFECTO)
    p.add_argument("--lunes", type=date.fromisoformat)
    p.add_argument("--rehacer", action="store_true")
    p.add_argument("--ver", action="store_true")
    a = p.parse_args(argv)
    sello = cargar_sello(a.sello)
    con = db.conectar(a.db)
    lunes = a.lunes or proximo_lunes()
    if a.ver:
        plan = json.loads(db.kv_get(con, clave_plan(lunes)) or "null")
        print(json.dumps(plan, ensure_ascii=False, indent=1) if plan else f"sin plan para {lunes}")
        return 0
    ia = cliente_para(sello, "estratega")
    ej = db.abrir_ejecucion(con, "estratega", ia.modelo)
    plan = generar_plan(con, sello, ia, lunes, rehacer=a.rehacer)
    db.cerrar_ejecucion(con, ej, ok=plan is not None, detalle=json.dumps({"semana": lunes.isoformat()}),
                        tokens_entrada=ia.tokens["entrada"], tokens_salida=ia.tokens["salida"],
                        tokens_cache_lectura=ia.tokens["cache_lectura"], coste_usd=ia.coste_usd())
    print(ia.resumen())
    return 0 if plan else 1


if __name__ == "__main__":
    sys.exit(main())
