"""Pinterest API v5. Variables: PINTEREST_TOKEN (access token), PINTEREST_TABLERO_ID.

Se envía la imagen en base64 (no necesita URL pública). El pin enlaza al libro con canal `pin`.
Documentación: https://developers.pinterest.com/docs/api/v5/pins-create
"""
from __future__ import annotations

import base64
import os
import sqlite3
from pathlib import Path
from typing import Any

import requests

from agentes.config import Sello
from agentes.enlaces import enlace_compra
from agentes.publicador.base import Publicador, Resultado

API = "https://api.pinterest.com/v5"


class PublicadorPinterest(Publicador):
    nombre = "pinterest"

    def __init__(self) -> None:
        self.token = os.environ.get("PINTEREST_TOKEN", "")
        self.tablero = os.environ.get("PINTEREST_TABLERO_ID", "")
        self._renovado = False

    def _renovar(self) -> None:
        """El access token caduca a los 30 días; con app id, secreto y refresh token se pide uno nuevo en cada corrida."""
        app, secreto, refresh = (os.environ.get(k, "") for k in ("PINTEREST_APP_ID", "PINTEREST_APP_SECRET", "PINTEREST_REFRESH_TOKEN"))
        if self._renovado or not (app and secreto and refresh):
            return
        import base64

        r = requests.post(f"{API}/oauth/token",
                          headers={"Authorization": "Basic " + base64.b64encode(f"{app}:{secreto}".encode()).decode()},
                          data={"grant_type": "refresh_token", "refresh_token": refresh}, timeout=30)
        if r.ok and r.json().get("access_token"):
            self.token = r.json()["access_token"]
        self._renovado = True

    def disponible(self) -> bool:
        self._renovar()
        return bool(self.token and self.tablero)

    def publicar(self, fila: sqlite3.Row, contenido: dict[str, Any], activos: list[Path], sello: Sello) -> Resultado:
        imagen = next((a for a in activos if a.name == "pin.jpg"), activos[0])
        pin = contenido.get("pin", {})
        cuerpo = {
            "board_id": self.tablero,
            "title": (pin.get("titulo") or fila["libro_titulo"])[:100],
            "description": pin.get("descripcion", "")[:800],
            "alt_text": contenido.get("alt_texto", "")[:500],
            "link": enlace_compra(sello, fila["libro_slug"], "pin"),
            "media_source": {
                "source_type": "image_base64",
                "content_type": "image/jpeg",
                "data": base64.b64encode(imagen.read_bytes()).decode("ascii"),
            },
        }
        r = requests.post(f"{API}/pins", json=cuerpo, headers={"Authorization": f"Bearer {self.token}"}, timeout=60)
        if r.status_code >= 400:
            raise RuntimeError(f"Pinterest {r.status_code}: {r.text[:300]}")
        datos = r.json()
        pid = datos.get("id")
        return Resultado(pid, f"https://www.pinterest.com/pin/{pid}/" if pid else None)
