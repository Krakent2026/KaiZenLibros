"""Threads API (Meta). Variable: THREADS_TOKEN (token de larga duración del usuario).
Como Instagram, las imágenes van por URL pública (web del sello). Texto máximo 500 caracteres."""
from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from typing import Any

import requests

from agentes.config import Sello
from agentes.enlaces import enlace_pieza, url_pieza
from agentes.publicador.base import NoDisponible, Publicador, Resultado

API = "https://graph.threads.net/v1.0"


class PublicadorThreads(Publicador):
    nombre = "threads"

    def __init__(self) -> None:
        self.token = os.environ.get("THREADS_TOKEN", "")

    def disponible(self) -> bool:
        return bool(self.token)

    def _post(self, ruta: str, datos: dict[str, Any]) -> dict[str, Any]:
        r = requests.post(f"{API}/{ruta}", data={**datos, "access_token": self.token}, timeout=60)
        cuerpo = r.json()
        if r.status_code >= 400 or "error" in cuerpo:
            raise RuntimeError(f"Threads {ruta}: {cuerpo.get('error', cuerpo)}")
        return cuerpo

    def publicar(self, fila: sqlite3.Row, contenido: dict[str, Any], activos: list[Path], sello: Sello) -> Resultado:
        imagenes = [a for a in activos if a.name != "pin.jpg"][:10] or activos[:1]
        urls = [url_pieza(sello, fila["id"], a.name) for a in imagenes]
        for u in urls:
            try:
                ok = requests.head(u, timeout=20, allow_redirects=True).status_code == 200
            except requests.RequestException:
                ok = False
            if not ok:
                raise NoDisponible(f"imagen aún no pública: {u}")
        texto = f"{(contenido.get('threads') or contenido.get('telegram', '')).strip()}\n\n{enlace_pieza(sello, fila, 'th')}"[:500]
        if len(urls) == 1:
            cid = self._post("me/threads", {"media_type": "IMAGE", "image_url": urls[0], "text": texto, "alt_text": contenido.get("alt_texto", "")[:1000]})["id"]
        else:
            hijos = [self._post("me/threads", {"media_type": "IMAGE", "image_url": u, "is_carousel_item": "true"})["id"] for u in urls]
            time.sleep(2)
            cid = self._post("me/threads", {"media_type": "CAROUSEL", "children": ",".join(hijos), "text": texto})["id"]
        time.sleep(3)
        mid = self._post("me/threads_publish", {"creation_id": cid})["id"]
        r = requests.get(f"{API}/{mid}", params={"fields": "permalink", "access_token": self.token}, timeout=30).json()
        return Resultado(str(mid), r.get("permalink"))
