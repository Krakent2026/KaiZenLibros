"""Instagram API con inicio de sesión de Instagram (cuentas profesionales).
Variables: INSTAGRAM_TOKEN (token de larga duración), INSTAGRAM_CUENTA_ID.

Instagram solo acepta imágenes por URL pública y en JPEG. Las imágenes de la pieza viven en la web
del sello (web/static/piezas/<id>/). Si aún no responden (la web no se ha desplegado), se lanza
NoDisponible y la pieza se reintenta en la siguiente corrida.
Documentación: https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/content-publishing
"""
from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from typing import Any

import requests

from agentes.config import Sello
from agentes.enlaces import url_pieza
from agentes.publicador.base import NoDisponible, Publicador, Resultado, caption_instagram

API = "https://graph.instagram.com/v23.0"


class PublicadorInstagram(Publicador):
    nombre = "instagram"

    def __init__(self) -> None:
        self.token = os.environ.get("INSTAGRAM_TOKEN", "")
        self.cuenta = os.environ.get("INSTAGRAM_CUENTA_ID", "")

    def disponible(self) -> bool:
        return bool(self.token and self.cuenta)

    def _post(self, ruta: str, datos: dict[str, Any]) -> dict[str, Any]:
        r = requests.post(f"{API}/{ruta}", data={**datos, "access_token": self.token}, timeout=60)
        cuerpo = r.json()
        if r.status_code >= 400 or "error" in cuerpo:
            raise RuntimeError(f"Instagram {ruta}: {cuerpo.get('error', cuerpo)}")
        return cuerpo

    def _get(self, ruta: str, campos: str) -> dict[str, Any]:
        r = requests.get(f"{API}/{ruta}", params={"fields": campos, "access_token": self.token}, timeout=60)
        return r.json()

    def _esperar_contenedor(self, cid: str, intentos: int = 10) -> None:
        for _ in range(intentos):
            est = self._get(cid, "status_code,status").get("status_code")
            if est == "FINISHED":
                return
            if est == "ERROR":
                raise RuntimeError(f"Instagram: el contenedor {cid} dio error")
            time.sleep(3)
        raise NoDisponible("Instagram: el contenedor sigue en proceso; se reintenta después")

    def publicar(self, fila: sqlite3.Row, contenido: dict[str, Any], activos: list[Path], sello: Sello) -> Resultado:
        imagenes = [a for a in activos if a.name != "pin.jpg"] or activos
        urls = [url_pieza(sello, fila["id"], a.name) for a in imagenes]
        for u in urls:
            try:
                ok = requests.head(u, timeout=20, allow_redirects=True).status_code == 200
            except requests.RequestException:
                ok = False
            if not ok:
                raise NoDisponible(f"imagen aún no pública: {u}")

        caption = caption_instagram(contenido)
        alt = contenido.get("alt_texto", "")[:1000]
        if len(urls) == 1:
            contenedor = self._post(f"{self.cuenta}/media", {"image_url": urls[0], "caption": caption, "alt_text": alt})["id"]
        else:
            hijos = []
            for u in urls[:10]:
                hijos.append(self._post(f"{self.cuenta}/media", {"image_url": u, "is_carousel_item": "true", "alt_text": alt})["id"])
                time.sleep(1)
            for h in hijos:
                self._esperar_contenedor(h)
            contenedor = self._post(f"{self.cuenta}/media", {"media_type": "CAROUSEL", "children": ",".join(hijos), "caption": caption})["id"]
        self._esperar_contenedor(contenedor)
        media_id = self._post(f"{self.cuenta}/media_publish", {"creation_id": contenedor})["id"]
        permalink = self._get(media_id, "permalink").get("permalink")
        return Resultado(str(media_id), permalink)
