"""Localiza fragmentos en un manuscrito de forma tolerante.

Una cita «literal» propuesta por el modelo puede diferir del original en comillas
tipográficas, guiones, espacios múltiples, saltos de línea o marcas Markdown.
Normalizamos ambos lados conservando un mapa de posiciones para devolver el
offset real en el texto original, que es lo que se guarda como huella.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass

_EQUIVALENTES = {
    "«": '"', "»": '"', "“": '"', "”": '"', "„": '"',
    "‘": "'", "’": "'", "‚": "'", "´": "'", "`": "'",
    "—": "-", "–": "-", "‑": "-", "−": "-",
    "…": "...",
    " ": " ", " ": " ", " ": " ",
}
_MARCAS_MD = re.compile(r"[*_#>`~]+")


@dataclass(frozen=True)
class Localizacion:
    inicio: int
    fin: int
    fragmento: str
    hash: str


def _normalizar_caracter(c: str) -> str:
    c = _EQUIVALENTES.get(c, c)
    c = unicodedata.normalize("NFC", c)
    return c.lower()


def normalizar_con_mapa(texto: str) -> tuple[str, list[int]]:
    """Devuelve (texto_normalizado, mapa) con mapa[i] = índice en `texto` del carácter i normalizado.

    Normalización: equivalencias tipográficas, minúsculas, marcas Markdown fuera,
    cualquier secuencia de espacios/saltos → un espacio.
    """
    salida: list[str] = []
    mapa: list[int] = []
    espacio_pendiente = False
    for i, c in enumerate(texto):
        if c in "*_#>`~":
            continue
        n = _normalizar_caracter(c)
        if n.isspace():
            espacio_pendiente = True
            continue
        if espacio_pendiente and salida:
            salida.append(" ")
            mapa.append(i)  # el espacio apunta al primer carácter no-espacio siguiente
        espacio_pendiente = False
        for k, ch in enumerate(n):  # "…" se expande a "..."
            salida.append(ch)
            mapa.append(i)
    return "".join(salida), mapa


def normalizar(texto: str) -> str:
    return normalizar_con_mapa(texto)[0]


def _recortar_puntuacion(s: str) -> str:
    return s.strip(" \"'.,;:!?¡¿()[]-")


def localizar(fragmento: str, texto: str, *, norm_cache: tuple[str, list[int]] | None = None,
              minimo: int = 12) -> Localizacion | None:
    """Busca `fragmento` en `texto`. Si no aparece entero, prueba con el fragmento sin puntuación
    en los extremos. Devuelve offsets reales y hash SHA-1 del trozo original, o None."""
    if not fragmento or len(fragmento.strip()) < minimo:
        return None
    ntexto, mapa = norm_cache if norm_cache else normalizar_con_mapa(texto)
    for candidato in (fragmento, _recortar_puntuacion(fragmento)):
        nfrag = normalizar(candidato).strip()
        if len(nfrag) < minimo:
            continue
        pos = ntexto.find(nfrag)
        if pos < 0:
            continue
        ini = mapa[pos]
        fin = mapa[pos + len(nfrag) - 1] + 1
        original = texto[ini:fin]
        h = hashlib.sha1(original.encode("utf-8")).hexdigest()[:16]
        return Localizacion(ini, fin, original, h)
    return None


def hash_texto(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:24]
