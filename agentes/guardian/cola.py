"""Guardián sobre la cola: piezas `redactada` → `pendiente_humano` o `rechazada`.

Dos capas, en este orden:
  1. Determinista (siempre): vocabulario vetado, límites de cada canal, número de diapositivas,
     hashtags, y que la cita literal del átomo esté intacta.
  2. Criterio (modelo, si hay credenciales): tono, promesas veladas, diagnóstico implícito.
Los avisos no bloquean: viajan con la pieza para que el humano los vea en Telegram.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from agentes import db
from agentes.config import Sello
from agentes.guardian.reglas import revisar
from agentes.guardian.verificar_citas import normalizar
from agentes.ia import ClienteIA

RUTA_PROMPT = Path(__file__).with_name("criterio.md")

LIMITES = {
    "caption_instagram": 2200,
    "pin_titulo": 100,
    "pin_descripcion": 800,
    "telegram": 1024,          # cabe como caption de una foto en Telegram
    "diapositiva_titulo": 70,
    "diapositiva_cuerpo": 260,
    "gancho": 100,
    "alt_texto": 250,
    "bluesky": 280,
    "threads": 480,
    "x": 245,
    "titulo_episodio": 70,
}
GUION_PALABRAS = (450, 1100)
DIAPOSITIVAS = {"carrusel": (5, 7), "cita": (1, 1), "audio": (1, 1), "sello": (5, 7), "serie": (5, 7)}
CON_GANCHO = ("carrusel", "sello", "serie")

ESQUEMA_CRITERIO: dict[str, Any] = {
    "type": "object",
    "properties": {
        "aprobado": {"type": "boolean"},
        "motivos": {"type": "array", "items": {"type": "string"}},
        "avisos": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["aprobado", "motivos", "avisos"],
    "additionalProperties": False,
}


def textos_de(contenido: dict[str, Any]) -> list[tuple[str, str]]:
    salida: list[tuple[str, str]] = []
    for i, d in enumerate(contenido.get("diapositivas", []), 1):
        salida.append((f"diapositiva {i} título", d.get("titulo", "")))
        salida.append((f"diapositiva {i} cuerpo", d.get("cuerpo", "")))
    for i, g in enumerate(contenido.get("ganchos", []), 1):
        salida.append((f"gancho {i}", g))
    salida.append(("caption", contenido.get("caption_instagram", "")))
    salida.append(("pin título", contenido.get("pin", {}).get("titulo", "")))
    salida.append(("pin descripción", contenido.get("pin", {}).get("descripcion", "")))
    salida.append(("telegram", contenido.get("telegram", "")))
    salida.append(("bluesky", contenido.get("bluesky", "")))
    salida.append(("threads", contenido.get("threads", "")))
    salida.append(("x", contenido.get("x", "")))
    salida.append(("alt", contenido.get("alt_texto", "")))
    salida.append(("hashtags", " ".join(contenido.get("hashtags", []))))
    if contenido.get("guion_audio"):
        salida.append(("guion", contenido["guion_audio"]))
        salida.append(("título episodio", contenido.get("titulo_episodio", "")))
    return salida


def revisar_determinista(fila: sqlite3.Row, contenido: dict[str, Any], sello: Sello) -> tuple[list[str], list[str]]:
    motivos: list[str] = []
    avisos: list[str] = []
    idioma = sello.datos["sello"].get("idioma", "es")
    literal_atomo = normalizar(fila["atomo_texto"] or "")

    # 1. vocabulario, campo a campo
    for nombre, texto in textos_de(contenido):
        if not texto:
            continue
        for h in revisar(texto, idioma):
            # una cita literal del libro puede contener vocabulario que fuera de contexto sería promesa: solo aviso
            if h.nivel == "bloquea" and fila["es_literal"] and normalizar(texto) == literal_atomo:
                avisos.append(f"{nombre}: la cita literal contiene «{h.coincidencia}» ({h.nota})")
            elif h.nivel == "bloquea":
                motivos.append(f"{nombre}: «{h.coincidencia}» — {h.nota}")
            else:
                avisos.append(f"{nombre}: «{h.coincidencia}» — {h.nota}")

    # 2. estructura y límites
    diapositivas = contenido.get("diapositivas", [])
    minimo, maximo = DIAPOSITIVAS.get(fila["formato"], (1, 7))
    if not minimo <= len(diapositivas) <= maximo:
        motivos.append(f"{len(diapositivas)} diapositivas; el formato {fila['formato']} admite de {minimo} a {maximo}")
    for i, d in enumerate(diapositivas, 1):
        if len(d.get("titulo", "")) > LIMITES["diapositiva_titulo"]:
            motivos.append(f"diapositiva {i}: título de {len(d['titulo'])} caracteres (máx. {LIMITES['diapositiva_titulo']})")
        if len(d.get("cuerpo", "")) > LIMITES["diapositiva_cuerpo"]:
            motivos.append(f"diapositiva {i}: cuerpo de {len(d['cuerpo'])} caracteres (máx. {LIMITES['diapositiva_cuerpo']})")
    if fila["formato"] in CON_GANCHO and diapositivas and not diapositivas[0].get("titulo"):
        motivos.append("la diapositiva 1 del carrusel necesita título (gancho)")
    if len(contenido.get("caption_instagram", "")) > LIMITES["caption_instagram"]:
        motivos.append("caption de Instagram demasiado largo")
    if len(contenido.get("pin", {}).get("titulo", "")) > LIMITES["pin_titulo"]:
        motivos.append("título de pin demasiado largo")
    if len(contenido.get("pin", {}).get("descripcion", "")) > LIMITES["pin_descripcion"]:
        motivos.append("descripción de pin demasiado larga")
    if len(contenido.get("telegram", "")) > LIMITES["telegram"]:
        motivos.append("texto de Telegram demasiado largo para ir como pie de foto")
    for campo in ("bluesky", "threads", "x"):
        if len(contenido.get(campo, "")) > LIMITES[campo]:
            motivos.append(f"texto de {campo} de {len(contenido[campo])} caracteres (máx. {LIMITES[campo]})")
    if fila["formato"] == "audio":
        palabras = len(contenido.get("guion_audio", "").split())
        if not GUION_PALABRAS[0] <= palabras <= GUION_PALABRAS[1]:
            motivos.append(f"guion de {palabras} palabras; el episodio necesita entre {GUION_PALABRAS[0]} y {GUION_PALABRAS[1]}")
        if not contenido.get("titulo_episodio"):
            motivos.append("falta el título del episodio")
        elif len(contenido["titulo_episodio"]) > LIMITES["titulo_episodio"]:
            motivos.append("título de episodio demasiado largo")
    hashtags = contenido.get("hashtags", [])
    maximo_h = int(sello.datos.get("publicacion", {}).get("hashtags_max", 8))
    if len(hashtags) > maximo_h:
        motivos.append(f"{len(hashtags)} hashtags (máx. {maximo_h})")
    if any("#" in h or " " in h for h in hashtags):
        motivos.append("hashtags con almohadilla o espacios")
    ganchos = contenido.get("ganchos", [])
    if len(ganchos) < 3:
        avisos.append("menos de tres ganchos")
    if any(len(g) > LIMITES["gancho"] for g in ganchos):
        motivos.append("algún gancho supera los 100 caracteres")

    # 3. la cita literal intacta
    if fila["es_literal"] and fila["formato"] == "cita":
        cuerpo = diapositivas[0].get("cuerpo", "") if diapositivas else ""
        if normalizar(cuerpo) != literal_atomo:
            motivos.append("la cita no coincide letra a letra con el átomo")
    if fila["es_literal"] and fila["formato"] == "carrusel":
        if not any(literal_atomo in normalizar(d.get("cuerpo", "") + " " + d.get("titulo", "")) for d in diapositivas):
            avisos.append("el átomo es literal pero la cita exacta no aparece en ninguna diapositiva")

    # 4. remate: la pieza tiene que nombrar aquello de lo que habla
    todo = " ".join(t for _, t in textos_de(contenido)).lower()
    if fila["atomo_id"] is None:  # institucional
        serie_nombre = sello.series[fila["serie"]].nombre_amazon.lower()
        if fila["formato"] == "serie" and serie_nombre not in todo:
            motivos.append(f"la pieza no nombra la serie «{sello.series[fila['serie']].nombre_amazon}»")
        if fila["formato"] == "sello" and sello.nombre.lower() not in todo:
            motivos.append(f"la pieza no nombra el sello «{sello.nombre}»")
        if fila["formato"] == "serie" and (fila["libro_titulo"] or "").lower() not in todo:
            avisos.append(f"la presentación de la serie no nombra el Libro 1 «{fila['libro_titulo']}»")
    else:
        titulo = (fila["libro_titulo"] or "").lower()
        if titulo and titulo not in todo:
            motivos.append(f"la pieza no nombra el libro «{fila['libro_titulo']}»")
    return motivos, avisos


def construir_sistema_criterio(sello: Sello, serie_id: str) -> str:
    serie = sello.series[serie_id]
    return RUTA_PROMPT.read_text(encoding="utf-8").format(
        sello_nombre=sello.nombre, serie_nombre=serie.nombre_amazon, serie_frase=serie.frase,
        nota_enfoque=" ".join(str(serie.datos.get("nota_enfoque", "")).split()),
    )


def revisar_criterio(fila: sqlite3.Row, contenido: dict[str, Any], sello: Sello, ia: ClienteIA) -> tuple[list[str], list[str]] | None:
    if fila["atomo_id"] is None:
        from agentes.redactor.redactar import dossier

        fuente = [f"Formato: {fila['formato']} (institucional). Única fuente admitida, el dossier:", dossier(fila, sello)]
    else:
        fuente = [f"Formato: {fila['formato']}. Libro: «{fila['libro_titulo']}» — {fila['libro_subtitulo']}.",
                  f"Átomo{' LITERAL' if fila['es_literal'] else ''}: «{fila['atomo_texto']}»",
                  f"Pasaje que lo respalda: «{fila['ancla']}»"]
    usuario = "\n".join([
        *fuente,
        "",
        "PIEZA:",
        json.dumps({k: v for k, v in contenido.items() if k not in ("modelo", "formato")}, ensure_ascii=False, indent=1),
    ])
    r = ia.json(construir_sistema_criterio(sello, fila["serie"]), usuario, ESQUEMA_CRITERIO, max_tokens=2000)
    if r is None:
        return None
    return ([] if r["aprobado"] else [f"criterio: {m}" for m in r["motivos"]] or ["criterio: rechazada sin motivo explícito"],
            [f"criterio: {a}" for a in r.get("avisos", [])])


MODOS = ("manual", "mixto", "auto")


def estado_tras_guardian(fila: sqlite3.Row, avisos: list[str], sello: Sello) -> str:
    """Decide si la pieza que pasó el Guardián queda `aprobada` (automático) o `pendiente_humano`."""
    pub = sello.datos.get("publicacion", {})
    modo = pub.get("aprobacion", "manual")
    if modo not in MODOS:
        modo = "manual"
    if pub.get("rechazadas_a_manual", True) and (fila["intentos"] or 0) > 0:
        return "pendiente_humano"          # ya falló una vez: la mira el humano
    if modo == "auto":
        return "aprobada"
    if modo == "mixto" and fila["formato"] == "cita" and fila["es_literal"] and not avisos:
        return "aprobada"
    return "pendiente_humano"


def revisar_pendientes(con: sqlite3.Connection, sello: Sello, ia: ClienteIA | None) -> dict[str, int]:
    r = {"aprobadas": 0, "rechazadas": 0, "automaticas": 0}
    for fila in db.piezas(con, "redactada"):
        contenido = db.contenido_de(fila)
        motivos, avisos = revisar_determinista(fila, contenido, sello)
        if not motivos and ia is not None:
            res = revisar_criterio(fila, contenido, sello, ia)
            if res is not None:
                motivos += res[0]
                avisos += res[1]
        contenido["avisos"] = avisos
        if motivos:
            db.actualizar_pieza(con, fila["id"], estado="rechazada", motivo_rechazo=" | ".join(motivos),
                                intentos=fila["intentos"] + 1, contenido=contenido)
            r["rechazadas"] += 1
            print(f"  ✗ pieza #{fila['id']} rechazada: {motivos[0]}" + (f" (+{len(motivos)-1})" if len(motivos) > 1 else ""))
        else:
            estado = estado_tras_guardian(fila, avisos, sello)
            db.actualizar_pieza(con, fila["id"], estado=estado, contenido=contenido)
            r["aprobadas"] += 1
            if estado == "aprobada":
                r["automaticas"] += 1
            destino = "aprobada automáticamente (cancelable en Telegram)" if estado == "aprobada" else "pasa al humano"
            print(f"  ✓ pieza #{fila['id']} {destino}" + (f" · {len(avisos)} avisos" if avisos else ""))
    return r
