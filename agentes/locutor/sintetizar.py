"""Locutor: piezas de formato `audio` → MP3 en web/static/podcast/<id>.mp3 y feed RSS.

    python -m agentes.locutor.sintetizar            # sintetiza lo pendiente y regenera el feed
    python -m agentes.locutor.sintetizar --id 12
    python -m agentes.locutor.sintetizar --feed     # solo regenera feed.xml y episodios.json

Voz, por orden de preferencia (`podcast.motor: auto`): Gemini TTS si hay GEMINI_API_KEY (voz dirigida por
instrucciones, nivel gratuito de AI Studio), Azure Speech si hay AZURE_SPEECH_KEY, y si no Edge TTS (gratis, sin
clave). Si el motor elegido falla, cae al siguiente: el episodio sale siempre. El MP3 sale a 24 kHz / 48 kbps: unos 1,8 MB
por cinco minutos.
    python -m agentes.locutor.sintetizar --id 8 --rehacer   # vuelve a grabar un episodio ya publicado El feed y los MP3 se publican con la web (GitHub Pages) y se dan de alta una vez en Spotify
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


async def _sintetizar_edge(texto: str, voz: str, velocidad: str, tono: str, salida: Path) -> None:
    import edge_tts

    comm = edge_tts.Communicate(texto, voz, rate=velocidad, pitch=tono)
    await comm.save(str(salida))


def ssml_azure(texto: str, voz: str, velocidad: str, tono: str, idioma: str = "es-ES") -> str:
    """Un párrafo por bloque del guion, con una pausa breve entre ellos: la voz respira donde respiraría un locutor."""
    parrafos = [escape(pz.strip()) for pz in texto.split("\n\n") if pz.strip()]
    cuerpo = '<break time="700ms"/>'.join(f"<p>{pz}</p>" for pz in parrafos)
    prosodia = f'<prosody rate="{velocidad}" pitch="{tono}">' if (velocidad not in ("", "+0%") or tono not in ("", "+0Hz")) else ""
    cierre = "</prosody>" if prosodia else ""
    return (f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="{idioma}">'
            f'<voice name="{voz}">{prosodia}{cuerpo}{cierre}</voice></speak>')


def _sintetizar_azure(texto: str, voz: str, velocidad: str, tono: str, salida: Path, clave: str, region: str) -> None:
    import requests

    r = requests.post(
        f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1",
        headers={"Ocp-Apim-Subscription-Key": clave, "Content-Type": "application/ssml+xml",
                 "X-Microsoft-OutputFormat": "audio-24khz-48kbitrate-mono-mp3", "User-Agent": "KaiZenLocutor"},
        data=ssml_azure(texto, voz, velocidad, tono).encode("utf-8"), timeout=180)
    if r.status_code != 200:
        raise RuntimeError(f"Azure Speech {r.status_code}: {r.text[:200]}")
    salida.write_bytes(r.content)


def pcm_a_mp3(pcm: bytes, rate: int, salida: Path, kbps: int = 48) -> None:
    import lameenc

    enc = lameenc.Encoder()
    enc.set_bit_rate(kbps)
    enc.set_in_sample_rate(rate)
    enc.set_channels(1)
    enc.set_quality(2)
    salida.write_bytes(enc.encode(pcm) + enc.flush())


ESTILO_GEMINI_POR_DEFECTO = ("Lee este guion de pódcast en español de España, con acento castellano peninsular. Voz cálida y cercana, "
                             "como quien cuenta algo a una amiga en la cocina: ritmo tranquilo, sin dramatizar, sin entusiasmo forzado, "
                             "pausas naturales entre párrafos. No leas ninguna instrucción, solo el guion.")


def _sintetizar_gemini(texto: str, voz: str, modelo: str, estilo: str, salida: Path, clave: str) -> None:
    """Gemini TTS: una petición por episodio; devuelve PCM 16 bits que se codifica a MP3 aquí."""
    import base64
    import re

    import requests

    cuerpo = {"contents": [{"parts": [{"text": f"{estilo.strip()}\n\nGUION:\n{texto}"}]}],
              "generationConfig": {"responseModalities": ["AUDIO"],
                                   "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voz}}}}}
    r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent",
                      headers={"x-goog-api-key": clave, "Content-Type": "application/json"}, json=cuerpo, timeout=300)
    if r.status_code != 200:
        raise RuntimeError(f"Gemini TTS {r.status_code}: {r.text[:200]}")
    parte = r.json()["candidates"][0]["content"]["parts"][0]["inlineData"]
    m = re.search(r"rate=(\d+)", parte.get("mimeType", ""))
    pcm_a_mp3(base64.b64decode(parte["data"]), int(m.group(1)) if m else 24000, salida)


def motores_disponibles(sello: Sello) -> list[str]:
    """`podcast.motor`: gemini | azure | edge | auto. En auto, el orden de caída es gemini → azure → edge."""
    import os

    motor = sello.datos.get("podcast", {}).get("motor", "auto")
    if motor != "auto":
        return [motor, "edge"] if motor != "edge" else ["edge"]
    orden = []
    if os.environ.get("GEMINI_API_KEY"):
        orden.append("gemini")
    if os.environ.get("AZURE_SPEECH_KEY"):
        orden.append("azure")
    return orden + ["edge"]


def motor_activo(sello: Sello) -> str:
    return motores_disponibles(sello)[0]


def sintetizar_texto(texto: str, sello: Sello, salida: Path) -> str:
    """Graba `texto` en `salida` con el motor configurado. Devuelve el nombre del motor usado.
    Si Azure falla (clave caducada, voz HD no disponible en la región), cae a Edge para no dejar el episodio sin audio."""
    import os

    pod = sello.datos.get("podcast", {})
    velocidad, tono = pod.get("velocidad", "+0%"), pod.get("tono", "+0Hz")
    for motor in motores_disponibles(sello):
        try:
            if motor == "gemini":
                _sintetizar_gemini(texto, pod.get("voz_gemini", "Sulafat"), pod.get("modelo_gemini", "gemini-2.5-flash-preview-tts"),
                                   pod.get("estilo_gemini") or ESTILO_GEMINI_POR_DEFECTO, salida, os.environ["GEMINI_API_KEY"])
            elif motor == "azure":
                _sintetizar_azure(texto, pod.get("voz_azure") or pod.get("voz", "es-ES-ElviraNeural"), velocidad, tono, salida,
                                  os.environ["AZURE_SPEECH_KEY"], os.environ.get("AZURE_SPEECH_REGION", "westeurope"))
            else:
                asyncio.run(_sintetizar_edge(texto, pod.get("voz", "es-ES-ElviraNeural"), velocidad, tono, salida))
            if salida.exists() and salida.stat().st_size >= 10_000:
                return motor
            raise RuntimeError("audio vacío")
        except Exception as e:  # noqa: BLE001
            print(f"  ! {motor} falló ({e}); se prueba el siguiente motor")
    raise RuntimeError("ningún motor de voz generó audio")


def producir_audio(fila: sqlite3.Row, contenido: dict[str, Any], sello: Sello) -> Path:
    destino = dir_podcast(sello) / f"{fila['id']}.mp3"
    destino.parent.mkdir(parents=True, exist_ok=True)
    texto = texto_locucion(fila, contenido, sello)
    motor = sintetizar_texto(texto, sello, destino)
    if not destino.exists() or destino.stat().st_size < 10_000:
        raise RuntimeError(f"{motor} no generó audio válido")
    return destino


def sintetizar_pendientes(con: sqlite3.Connection, sello: Sello, ids: list[int] | None = None, rehacer: bool = False) -> int:
    n = 0
    filas = (con.execute("SELECT c.*, l.titulo AS libro_titulo, l.numero AS libro_numero FROM cola c JOIN libros l ON l.id = c.libro_id "
                         "WHERE c.formato = 'audio' AND c.id IN (%s)" % ",".join("?" * len(ids)), ids).fetchall()
             if rehacer and ids else db.piezas(con, "pendiente_humano", "aprobada"))
    for fila in filas:
        if fila["formato"] != "audio" or (fila["ruta_audio"] and not rehacer):
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
        if rehacer and fila["ruta_audio"]:
            # guid nuevo: las plataformas que guardan copia del MP3 (Spotify) lo tratan como episodio nuevo y bajan el audio actual
            rev = int(db.kv_get(con, f"podcast_rev:{fila['id']}") or "1") + 1
            db.kv_set(con, f"podcast_rev:{fila['id']}", str(rev))
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
            "id": f["id"], "guid": f"kaizen-podcast-{f['id']}" + (f"-v{rev}" if (rev := db.kv_get(con, f"podcast_rev:{f['id']}")) else ""),
            "titulo": contenido.get("titulo_episodio") or f["libro_titulo"],
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
      <guid isPermaLink="false">{e['guid']}</guid>
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
    p.add_argument("--rehacer", action="store_true", help="vuelve a grabar los --id aunque ya tengan audio o estén publicados")
    a = p.parse_args(argv)
    sello = cargar_sello(a.sello)
    con = db.conectar(a.db)
    if not a.feed:
        print(f"{sintetizar_pendientes(con, sello, a.id, rehacer=a.rehacer)} audios generados ({motor_activo(sello)})")
    ruta = generar_feed(con, sello)
    print(f"feed: {ruta.relative_to(RAIZ_REPO)} ({len(episodios(con, sello))} episodios)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
