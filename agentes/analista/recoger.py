"""Recoge métricas por API de lo publicado en los últimos días y las guarda en `metricas`.
También anota seguidores/miembros por canal en kv (`seguidores:<canal>:<fecha>`).

    python -m agentes.analista.recoger
Cada conector falla por separado y en silencio razonable: una API caída no para el resto.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import date
from pathlib import Path
from typing import Any

import requests

from agentes import db
from agentes.config import DB_POR_DEFECTO, Sello, cargar_sello, consola_utf8


def _ig(token: str, ruta: str, **params: Any) -> dict[str, Any]:
    r = requests.get(f"https://graph.instagram.com/v23.0/{ruta}", params={**params, "access_token": token}, timeout=30)
    return r.json()


def _insights_a_dict(datos: dict[str, Any]) -> dict[str, int]:
    salida: dict[str, int] = {}
    for m in datos.get("data", []):
        nombre = m.get("name")
        valor = None
        if "total_value" in m:
            valor = m["total_value"].get("value")
        elif m.get("values"):
            valor = m["values"][-1].get("value")
        if nombre and isinstance(valor, (int, float)):
            salida[nombre] = int(valor)
    return salida


def metricas_instagram(pub: sqlite3.Row) -> dict[str, int] | None:
    token = os.environ.get("INSTAGRAM_TOKEN", "")
    if not token or not pub["id_externo"]:
        return None
    d = _insights_a_dict(_ig(token, f"{pub['id_externo']}/insights", metric="views,reach,likes,comments,saved,shares"))
    if not d:
        return None
    return {"impresiones": d.get("views"), "alcance": d.get("reach"), "me_gusta": d.get("likes"),
            "comentarios": d.get("comments"), "guardados": d.get("saved"), "compartidos": d.get("shares")}


def metricas_pinterest(pub: sqlite3.Row) -> dict[str, int] | None:
    from herramientas.comprobar_credenciales import pinterest_token_desde_refresh  # reutiliza la renovación

    token = pinterest_token_desde_refresh() or os.environ.get("PINTEREST_TOKEN", "")
    if not token or not pub["id_externo"]:
        return None
    r = requests.get(f"https://api.pinterest.com/v5/pins/{pub['id_externo']}/analytics",
                     headers={"Authorization": f"Bearer {token}"},
                     params={"start_date": pub["publicado_en"][:10], "end_date": date.today().isoformat(),
                             "metric_types": "IMPRESSION,SAVE,PIN_CLICK,OUTBOUND_CLICK"}, timeout=30)
    if not r.ok:
        return None
    todo = r.json().get("all", {})
    m = todo.get("lifetime_metrics") or todo.get("summary_metrics") or {}
    if not m:
        return None
    return {"impresiones": int(m.get("IMPRESSION", 0)), "guardados": int(m.get("SAVE", 0)),
            "clics": int(m.get("PIN_CLICK", 0)) + int(m.get("OUTBOUND_CLICK", 0))}


def metricas_bluesky(pub: sqlite3.Row) -> dict[str, int] | None:
    if not pub["id_externo"] or not pub["id_externo"].startswith("at://"):
        return None
    r = requests.get("https://public.api.bsky.app/xrpc/app.bsky.feed.getPosts", params={"uris": pub["id_externo"]}, timeout=30)
    posts = r.json().get("posts", []) if r.ok else []
    if not posts:
        return None
    p = posts[0]
    return {"me_gusta": p.get("likeCount", 0), "compartidos": p.get("repostCount", 0) + p.get("quoteCount", 0),
            "comentarios": p.get("replyCount", 0)}


def metricas_threads(pub: sqlite3.Row) -> dict[str, int] | None:
    token = os.environ.get("THREADS_TOKEN", "")
    if not token or not pub["id_externo"]:
        return None
    r = requests.get(f"https://graph.threads.net/v1.0/{pub['id_externo']}/insights",
                     params={"metric": "views,likes,replies,reposts,quotes", "access_token": token}, timeout=30)
    d = _insights_a_dict(r.json()) if r.ok else {}
    if not d:
        return None
    return {"impresiones": d.get("views"), "me_gusta": d.get("likes"), "comentarios": d.get("replies"),
            "compartidos": (d.get("reposts") or 0) + (d.get("quotes") or 0)}


RECOLECTORES = {"instagram": metricas_instagram, "pinterest": metricas_pinterest, "bluesky": metricas_bluesky, "threads": metricas_threads}


def seguidores(con: sqlite3.Connection, hoy: str) -> dict[str, int]:
    salida: dict[str, int] = {}
    tok, canal = os.environ.get("TELEGRAM_BOT_TOKEN", ""), os.environ.get("TELEGRAM_CANAL", "")
    if tok and canal:
        try:
            r = requests.get(f"https://api.telegram.org/bot{tok}/getChatMemberCount", params={"chat_id": canal}, timeout=30).json()
            if r.get("ok"):
                salida["telegram"] = int(r["result"])
        except requests.RequestException:
            pass
    ig = os.environ.get("INSTAGRAM_TOKEN", "")
    if ig:
        try:
            r = _ig(ig, "me", fields="followers_count,media_count")
            if "followers_count" in r:
                salida["instagram"] = int(r["followers_count"])
        except requests.RequestException:
            pass
    bs = os.environ.get("BLUESKY_USUARIO", "")
    if bs:
        try:
            r = requests.get("https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile", params={"actor": bs}, timeout=30).json()
            if "followersCount" in r:
                salida["bluesky"] = int(r["followersCount"])
        except requests.RequestException:
            pass
    for canal_, n in salida.items():
        db.kv_set(con, f"seguidores:{canal_}:{hoy}", str(n))
    return salida


def recoger_metricas(con: sqlite3.Connection, sello: Sello) -> dict[str, int]:
    hoy = date.today().isoformat()
    ventana = int(sello.datos.get("analista", {}).get("ventana_dias", 30))
    r = {"medidas": 0, "sin_datos": 0}
    for pub in db.publicaciones_recientes(con, ventana):
        fn = RECOLECTORES.get(pub["canal"])
        if not fn:
            continue
        try:
            m = fn(pub)
        except Exception as e:  # noqa: BLE001
            print(f"  ! {pub['canal']} #{pub['id']}: {e}")
            m = None
        if m:
            db.guardar_metrica(con, pub["id"], hoy, pub["canal"], **{k: v for k, v in m.items() if v is not None})
            r["medidas"] += 1
        else:
            r["sin_datos"] += 1
    seg = seguidores(con, hoy)
    if seg:
        print("  seguidores: " + " · ".join(f"{k} {v}" for k, v in seg.items()))
    return r


def main(argv: list[str] | None = None) -> int:
    consola_utf8()
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sello", default="kaizen")
    p.add_argument("--db", type=Path, default=DB_POR_DEFECTO)
    a = p.parse_args(argv)
    print(recoger_metricas(db.conectar(a.db), cargar_sello(a.sello)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
