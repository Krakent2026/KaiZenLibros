"""Canal «podcast»: el episodio ya está sintetizado y publicado con la web; aquí solo se comprueba
que existe el MP3. El feed se regenera al final de cada corrida de publicación (publicar.py)."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from agentes.config import RAIZ_REPO, Sello
from agentes.locutor.sintetizar import url_podcast
from agentes.publicador.base import Publicador, Resultado


class PublicadorPodcast(Publicador):
    nombre = "podcast"

    def disponible(self) -> bool:
        return True

    def publicar(self, fila: sqlite3.Row, contenido: dict[str, Any], activos: list[Path], sello: Sello) -> Resultado:
        if not fila["ruta_audio"] or not (RAIZ_REPO / fila["ruta_audio"]).exists():
            raise RuntimeError("la pieza no tiene MP3; el Locutor no llegó a sintetizarla")
        return Resultado(f"kaizen-podcast-{fila['id']}", url_podcast(sello, "feed.xml"))
