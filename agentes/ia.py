"""Cliente compartido de la API de Claude para los agentes creativos.

Una sola forma de llamar: sistema + usuario → JSON validado contra un esquema, con registro
de tokens y coste. Los modelos y el esfuerzo salen del YAML del sello (sección `ia`).
"""
from __future__ import annotations

import json
import sys
from typing import Any

from agentes.config import Sello


class ClienteIA:
    def __init__(self, sello: Sello, modelo: str, esfuerzo: str | None = "medium"):
        import anthropic

        self.anthropic = anthropic
        self.client = anthropic.Anthropic(max_retries=5)
        self.sello = sello
        self.modelo = modelo
        self.esfuerzo = esfuerzo
        self.tokens = {"entrada": 0, "salida": 0, "cache_lectura": 0, "cache_escritura": 0}
        self.llamadas = 0

    # ---- coste ---------------------------------------------------------------
    def coste_usd(self) -> float:
        pe, ps = self.sello.precio(self.modelo)
        t = self.tokens
        return (t["entrada"] * pe + t["cache_escritura"] * pe * 1.25 + t["cache_lectura"] * pe * 0.1
                + t["salida"] * ps) / 1_000_000

    def resumen(self) -> str:
        t = self.tokens
        return (f"{self.modelo}: {self.llamadas} llamadas · {t['entrada']:,} entrada · {t['salida']:,} salida · "
                f"{t['cache_lectura']:,} caché → {self.coste_usd():.3f} USD")

    # ---- llamada JSON ----------------------------------------------------------
    def json(self, sistema: str, usuario: str, esquema: dict[str, Any], *, max_tokens: int = 8000) -> dict | None:
        kwargs: dict[str, Any] = dict(
            model=self.modelo,
            max_tokens=max_tokens,
            system=[{"type": "text", "text": sistema, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": usuario}],
            output_config={"format": {"type": "json_schema", "schema": esquema}},
        )
        if self.esfuerzo and "haiku" not in self.modelo:
            kwargs["output_config"]["effort"] = self.esfuerzo
        try:
            resp = self.client.messages.create(**kwargs)
        except self.anthropic.RateLimitError as e:
            print(f"    ! límite de peticiones: {e.message}", file=sys.stderr)
            return None
        except self.anthropic.APIStatusError as e:
            print(f"    ! error de API {e.status_code}: {e.message}", file=sys.stderr)
            return None
        except self.anthropic.APIConnectionError as e:
            print(f"    ! error de red: {e}", file=sys.stderr)
            return None

        self.llamadas += 1
        u = resp.usage
        self.tokens["entrada"] += u.input_tokens
        self.tokens["salida"] += u.output_tokens
        self.tokens["cache_lectura"] += getattr(u, "cache_read_input_tokens", 0) or 0
        self.tokens["cache_escritura"] += getattr(u, "cache_creation_input_tokens", 0) or 0

        if resp.stop_reason == "refusal":
            det = getattr(resp, "stop_details", None)
            print(f"    ! el modelo declinó ({getattr(det, 'category', '?')})", file=sys.stderr)
            return None
        if resp.stop_reason == "max_tokens":
            print("    ! salida truncada por max_tokens", file=sys.stderr)
            return None
        texto = next((b.text for b in resp.content if b.type == "text"), "")
        try:
            return json.loads(texto)
        except json.JSONDecodeError:
            print("    ! JSON inválido en la respuesta", file=sys.stderr)
            return None


def cliente_para(sello: Sello, agente: str) -> ClienteIA:
    """Crea el cliente con el modelo del YAML: ia.modelo_<agente> y ia.esfuerzo_<agente>."""
    modelo = sello.ia.get(f"modelo_{agente}", "claude-sonnet-5")
    esfuerzo = sello.ia.get(f"esfuerzo_{agente}", "medium")
    return ClienteIA(sello, modelo, esfuerzo)
