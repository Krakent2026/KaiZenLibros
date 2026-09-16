"""Informe semanal: qué salió, qué funcionó, seguidores, KDP y coste. Markdown a datos/salida y resumen a Telegram.

    python -m agentes.analista.informe [--dias 7] [--enviar]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

from agentes import db
from agentes.analista.kdp import resumen_kdp
from agentes.config import DB_POR_DEFECTO, RAIZ_REPO, Sello, cargar_sello, consola_utf8


def _seguidores(con: sqlite3.Connection, canal: str, fecha: date) -> int | None:
    fila = con.execute("SELECT valor FROM kv WHERE clave LIKE ? AND clave <= ? ORDER BY clave DESC LIMIT 1",
                       (f"seguidores:{canal}:%", f"seguidores:{canal}:{fecha.isoformat()}")).fetchone()
    return int(fila["valor"]) if fila else None


def generar_informe(con: sqlite3.Connection, sello: Sello, dias: int = 7) -> str:
    hoy = date.today()
    desde = hoy - timedelta(days=dias)
    L: list[str] = [f"# Informe semanal · {sello.nombre} · {desde.isoformat()} → {hoy.isoformat()}", ""]

    pubs = db.publicaciones_recientes(con, dias)
    por_canal: dict[str, int] = {}
    for p in pubs:
        por_canal[p["canal"]] = por_canal.get(p["canal"], 0) + 1
    L += ["## Publicado", f"{len(pubs)} publicaciones: " + (", ".join(f"{k} {v}" for k, v in sorted(por_canal.items())) or "ninguna"), ""]

    met = db.ultimas_metricas(con, dias)
    if met:
        L += ["## Lo que más llegó", "| Pieza | Libro | Canal | Alcance | Guardados | Me gusta |", "|---|---|---|---|---|---|"]
        for m in met[:8]:
            L.append(f"| #{m['cola_id']} {m['formato']} · {(m['gancho'] or '')[:40]} | L{m['libro_numero']} {m['libro_titulo']} | {m['canal']} | "
                     f"{m['alcance'] or m['impresiones'] or '—'} | {m['guardados'] or '—'} | {m['me_gusta'] or '—'} |")
        por_libro: dict[str, int] = {}
        por_tipo: dict[str, list[int]] = {}
        for m in met:
            a = m["alcance"] or m["impresiones"] or 0
            por_libro[m["libro_titulo"]] = por_libro.get(m["libro_titulo"], 0) + a
            por_tipo.setdefault(m["atomo_tipo"] or "?", []).append(a)
        L += ["", "**Alcance por libro:** " + ", ".join(f"{k} {v}" for k, v in sorted(por_libro.items(), key=lambda x: -x[1])[:6])]
        L += ["**Alcance medio por tipo de átomo:** " + ", ".join(f"{k} {sum(v)//len(v)}" for k, v in sorted(por_tipo.items(), key=lambda x: -sum(x[1])/len(x[1]))), ""]
    else:
        L += ["## Métricas", "Sin métricas todavía (se recogen a diario cuando los canales tienen credenciales).", ""]

    L.append("## Seguidores")
    for canal in ("instagram", "telegram", "bluesky"):
        ahora, antes = _seguidores(con, canal, hoy), _seguidores(con, canal, desde)
        if ahora is not None:
            delta = f" ({ahora - antes:+d} en {dias} días)" if antes is not None else ""
            L.append(f"- {canal}: {ahora}{delta}")
    L.append("")

    kdp = resumen_kdp(con, 30)
    if kdp:
        L += ["## KDP (últimos 30 días, según los CSV importados)", "| Título | Unidades | Gratis | KENP | Regalías |", "|---|---|---|---|---|"]
        for k in kdp[:12]:
            L.append(f"| {k['titulo'][:40]} | {k['unidades']:.0f} | {k['gratis']:.0f} | {k['kenp']:.0f} | {k['regalias']:.2f} |")
        L.append("")
    else:
        L += ["## KDP", "Sin datos: deja los CSV de KDP Reports en `datos/kdp/` y el Analista los importa.", ""]

    c = con.execute("SELECT COUNT(*) AS n, COALESCE(SUM(coste_usd),0) AS usd FROM ejecuciones WHERE inicio >= ?", (desde.isoformat(),)).fetchone()
    cola = {f["estado"]: f["n"] for f in db.resumen_cola(con)}
    L += ["## Sistema", f"- {c['n']} corridas · {c['usd']:.2f} USD de API en {dias} días",
          "- Cola: " + (", ".join(f"{k} {v}" for k, v in cola.items()) or "vacía"), ""]
    return "\n".join(L)


def guardar(texto: str) -> Path:
    carpeta = RAIZ_REPO / "datos" / "salida"
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / f"informe_{date.today().isoformat()}.md"
    ruta.write_text(texto, encoding="utf-8")
    return ruta


def resumen_telegram(texto: str, maximo: int = 3500) -> str:
    """Versión plana para Telegram: sin tablas Markdown, recortada."""
    lineas = []
    for l in texto.splitlines():
        if l.startswith("|---"):
            continue
        if l.startswith("|"):
            celdas = [c.strip() for c in l.strip("|").split("|")]
            lineas.append(" · ".join(celdas))
        else:
            lineas.append(l.replace("**", "").replace("# ", "").replace("#", ""))
    plano = "\n".join(lineas).strip()
    return plano[:maximo] + ("…" if len(plano) > maximo else "")


def main(argv: list[str] | None = None) -> int:
    consola_utf8()
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sello", default="kaizen")
    p.add_argument("--db", type=Path, default=DB_POR_DEFECTO)
    p.add_argument("--dias", type=int, default=7)
    p.add_argument("--enviar", action="store_true", help="manda el resumen al chat de Telegram")
    a = p.parse_args(argv)
    sello = cargar_sello(a.sello)
    con = db.conectar(a.db)
    texto = generar_informe(con, sello, a.dias)
    ruta = guardar(texto)
    print(texto)
    print(f"\n→ {ruta.relative_to(RAIZ_REPO)}")
    if a.enviar:
        import os

        from agentes.aprobacion.telegram import Telegram

        tg, chat = Telegram(), os.environ.get("TELEGRAM_CHAT_APROBACION", "")
        if tg.disponible and chat:
            tg.enviar_texto(chat, resumen_telegram(texto))
            print("enviado a Telegram")
    return 0


if __name__ == "__main__":
    sys.exit(main())
