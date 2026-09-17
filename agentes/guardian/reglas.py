"""Vocabulario vetado. Lee config/prohibido_<idioma>.txt y evalúa textos.

Uso:
    from agentes.guardian.reglas import revisar, bloquea
    hallazgos = revisar("Este libro cura la ansiedad")
    if bloquea(hallazgos): ...
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from agentes.config import DIR_CONFIG

NIVELES = ("bloquea", "avisa")


@dataclass(frozen=True)
class Regla:
    nivel: str
    patron: re.Pattern[str]
    nota: str
    origen: str


@dataclass(frozen=True)
class Hallazgo:
    nivel: str
    coincidencia: str
    nota: str
    inicio: int
    fin: int

    def __str__(self) -> str:
        return f"[{self.nivel}] «{self.coincidencia}» — {self.nota}"


def _parsear(ruta: Path) -> tuple[Regla, ...]:
    reglas: list[Regla] = []
    for n, linea in enumerate(ruta.read_text(encoding="utf-8").splitlines(), 1):
        linea = linea.strip()
        if not linea or linea.startswith("#"):
            continue
        # nivel = hasta el primer «|»; nota = desde el último «|»; la regex puede contener «|»
        nivel, _, resto = linea.partition("|")
        regex, sep, nota = resto.rpartition("|")
        if not sep or nivel not in NIVELES or not regex:
            raise ValueError(f"{ruta.name}:{n}: formato inválido, se espera nivel|regex|nota")
        reglas.append(Regla(nivel, re.compile(regex, re.IGNORECASE | re.UNICODE), nota, f"{ruta.name}:{n}"))
    return tuple(reglas)


@lru_cache(maxsize=4)
def cargar_reglas(idioma: str = "es") -> tuple[Regla, ...]:
    ruta = DIR_CONFIG / f"prohibido_{idioma}.txt"
    if not ruta.exists():
        raise FileNotFoundError(ruta)
    return _parsear(ruta)


NEGACIONES = {
    "es": re.compile(r"\b(no|ni|nunca|jamás|nadie|nada|sin|ningún|ninguna|ninguno|tampoco|niega|negamos|rompemos)\b", re.IGNORECASE),
    "en": re.compile(r"\b(no|not|never|nobody|nothing|without|neither|nor|won't|doesn't|don't|isn't|aren't)\b", re.IGNORECASE),
}
_FIN_FRASE = re.compile(r"[.!?;:\n]")


def negado(texto: str, inicio: int, idioma: str = "es", ventana: int = 70) -> bool:
    """¿Hay una negación antes de la coincidencia, dentro de la misma frase?
    «no se predice», «nadie tiene un superpoder», «ni un test» son la voz de la casa, no una promesa."""
    previo = texto[max(0, inicio - ventana):inicio]
    corte = [m.end() for m in _FIN_FRASE.finditer(previo)]
    if corte:
        previo = previo[corte[-1]:]
    patron = NEGACIONES.get(idioma, NEGACIONES["es"])
    return bool(patron.search(previo))


def revisar(texto: str, idioma: str = "es", reglas: tuple[Regla, ...] | None = None) -> list[Hallazgo]:
    reglas = reglas or cargar_reglas(idioma)
    hallazgos: list[Hallazgo] = []
    for r in reglas:
        for m in r.patron.finditer(texto):
            nivel, nota = r.nivel, r.nota
            if nivel == "bloquea" and negado(texto, m.start(), idioma):
                nivel, nota = "avisa", nota + " (en frase negada: lo mira el humano)"
            hallazgos.append(Hallazgo(nivel, m.group(0), nota, m.start(), m.end()))
    hallazgos.sort(key=lambda h: (h.nivel != "bloquea", h.inicio))
    return hallazgos


def bloquea(hallazgos: list[Hallazgo]) -> bool:
    return any(h.nivel == "bloquea" for h in hallazgos)


def informe(hallazgos: list[Hallazgo]) -> str:
    if not hallazgos:
        return "sin hallazgos"
    return "\n".join(str(h) for h in hallazgos)
