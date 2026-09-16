"""Publica las piezas aprobadas cuya hora ha llegado, canal a canal.

    python -m agentes.publicador.publicar            # lo vencido
    python -m agentes.publicador.publicar --id 12 --ahora
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agentes import db
from agentes.config import DB_POR_DEFECTO, Sello, cargar_sello, consola_utf8
from agentes.disenador.render import activos_de
from agentes.publicador.base import NoDisponible, Publicador
from agentes.publicador.instagram import PublicadorInstagram
from agentes.publicador.pinterest import PublicadorPinterest
from agentes.publicador.telegram import PublicadorTelegram

CONECTORES: dict[str, type[Publicador]] = {
    "telegram": PublicadorTelegram,
    "pinterest": PublicadorPinterest,
    "instagram": PublicadorInstagram,
}


def conectores_activos(sello: Sello) -> dict[str, Publicador]:
    activos: dict[str, Publicador] = {}
    for nombre in sello.datos.get("publicacion", {}).get("canales", []):
        cls = CONECTORES.get(nombre)
        if not cls:
            continue
        c = cls()
        if c.disponible():
            activos[nombre] = c
    return activos


def publicar_vencidas(con: sqlite3.Connection, sello: Sello, *, ahora: datetime | None = None,
                      ids: list[int] | None = None, forzar_hora: bool = False) -> dict[str, int]:
    ahora = ahora or datetime.now(timezone.utc)
    activos = conectores_activos(sello)
    r = {"publicadas": 0, "parciales": 0, "esperando": 0, "errores": 0}
    if not activos:
        print("  · ningún canal con credenciales; las piezas aprobadas esperan")
        return r
    pub = sello.datos.get("publicacion", {})
    antelacion = timedelta(minutes=int(pub.get("antelacion_minima_min", 0)))
    hay_telegram = bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_APROBACION"))
    for fila in db.piezas(con, "aprobada"):
        if ids and fila["id"] not in ids:
            continue
        if not forzar_hora and fila["programado_para"] and datetime.fromisoformat(fila["programado_para"]) > ahora:
            r["esperando"] += 1
            continue
        # Ventana de cancelación: la previa tiene que haber llegado a Telegram con antelación suficiente.
        if not forzar_hora and hay_telegram and antelacion:
            enviado = fila["enviado_humano_en"]
            if not enviado or datetime.fromisoformat(enviado) + antelacion > ahora:
                r["esperando"] += 1
                print(f"  · pieza #{fila['id']}: ventana de cancelación abierta hasta {antelacion.seconds // 60} min "
                      f"después del aviso en Telegram")
                continue
        imagenes = activos_de(fila)
        if not imagenes:
            print(f"  ! pieza #{fila['id']} aprobada sin imágenes; se produce en la próxima corrida")
            continue
        contenido = db.contenido_de(fila)
        canales_pieza = [c.strip() for c in (fila["canal"] or "").split(",") if c.strip()]
        hechos = db.canales_publicados(con, fila["id"])
        pendientes = [c for c in canales_pieza if c in activos and c not in hechos]
        for nombre in pendientes:
            try:
                res = activos[nombre].publicar(fila, contenido, imagenes, sello)
                db.registrar_publicacion(con, fila["id"], nombre, res.id_externo, res.url)
                hechos.add(nombre)
                print(f"  ✓ pieza #{fila['id']} → {nombre} {res.url or res.id_externo or ''}")
            except NoDisponible as e:
                print(f"  · pieza #{fila['id']} → {nombre} espera: {e}")
            except Exception as e:  # noqa: BLE001 — el canal falla, la pieza sigue viva para el siguiente intento
                r["errores"] += 1
                print(f"  ! pieza #{fila['id']} → {nombre} error: {e}")
        objetivo = {c for c in canales_pieza if c in activos}
        if objetivo and objetivo <= hechos:
            db.actualizar_pieza(con, fila["id"], estado="publicada", publicada_en=db.ahora())
            r["publicadas"] += 1
        elif hechos:
            r["parciales"] += 1
    return r


def main(argv: list[str] | None = None) -> int:
    consola_utf8()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sello", default="kaizen")
    p.add_argument("--db", type=Path, default=DB_POR_DEFECTO)
    p.add_argument("--id", type=int, action="append")
    p.add_argument("--ahora", action="store_true", help="ignora la hora programada")
    a = p.parse_args(argv)
    sello = cargar_sello(a.sello)
    con = db.conectar(a.db)
    r = publicar_vencidas(con, sello, ids=a.id, forzar_hora=a.ahora)
    print(r)
    return 0 if r["errores"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
