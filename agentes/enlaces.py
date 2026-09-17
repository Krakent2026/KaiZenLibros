"""Enlaces de compra y URLs públicas de las piezas. Misma lógica que la web."""
from __future__ import annotations

from agentes.config import Sello


def web_base(sello: Sello) -> str:
    return sello.datos["sello"].get("web", "").rstrip("/")


def enlace_compra(sello: Sello, libro_slug: str, canal: str) -> str:
    """Enlace universal (Worker) si está configurado; si no, la redirección estática de la web."""
    base = (sello.datos.get("enlaces", {}) or {}).get("base_url", "").rstrip("/")
    if base:
        return f"{base}/{libro_slug}?c={canal}"
    return f"{web_base(sello)}/ir/{libro_slug}/?c={canal}"


def enlace_pieza(sello: Sello, fila, canal: str) -> str:
    """Destino de una pieza: el libro (enlace de compra) o, si es institucional, la web del sello o de la serie."""
    formato = fila["formato"] if fila is not None else ""
    utm = f"utm_source={canal}&utm_medium=social"
    if formato == "sello":
        return f"{web_base(sello)}/enlaces/?{utm}&utm_campaign=sello"
    if formato == "serie":
        return f"{web_base(sello)}/series/{fila['serie'].replace('_', '-')}/?{utm}&utm_campaign=serie"
    return enlace_compra(sello, fila["libro_slug"], canal)


def url_pieza(sello: Sello, id_pieza: int, fichero: str) -> str:
    ruta = sello.datos.get("publicacion", {}).get("ruta_piezas_web", "static/piezas").strip("/")
    return f"{web_base(sello)}/{ruta}/{id_pieza}/{fichero}"
