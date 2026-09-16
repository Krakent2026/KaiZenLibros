"""Locutor: piezas de formato `audio` → MP3 en web/static/podcast/<id>.mp3 y feed RSS.

    python -m agentes.locutor.sintetizar            # sintetiza lo pendiente y regenera el feed
    python -m agentes.locutor.sintetizar --id 12
    python -m agentes.locutor.sintetizar --feed     # solo regenera feed.xml y episodios.json

Voz: Edge TTS (Microsoft, gratuita, sin clave). El MP3 sale a 24 kHz / 48 kbps: unos 1,8 MB por cinco
minutos. El feed y los MP3 se publican con la web (GitHub Pages) y se dan de alta una vez en Spotify
for Creators y Apple Podcasts con la URL del feed.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from agentes import db
from agentes.config import DB_POR_DEFECTO, RAIZ_REPO, Sello, cargar_sello, consola_utf8
from agentes.enlaces import enlace_compra, web_base

PALABRAS_POR_MINUTO = 145


def dir_podcast(sello: Sello) -> Path:
    return RAIZ_REPO / "web" / sello.datos.get("podcast", {}).get("ruta_web", "static/podcast").strip("/")


def url_podcast(sello: Sello, fichero: str) -> str:
    ruta = sello.datos.get("podcast", {}).get("ruta_web", "static/podcast").strip("/")
    return f"{web_base(sello)}/{ruta}/{fichero}"


def texto_locucion(fila: sqlite3.Row, contenido: dict[str, Any], sello: Sello) -> str:
    pod = sello.datos.get("podcast", {})
    serie = sello.series[fila["serie"]]
    titulo = contenido.get("titulo_episodio", "").strip()
    guion = contenido.get("guion_audio", "").strip()
    partes = [
        f"{pod.get('titulo', 'Pódcast')}. {titulo}.",
        f"Una idea de «{fila['libro_titulo']}», libro {fila['libro_numero']} de la serie {serie.nombre_amazon}, de {sello.nombre}.",
        guion,
        f"Esto ha sido {pod.get('titulo', 'el pódcast')}. El libro es «{fila['libro_titulo']}». {pod.get('aviso_voz', '')}".strip(),
    ]
    return "\n\n".join(p for p in partes if p)


def duracion_estimada_seg(texto: str) -> int:
    return int(len(texto.split()) / PALABRAS_POR_MINUTO * 60) + 4


async def _sintetizar(texto: str, voz: str, velocidad: str, salida: Path) -> None:
    import edge_tts

    comm = edge_tts.Communicate(texto, voz, rate=velocidad)
    await comm.save(str(salida))


def producir_audio(fila: sqlite3.Row, contenido: dict[str, Any], sello: Sello) -> Path:
    pod = sello.datos.get("podcast", {})
    destino = dir_podcast(sello) / f"{fila['id']}.mp3"
    destino.parent.mkdir(parents=True, exist_ok=True)
    texto = texto_locucion(fila, contenido, sello)
    asyncio.run(_sintetizar(texto, pod.get("voz", "es-ES-AlvaroNeural"), pod.get("velocidad", "+0%"), destino))
    if not destino.exists() or destino.stat().st_size < 10_000:
        raise RuntimeError("Edge TTS no generó audio válido")
    return destino


def sintetizar_pendientes(con: sqlite3.Connection, sello: Sello, ids: list[int] | None = None) -> int:
    n = 0
    for fila in db.piezas(con, "pendiente_humano", "aprobada"):
        if fila["formato"] != "audio" or fila["ruta_audio"]:
            continue
        if ids and fila["id"] not in ids:
            continue
        contenido = db.contenido_de(fila)
        if not contenido.get("guion_audio"):
            print(f"  ! pieza #{fila['id']}: sin guion; no se sintetiza")
            continue
        try:
            ruta = producir_audio(fila, contenido, sello)
        except Exception as e:  # noqa: BLE001
            print(f"  ! pieza #{fila['id']}: {e}")
            continue
        db.actualizar_pieza(con, fila["id"], ruta_audio=str(ruta.relative_to(RAIZ_REPO)).replace("\\", "/"))
        n += 1
        print(f"  ✓ pieza #{fila['id']}: audio {ruta.name} ({ruta.stat().st_size // 1024} KB, ~{duracion_estimada_seg(texto_locucion(fila, contenido, sello)) // 60} min)")
    return n


# ---- feed RSS ---------------------------------------------------------------------------
def episodios(con: sqlite3.Connection, sello: Sello, incluir: int | None = None) -> list[dict[str, Any]]:
    filas = con.execute(
        """SELECT c.*, l.titulo AS libro_titulo, l.numero AS libro_numero, l.slug AS libro_slug,
                  (SELECT MIN(p.publicado_en) FROM publicaciones p WHERE p.cola_id = c.id AND p.canal = 'podcast') AS publicado_podcast
           FROM cola c JOIN libros l ON l.id = c.libro_id
           WHERE c.formato = 'audio' AND c.ruta_audio IS NOT NULL
             AND (c.id = ? OR EXISTS (SELECT 1 FROM publicaciones p WHERE p.cola_id = c.id AND p.canal = 'podcast'))
           ORDER BY COALESCE(publicado_podcast, c.publicada_en, c.actualizado_en) DESC""", (incluir or -1,)).fetchall()
    salida = []
    for f in filas:
        contenido = db.contenido_de(f)
        ruta = RAIZ_REPO / f["ruta_audio"]
        if not ruta.exists():
            continue
        texto = texto_locucion(f, contenido, sello)
        fecha = f["publicado_podcast"] or f["publicada_en"] or db.ahora()
        salida.append({
            "id": f["id"], "titulo": contenido.get("titulo_episodio") or f["libro_titulo"],
            "descripcion": (contenido.get("telegram") or contenido.get("caption_instagram", ""))[:900],
            "libro": f["libro_titulo"], "libro_slug": f["libro_slug"], "numero_libro": f["libro_numero"],
            "fecha": fecha, "mp3": url_podcast(sello, ruta.name), "bytes": ruta.stat().st_size,
            "duracion_seg": duracion_estimada_seg(texto), "enlace": enlace_compra(sello, f["libro_slug"], "pod"),
        })
    return salida


def _hms(seg: int) -> str:
    return f"{seg // 3600:02d}:{seg % 3600 // 60:02d}:{seg % 60:02d}"


def generar_feed(con: sqlite3.Connection, sello: Sello, incluir: int | None = None) -> Path:
    pod = sello.datos.get("podcast", {})
    eps = episodios(con, sello, incluir)
    carpeta = dir_podcast(sello)
    carpeta.mkdir(parents=True, exist_ok=True)
    web = web_base(sello)
    portada = f"{web}/static/podcast/portada.jpg"
    items = []
    for e in eps:
        fecha = format_datetime(datetime.fromisoformat(e["fecha"]).astimezone(timezone.utc))
        desc = escape(e["descripcion"] + f"\n\nEl libro: {e['libro']}. {e['enlace']}")
        items.append(f"""    <item>
      <title>{escape(e['titulo'])}</title>
      <description>{desc}</description>
      <enclosure url="{e['mp3']}" length="{e['bytes']}" type="audio/mpeg"/>
      <guid isPermaLink="false">kaizen-podcast-{e['id']}</guid>
      <pubDate>{fecha}</pubDate>
      <itunes:duration>{_hms(e['duracion_seg'])}</itunes:duration>
      <itunes:explicit>false</itunes:explicit>
      <link>{web}/libros/{e['libro_slug']}/</link>
    </item>""")
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>{escape(pod.get('titulo', sello.nombre))}</title>
    <link>{web}/podcast/</link>
    <atom:link href="{url_podcast(sello, 'feed.xml')}" rel="self" type="application/rss+xml"/>
    <language>{pod.get('idioma', 'es-es')}</language>
    <description>{escape(pod.get('descripcion', ''))}</description>
    <itunes:author>{escape(pod.get('autor', sello.nombre))}</itunes:author>
    <itunes:owner><itunes:name>{escape(pod.get('autor', sello.nombre))}</itunes:name><itunes:email>{escape(pod.get('email', ''))}</itunes:email></itunes:owner>
    <itunes:image href="{portada}"/>
    <itunes:category text="{escape(pod.get('categoria', 'Self-Improvement'))}"/>
    <itunes:explicit>false</itunes:explicit>
    <itunes:type>episodic</itunes:type>
{chr(10).join(items)}
  </channel>
</rss>
"""
    (carpeta / "feed.xml").write_text(xml, encoding="utf-8")
    (carpeta / "episodios.json").write_text(json.dumps(eps, ensure_ascii=False, indent=1), encoding="utf-8")
    return carpeta / "feed.xml"


def main(argv: list[str] | None = None) -> int:
    consola_utf8()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sello", default="kaizen")
    p.add_argument("--db", type=Path, default=DB_POR_DEFECTO)
    p.add_argument("--id", type=int, action="append")
    p.add_argument("--feed", action="store_true")
    a = p.parse_args(argv)
    sello = cargar_sello(a.sello)
    con = db.conectar(a.db)
    if not a.feed:
        print(f"{sintetizar_pendientes(con, sello, a.id)} audios generados")
    ruta = generar_feed(con, sello)
    print(f"feed: {ruta.relative_to(RAIZ_REPO)} ({len(episodios(con, sello))} episodios)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
