"""Bluesky (AT Protocol). Variables: BLUESKY_USUARIO (p. ej. kaizenlibros.bsky.social), BLUESKY_APP_PASSWORD.
Sin revisión ni cupo relevante. Texto máximo 300 grafemas; hasta 4 imágenes de menos de 1 MB."""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from agentes.config import Sello
from agentes.enlaces import enlace_compra
from agentes.publicador.base import Publicador, Resultado

PDS = "https://bsky.social/xrpc"
LIMITE = 300


def componer_texto(cuerpo: str, enlace: str, limite: int = LIMITE) -> tuple[str, list[dict[str, Any]]]:
    """Recorta el cuerpo para que quepa con el enlace y devuelve (texto, facets) con el enlace clicable."""
    cuerpo = cuerpo.strip()
    maximo = limite - len(enlace) - 2
    if len(cuerpo) > maximo:
        cuerpo = cuerpo[: maximo - 1].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    texto = f"{cuerpo}\n\n{enlace}"
    inicio = len(texto[: texto.rfind(enlace)].encode("utf-8"))
    facets = [{"index": {"byteStart": inicio, "byteEnd": inicio + len(enlace.encode("utf-8"))},
               "features": [{"$type": "app.bsky.richtext.facet#link", "uri": enlace}]}]
    return texto, facets


class PublicadorBluesky(Publicador):
    nombre = "bluesky"

    def __init__(self) -> None:
        self.usuario = os.environ.get("BLUESKY_USUARIO", "")
        self.clave = os.environ.get("BLUESKY_APP_PASSWORD", "")

    def disponible(self) -> bool:
        return bool(self.usuario and self.clave)

    def _sesion(self) -> dict[str, Any]:
        r = requests.post(f"{PDS}/com.atproto.server.createSession",
                          json={"identifier": self.usuario, "password": self.clave}, timeout=30)
        if not r.ok:
            raise RuntimeError(f"Bluesky login: {r.status_code} {r.text[:200]}")
        return r.json()

    def publicar(self, fila: sqlite3.Row, contenido: dict[str, Any], activos: list[Path], sello: Sello) -> Resultado:
        ses = self._sesion()
        cab = {"Authorization": f"Bearer {ses['accessJwt']}"}
        imagenes = [a for a in activos if a.name != "pin.jpg"][:4] or activos[:1]
        blobs = []
        for img in imagenes:
            datos = img.read_bytes()
            if len(datos) > 950_000:
                continue
            r = requests.post(f"{PDS}/com.atproto.repo.uploadBlob", headers={**cab, "Content-Type": "image/jpeg"}, data=datos, timeout=60)
            if not r.ok:
                raise RuntimeError(f"Bluesky uploadBlob: {r.status_code} {r.text[:200]}")
            blobs.append(r.json()["blob"])
        texto, facets = componer_texto(contenido.get("bluesky") or contenido.get("telegram", ""), enlace_compra(sello, fila["libro_slug"], "bs"))
        registro: dict[str, Any] = {
            "$type": "app.bsky.feed.post", "text": texto, "facets": facets, "langs": ["es"],
            "createdAt": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        }
        if blobs:
            alt = contenido.get("alt_texto", "")[:1000]
            registro["embed"] = {"$type": "app.bsky.embed.images", "images": [{"alt": alt, "image": b} for b in blobs]}
        r = requests.post(f"{PDS}/com.atproto.repo.createRecord", headers=cab,
                          json={"repo": ses["did"], "collection": "app.bsky.feed.post", "record": registro}, timeout=30)
        if not r.ok:
            raise RuntimeError(f"Bluesky createRecord: {r.status_code} {r.text[:200]}")
        uri = r.json().get("uri", "")
        rkey = uri.rsplit("/", 1)[-1]
        return Resultado(uri, f"https://bsky.app/profile/{ses.get('handle', self.usuario)}/post/{rkey}" if rkey else None)
