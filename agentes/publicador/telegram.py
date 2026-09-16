"""Canal público de Telegram. Variables: TELEGRAM_BOT_TOKEN, TELEGRAM_CANAL (@nombre o id). El bot debe ser administrador del canal."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

from agentes.aprobacion.telegram import Telegram
from agentes.config import Sello
from agentes.enlaces import enlace_compra
from agentes.publicador.base import Publicador, Resultado


class PublicadorTelegram(Publicador):
    nombre = "telegram"

    def __init__(self) -> None:
        self.tg = Telegram()
        self.canal = os.environ.get("TELEGRAM_CANAL", "")

    def disponible(self) -> bool:
        return self.tg.disponible and bool(self.canal)

    def publicar(self, fila: sqlite3.Row, contenido: dict[str, Any], activos: list[Path], sello: Sello) -> Resultado:
        firma = sello.datos.get("telegram", {}).get("firma_canal", "")
        enlace = enlace_compra(sello, fila["libro_slug"], "tg")
        texto = f"{contenido.get('telegram', '').strip()}\n\n{enlace}\n{firma}".strip()
        fotos = [a for a in activos if a.name != "pin.jpg"] or activos
        res = self.tg.enviar_fotos(self.canal, fotos, texto[:1024])
        primero = res[0] if isinstance(res, list) else res
        mid = primero.get("message_id")
        url = None
        if self.canal.startswith("@") and mid:
            url = f"https://t.me/{self.canal[1:]}/{mid}"
        return Resultado(str(mid) if mid else None, url)
