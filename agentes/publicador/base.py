from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentes.config import Sello


@dataclass
class Resultado:
    id_externo: str | None
    url: str | None


class NoDisponible(Exception):
    """El canal no puede publicar ahora (imágenes aún no accesibles, cupo agotado…). Se reintenta después."""


class Publicador:
    nombre = "base"

    def disponible(self) -> bool:  # pragma: no cover
        raise NotImplementedError

    def publicar(self, fila: sqlite3.Row, contenido: dict[str, Any], activos: list[Path], sello: Sello) -> Resultado:  # pragma: no cover
        raise NotImplementedError


def caption_instagram(contenido: dict[str, Any]) -> str:
    hashtags = " ".join(f"#{h}" for h in contenido.get("hashtags", []))
    return (contenido.get("caption_instagram", "").strip() + ("\n\n" + hashtags if hashtags else ""))[:2200]
