"""Carga de la configuración del sello y resolución de rutas.

Un sello = un YAML en config/sellos/. Los manuscritos viven fuera del repositorio;
su raíz se toma de la variable de entorno indicada en el YAML (KAIZEN_FUENTES) o,
si no existe, de la ruta relativa por defecto.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

def consola_utf8() -> None:
    """La consola de Windows arranca en cp1252 y revienta con «→» o «✓». Todas las CLIs llaman a esto."""
    import sys

    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass


RAIZ_REPO = Path(__file__).resolve().parent.parent


def cargar_env(*rutas: Path) -> list[Path]:
    """Carga ficheros CLAVE=valor en os.environ sin pisar variables ya definidas.

    Por defecto lee, en este orden, `<repo>/.env` y `~/.promocion_ia.env` (este segundo queda fuera
    de OneDrive, útil si el repositorio vive en una carpeta sincronizada). Devuelve los que existían.
    """
    rutas = rutas or (RAIZ_REPO / ".env", Path.home() / ".promocion_ia.env")
    cargados: list[Path] = []
    for ruta in rutas:
        if not ruta.is_file():
            continue
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            linea = linea.strip()
            if not linea or linea.startswith("#") or "=" not in linea:
                continue
            clave, _, valor = linea.partition("=")
            clave, valor = clave.strip(), valor.strip().strip('"').strip("'")
            if clave and valor and clave not in os.environ:
                os.environ[clave] = valor
        cargados.append(ruta)
    return cargados


cargar_env()

DIR_CONFIG = RAIZ_REPO / "config"
DIR_DATOS = RAIZ_REPO / "datos"
DB_POR_DEFECTO = DIR_DATOS / "atomos.sqlite"


@dataclass(frozen=True)
class Libro:
    serie_id: str
    numero: int
    slug: str
    titulo: str
    subtitulo: str
    carpeta: str
    portada: str
    bloque: str
    para_que: str
    asin_ebook: str | None
    asin_papel: str | None
    manuscrito: str | None = None  # ruta alternativa (relativa al repo o absoluta) si el libro no tiene 11_Version_Definitiva.md

    @property
    def id(self) -> str:
        return f"{self.serie_id}/{self.slug}"


@dataclass(frozen=True)
class Serie:
    id: str
    activa: bool
    nombre_amazon: str
    carpeta: str
    frase: str
    datos: dict[str, Any]
    libros: tuple[Libro, ...]

    def libro(self, slug_o_numero: str | int) -> Libro:
        for lib in self.libros:
            if lib.slug == slug_o_numero or lib.numero == slug_o_numero:
                return lib
        raise KeyError(f"Libro {slug_o_numero!r} no existe en la serie {self.id}")


class Sello:
    def __init__(self, datos: dict[str, Any], ruta_yaml: Path):
        self.datos = datos
        self.ruta_yaml = ruta_yaml
        self.id: str = datos["sello"]["id"]
        self.nombre: str = datos["sello"]["nombre"]
        self.series: dict[str, Serie] = {
            sid: _construir_serie(sid, s) for sid, s in datos.get("series", {}).items()
        }

    # ---- rutas -------------------------------------------------------------
    @property
    def raiz_fuentes(self) -> Path:
        f = self.datos["fuentes"]
        valor = os.environ.get(f["raiz_env"])
        if valor:
            return Path(valor).expanduser().resolve()
        return (RAIZ_REPO / f["raiz_por_defecto"]).resolve()

    def ruta_manuscrito(self, libro: Libro) -> Path:
        if libro.manuscrito:
            p = Path(libro.manuscrito)
            return p if p.is_absolute() else (RAIZ_REPO / p)
        serie = self.series[libro.serie_id]
        return self.raiz_fuentes / serie.carpeta / libro.carpeta / self.datos["fuentes"]["manuscrito"]

    def ruta_ficha(self, libro: Libro) -> Path:
        serie = self.series[libro.serie_id]
        return self.raiz_fuentes / serie.carpeta / libro.carpeta / self.datos["fuentes"]["ficha"]

    def ruta_portada(self, libro: Libro) -> Path:
        serie = self.series[libro.serie_id]
        return self.raiz_fuentes / serie.carpeta / libro.carpeta / libro.portada

    # ---- accesos cómodos ---------------------------------------------------
    def series_activas(self) -> list[Serie]:
        return [s for s in self.series.values() if s.activa]

    def libros_activos(self) -> list[Libro]:
        return [lib for s in self.series_activas() for lib in s.libros]

    @property
    def ia(self) -> dict[str, Any]:
        return self.datos.get("ia", {})

    def precio(self, modelo: str) -> tuple[float, float]:
        p = self.ia.get("precios", {}).get(modelo)
        if not p:
            return (0.0, 0.0)
        return (float(p["entrada"]), float(p["salida"]))


def _construir_serie(sid: str, s: dict[str, Any]) -> Serie:
    libros = tuple(
        Libro(
            serie_id=sid,
            numero=int(l["numero"]),
            slug=l["slug"],
            titulo=l["titulo"],
            subtitulo=l.get("subtitulo", ""),
            carpeta=l["carpeta"],
            portada=l.get("portada", ""),
            bloque=l.get("bloque", ""),
            para_que=l.get("para_que", ""),
            asin_ebook=l.get("asin_ebook"),
            asin_papel=l.get("asin_papel"),
            manuscrito=l.get("manuscrito"),
        )
        for l in s.get("libros", []) or []
    )
    return Serie(
        id=sid,
        activa=bool(s.get("activa", False)),
        nombre_amazon=s["nombre_amazon"],
        carpeta=s["carpeta"],
        frase=s.get("frase", ""),
        datos=s,
        libros=libros,
    )


def cargar_sello(id_sello: str = "kaizen") -> Sello:
    ruta = DIR_CONFIG / "sellos" / f"{id_sello}.yaml"
    if not ruta.exists():
        raise FileNotFoundError(f"No existe la configuración del sello: {ruta}")
    with ruta.open(encoding="utf-8") as fh:
        datos = yaml.safe_load(fh)
    return Sello(datos, ruta)


def cargar_yaml(nombre: str) -> Any:
    with (DIR_CONFIG / nombre).open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)
