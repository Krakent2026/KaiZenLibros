"""X (capa gratuita, solo escritura). Variables: X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET.
Publica texto con enlace. La subida de imágenes en la capa gratuita cambia de condiciones con frecuencia;
se deja para cuando se verifique. Cupo mensual reducido: el Guardián de cupos (Fase 3) lo vigilará."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

import requests

from agentes.config import Sello
from agentes.enlaces import enlace_pieza
from agentes.publicador.base import Publicador, Resultado

API = "https://api.x.com/2/tweets"


class PublicadorX(Publicador):
    nombre = "x"

    def __init__(self) -> None:
        self.claves = {k: os.environ.get(k, "") for k in ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET")}

    def disponible(self) -> bool:
        return all(self.claves.values())

    def publicar(self, fila: sqlite3.Row, contenido: dict[str, Any], activos: list[Path], sello: Sello) -> Resultado:
        from requests_oauthlib import OAuth1

        auth = OAuth1(self.claves["X_API_KEY"], self.claves["X_API_SECRET"], self.claves["X_ACCESS_TOKEN"], self.claves["X_ACCESS_SECRET"])
        cuerpo = (contenido.get("x") or contenido.get("bluesky") or "").strip()[:250]
        texto = f"{cuerpo}\n{enlace_pieza(sello, fila, 'x')}"
        r = requests.post(API, json={"text": texto}, auth=auth, timeout=30)
        if r.status_code >= 400:
            raise RuntimeError(f"X {r.status_code}: {r.text[:300]}")
        tid = r.json().get("data", {}).get("id")
        return Resultado(tid, f"https://x.com/i/status/{tid}" if tid else None)
