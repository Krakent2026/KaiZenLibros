"""Publicador: conectores por canal. Solo publica piezas `aprobada` cuya hora ha llegado.

Cada conector implementa `disponible()` (hay credenciales) y `publicar(...)`. Ninguno usa modelo
de lenguaje. Los fallos se registran y la pieza se reintenta en la siguiente corrida.
"""
from __future__ import annotations

from agentes.publicador.base import Publicador, Resultado, NoDisponible  # noqa: F401
