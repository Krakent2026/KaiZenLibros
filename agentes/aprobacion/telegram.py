"""Cola de aprobación en Telegram, sin servidor: cada corrida envía las previas nuevas y
recoge las respuestas acumuladas (getUpdates) desde la última vez.

Botones por pieza:  ✅ Aprobar · ✏️ Editar (se pide una nota y vuelve al Redactor) · ❌ Descartar
Solo se atienden mensajes del chat de aprobación (TELEGRAM_CHAT_APROBACION).

Variables de entorno: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_APROBACION.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

import requests

from agentes import db
from agentes.config import RAIZ_REPO, Sello

API = "https://api.telegram.org/bot{token}/{metodo}"


class Telegram:
    def __init__(self, token: str | None = None):
        self.token = token or os.environ.get("TELEGRAM_BOT_TOKEN", "")

    @property
    def disponible(self) -> bool:
        return bool(self.token)

    def llamar(self, metodo: str, datos: dict[str, Any] | None = None, ficheros: dict[str, Any] | None = None) -> dict[str, Any]:
        r = requests.post(API.format(token=self.token, metodo=metodo), data=datos, files=ficheros, timeout=60)
        cuerpo = r.json()
        if not cuerpo.get("ok"):
            raise RuntimeError(f"Telegram {metodo}: {cuerpo.get('description', r.text)}")
        return cuerpo["result"]

    # ---- envíos --------------------------------------------------------------------
    def enviar_fotos(self, chat: str, rutas: list[Path], pie: str = "") -> list[dict[str, Any]]:
        """sendMediaGroup (hasta 10). El pie va en la primera foto (máx. 1024 caracteres)."""
        rutas = rutas[:10]
        if len(rutas) == 1:
            with rutas[0].open("rb") as fh:
                return [self.llamar("sendPhoto", {"chat_id": chat, "caption": pie[:1024]}, {"photo": fh})]
        media = []
        ficheros = {}
        manejadores = []
        try:
            for i, ruta in enumerate(rutas):
                fh = ruta.open("rb")
                manejadores.append(fh)
                ficheros[f"f{i}"] = fh
                item: dict[str, Any] = {"type": "photo", "media": f"attach://f{i}"}
                if i == 0 and pie:
                    item["caption"] = pie[:1024]
                media.append(item)
            return self.llamar("sendMediaGroup", {"chat_id": chat, "media": json.dumps(media)}, ficheros)
        finally:
            for fh in manejadores:
                fh.close()

    def enviar_texto(self, chat: str, texto: str, teclado: list[list[dict[str, str]]] | None = None) -> dict[str, Any]:
        datos: dict[str, Any] = {"chat_id": chat, "text": texto[:4096], "disable_web_page_preview": "true"}
        if teclado:
            datos["reply_markup"] = json.dumps({"inline_keyboard": teclado})
        return self.llamar("sendMessage", datos)

    def quitar_botones(self, chat: str, mensaje_id: int, texto_extra: str = "") -> None:
        try:
            self.llamar("editMessageReplyMarkup", {"chat_id": chat, "message_id": mensaje_id, "reply_markup": json.dumps({"inline_keyboard": []})})
            if texto_extra:
                self.llamar("sendMessage", {"chat_id": chat, "text": texto_extra, "reply_to_message_id": mensaje_id})
        except RuntimeError:
            pass

    def actualizaciones(self, desde: int) -> list[dict[str, Any]]:
        return self.llamar("getUpdates", {"offset": desde, "timeout": 0,
                                          "allowed_updates": json.dumps(["callback_query", "message"])})

    def responder_callback(self, id_cb: str, texto: str) -> None:
        try:
            self.llamar("answerCallbackQuery", {"callback_query_id": id_cb, "text": texto[:200]})
        except RuntimeError:
            pass


# ---- previas -----------------------------------------------------------------------
def resumen_pieza(fila: sqlite3.Row, contenido: dict[str, Any]) -> str:
    avisos = contenido.get("avisos", [])
    lineas = [
        f"Pieza #{fila['id']} · {fila['formato']} · L{fila['libro_numero']} {fila['libro_titulo']}",
        f"Programada: {fila['programado_para'] or '—'} · canales: {fila['canal']}",
        "",
        "CAPTION INSTAGRAM:",
        contenido.get("caption_instagram", "")[:900],
        "",
        "#" + " #".join(contenido.get("hashtags", [])),
        "",
        f"PIN: {contenido.get('pin', {}).get('titulo', '')}",
        contenido.get("pin", {}).get("descripcion", "")[:300],
        "",
        "TELEGRAM:",
        contenido.get("telegram", "")[:500],
    ]
    if avisos:
        lineas += ["", "AVISOS DEL GUARDIÁN:"] + [f"• {a}" for a in avisos[:8]]
    return "\n".join(lineas)


def teclado(id_pieza: int) -> list[list[dict[str, str]]]:
    return [[
        {"text": "✅ Aprobar", "callback_data": f"ok:{id_pieza}"},
        {"text": "✏️ Editar", "callback_data": f"ed:{id_pieza}"},
        {"text": "❌ Descartar", "callback_data": f"no:{id_pieza}"},
    ]]


def enviar_previas(con: sqlite3.Connection, sello: Sello, tg: Telegram | None = None) -> int:
    tg = tg or Telegram()
    chat = os.environ.get("TELEGRAM_CHAT_APROBACION", "")
    if not tg.disponible or not chat:
        print("  · Telegram no configurado: las piezas quedan pendientes (aprobar con `pipeline aprobar --id N`)")
        return 0
    n = 0
    for fila in db.piezas(con, "pendiente_humano"):
        if fila["enviado_humano_en"] or not fila["ruta_activos"]:
            continue
        contenido = db.contenido_de(fila)
        rutas = sorted((RAIZ_REPO / fila["ruta_activos"]).glob("*.jpg"))
        try:
            tg.enviar_fotos(chat, rutas, f"Pieza #{fila['id']} · {fila['formato']} · {fila['libro_titulo']}")
            msg = tg.enviar_texto(chat, resumen_pieza(fila, contenido), teclado(fila["id"]))
        except RuntimeError as e:
            print(f"  ! pieza #{fila['id']}: {e}")
            continue
        db.actualizar_pieza(con, fila["id"], telegram_msg_id=msg["message_id"], enviado_humano_en=db.ahora())
        n += 1
        print(f"  → pieza #{fila['id']} enviada a Telegram para aprobación")
    return n


# ---- respuestas --------------------------------------------------------------------
def aplicar_decision(con: sqlite3.Connection, id_pieza: int, decision: str, nota: str | None = None) -> str:
    fila = db.pieza(con, id_pieza)
    if fila is None:
        return "no existe"
    if fila["estado"] not in ("pendiente_humano", "aprobada"):
        return f"ya está en estado {fila['estado']}"
    if decision == "ok":
        db.actualizar_pieza(con, id_pieza, estado="aprobada", nota_humano=None)
        return "aprobada"
    if decision == "no":
        db.actualizar_pieza(con, id_pieza, estado="descartada", nota_humano=nota)
        return "descartada"
    if decision == "ed":
        # vuelve al Redactor con la nota; conserva las imágenes anteriores hasta que se rehagan
        db.actualizar_pieza(con, id_pieza, estado="planificada", nota_humano=nota, ruta_activos=None,
                            telegram_msg_id=None, enviado_humano_en=None)
        return "devuelta al Redactor con tu nota"
    return "orden desconocida"


def procesar_respuestas(con: sqlite3.Connection, sello: Sello, tg: Telegram | None = None) -> dict[str, int]:
    tg = tg or Telegram()
    chat = os.environ.get("TELEGRAM_CHAT_APROBACION", "")
    r = {"aprobadas": 0, "descartadas": 0, "editar": 0, "ignoradas": 0}
    if not tg.disponible or not chat:
        return r
    desde = int(db.kv_get(con, "telegram_offset", "0") or 0)
    try:
        updates = tg.actualizaciones(desde)
    except RuntimeError as e:
        print(f"  ! Telegram getUpdates: {e}")
        return r
    ultimo = desde
    for u in updates:
        ultimo = max(ultimo, u["update_id"] + 1)
        cb = u.get("callback_query")
        msg = u.get("message")
        if cb:
            if str(cb["message"]["chat"]["id"]) != str(chat):
                r["ignoradas"] += 1
                continue
            accion, _, id_txt = (cb.get("data") or "").partition(":")
            if accion not in ("ok", "no", "ed") or not id_txt.isdigit():
                r["ignoradas"] += 1
                continue
            id_pieza = int(id_txt)
            if accion == "ed":
                db.kv_set(con, f"esperando_nota:{chat}", str(id_pieza))
                tg.responder_callback(cb["id"], "Escribe la nota para el Redactor en el chat")
                tg.enviar_texto(chat, f"Pieza #{id_pieza}: escribe qué hay que cambiar (un mensaje).")
                r["editar"] += 1
                continue
            resultado = aplicar_decision(con, id_pieza, accion)
            tg.responder_callback(cb["id"], f"#{id_pieza}: {resultado}")
            tg.quitar_botones(chat, cb["message"]["message_id"], f"#{id_pieza}: {resultado}")
            r["aprobadas" if accion == "ok" else "descartadas"] += 1
        elif msg and str(msg.get("chat", {}).get("id")) == str(chat) and msg.get("text"):
            texto = msg["text"].strip()
            esperando = db.kv_get(con, f"esperando_nota:{chat}")
            if esperando:
                resultado = aplicar_decision(con, int(esperando), "ed", texto)
                db.kv_set(con, f"esperando_nota:{chat}", "")
                tg.enviar_texto(chat, f"#{esperando}: {resultado}")
                r["editar"] += 1
            elif texto.lower().startswith(("ok ", "no ", "ed ")) and texto.split()[1].isdigit():
                accion, id_txt, *resto = texto.split(maxsplit=2)
                resultado = aplicar_decision(con, int(id_txt), accion.lower(), " ".join(resto) or None)
                tg.enviar_texto(chat, f"#{id_txt}: {resultado}")
            else:
                r["ignoradas"] += 1
    db.kv_set(con, "telegram_offset", str(ultimo))
    return r
