"""Minero: convierte manuscritos en átomos de contenido verificados.

Uso (desde la raíz del repositorio):
    python -m agentes.minero.extraer --serie mente_distinta                # todos los libros activos de la serie
    python -m agentes.minero.extraer --serie mente_distinta --libro no-es-pereza --max-tramos 3
    python -m agentes.minero.extraer --serie mente_distinta --estimar      # coste aproximado, sin llamar a la API
    python -m agentes.minero.extraer --serie mente_distinta --sin-ia       # heurísticas locales, sin modelo
    python -m agentes.minero.extraer --listar --serie mente_distinta       # muestra átomos guardados

Los manuscritos se leen de la raíz de fuentes (variable KAIZEN_FUENTES); nunca se copian al repositorio.
Cada átomo se verifica contra el manuscrito antes de guardarse: el ancla (y la cita, si es literal)
tiene que existir tal cual. Lo que no se encuentra se guarda como no verificado, con el motivo.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentes import db
from agentes.config import DB_POR_DEFECTO, RAIZ_REPO, Libro, Sello, Serie, cargar_sello, consola_utf8
from agentes.guardian.reglas import bloquea, informe, revisar
from agentes.guardian.verificar_citas import hash_texto, localizar, normalizar_con_mapa

TIPOS = ("cita", "microleccion", "pregunta", "contraste", "herramienta", "escena", "dato_honesto")
FORMATOS = ("cita", "carrusel", "reel", "pin", "hilo", "articulo", "audio")

ESQUEMA_SALIDA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "atomos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "tipo": {"type": "string", "enum": list(TIPOS)},
                    "texto": {"type": "string"},
                    "es_literal": {"type": "boolean"},
                    "ancla": {"type": "string"},
                    "temas": {"type": "array", "items": {"type": "string"}},
                    "intensidad": {"type": "integer"},
                    "gancho": {"type": "string"},
                    "formatos": {"type": "array", "items": {"type": "string", "enum": list(FORMATOS)}},
                },
                "required": ["tipo", "texto", "es_literal", "ancla", "temas", "intensidad", "gancho", "formatos"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["atomos"],
    "additionalProperties": False,
}

RUTA_PROMPT = Path(__file__).with_name("prompt.md")


# ---------------------------------------------------------------------------
# Troceado del manuscrito
# ---------------------------------------------------------------------------
@dataclass
class Tramo:
    titulo: str
    texto: str
    inicio: int  # offset en el manuscrito completo

    @property
    def palabras(self) -> int:
        return len(self.texto.split())


_RE_ENCABEZADO = re.compile(r"^(#{1,3}) +(.+?)\s*$", re.MULTILINE)


def trocear(texto: str, *, max_palabras: int = 4500, min_palabras: int = 250) -> list[Tramo]:
    """Parte por encabezados de nivel 1-2; los tramos enormes se subdividen por nivel 3;
    los diminutos se funden con el siguiente."""
    cortes = [(m.start(), len(m.group(1)), m.group(2)) for m in _RE_ENCABEZADO.finditer(texto)]
    principales = [c for c in cortes if c[1] <= 2]
    if not principales:
        return [Tramo("Texto", texto, 0)]
    if principales[0][0] > 0:
        principales.insert(0, (0, 1, "Inicio"))
    brutos: list[Tramo] = []
    for i, (pos, _nivel, titulo) in enumerate(principales):
        fin = principales[i + 1][0] if i + 1 < len(principales) else len(texto)
        brutos.append(Tramo(titulo, texto[pos:fin], pos))

    # subdividir los muy largos por h3
    medios: list[Tramo] = []
    for t in brutos:
        if t.palabras <= max_palabras:
            medios.append(t)
            continue
        sub = [(m.start(), m.group(2)) for m in _RE_ENCABEZADO.finditer(t.texto) if len(m.group(1)) == 3]
        if not sub:
            medios.append(t)
            continue
        if sub[0][0] > 0:
            sub.insert(0, (0, t.titulo))
        for j, (p, tit) in enumerate(sub):
            f = sub[j + 1][0] if j + 1 < len(sub) else len(t.texto)
            medios.append(Tramo(f"{t.titulo} · {tit}", t.texto[p:f], t.inicio + p))

    # fundir los cortos con el siguiente
    salida: list[Tramo] = []
    acumulado: Tramo | None = None
    for t in medios:
        if acumulado is None:
            acumulado = t
        else:
            acumulado = Tramo(acumulado.titulo, acumulado.texto + t.texto, acumulado.inicio)
        if acumulado.palabras >= min_palabras:
            salida.append(acumulado)
            acumulado = None
    if acumulado is not None:
        if salida:
            u = salida[-1]
            salida[-1] = Tramo(u.titulo, u.texto + acumulado.texto, u.inicio)
        else:
            salida.append(acumulado)
    return salida


# ---------------------------------------------------------------------------
# Verificación
# ---------------------------------------------------------------------------
def verificar_atomo(a: dict[str, Any], tramo: Tramo, manuscrito: str,
                    cache_tramo: tuple[str, list[int]], cache_libro: tuple[str, list[int]],
                    idioma: str) -> dict[str, Any]:
    """Comprueba ancla, cita literal y vocabulario. Devuelve el átomo con los campos de verificación."""
    motivos: list[str] = []
    loc = localizar(a["ancla"], tramo.texto, norm_cache=cache_tramo)
    inicio = fin = None
    hash_frag = None
    if loc:
        inicio, fin, hash_frag = tramo.inicio + loc.inicio, tramo.inicio + loc.fin, loc.hash
    else:
        loc2 = localizar(a["ancla"], manuscrito, norm_cache=cache_libro)
        if loc2:
            inicio, fin, hash_frag = loc2.inicio, loc2.fin, loc2.hash
        else:
            motivos.append("ancla no encontrada en el manuscrito")

    if a["es_literal"]:
        if not localizar(a["texto"], manuscrito, norm_cache=cache_libro):
            motivos.append("cita marcada como literal que no aparece en el manuscrito")

    hallazgos = revisar(f"{a['texto']}\n{a.get('gancho', '')}", idioma)
    if bloquea(hallazgos):
        motivos.append("vocabulario vetado: " + "; ".join(str(h) for h in hallazgos if h.nivel == "bloquea"))

    intensidad = a.get("intensidad")
    if not isinstance(intensidad, int) or not 1 <= intensidad <= 5:
        intensidad = 3
    formatos = [f for f in a.get("formatos", []) if f in FORMATOS] or ["cita"]

    return {
        **a,
        "intensidad": intensidad,
        "formatos": formatos,
        "capitulo": tramo.titulo,
        "inicio": inicio,
        "fin": fin,
        "hash_fragmento": hash_frag,
        "verificado": not motivos,
        "motivo_no_verificado": " | ".join(motivos) if motivos else None,
    }


# ---------------------------------------------------------------------------
# Extracción con modelo
# ---------------------------------------------------------------------------
def construir_sistema(sello: Sello, serie: Serie) -> str:
    plantilla = RUTA_PROMPT.read_text(encoding="utf-8")
    d = serie.datos
    return plantilla.format(
        sello_nombre=sello.nombre,
        sello_voz=sello.datos["sello"].get("voz", "").strip(),
        serie_nombre=serie.nombre_amazon,
        serie_frase=serie.frase,
        serie_promesa=d.get("promesa", ""),
        nota_enfoque=" ".join(str(d.get("nota_enfoque", "")).split()),
    )


def mensaje_usuario(libro: Libro, tramo: Tramo, n: int, total: int) -> str:
    return textwrap.dedent(f"""\
        Libro: «{libro.titulo}» — {libro.subtitulo}. Tramo {n} de {total}: {tramo.titulo}.

        <manuscrito>
        {tramo.texto.strip()}
        </manuscrito>

        Extrae los átomos de este tramo siguiendo las reglas. Recuerda: `ancla` y las citas literales se copian exactas.""")


class Extractor:
    def __init__(self, sello: Sello, modelo: str, esfuerzo: str):
        import anthropic  # importación tardía: --sin-ia y --estimar no lo necesitan

        self.anthropic = anthropic
        self.client = anthropic.Anthropic(max_retries=5)
        self.modelo = modelo
        self.esfuerzo = esfuerzo
        self.sello = sello
        self.tokens = {"entrada": 0, "salida": 0, "cache_lectura": 0, "cache_escritura": 0}

    def coste_usd(self) -> float:
        pe, ps = self.sello.precio(self.modelo)
        t = self.tokens
        return (t["entrada"] * pe + t["cache_escritura"] * pe * 1.25 + t["cache_lectura"] * pe * 0.1
                + t["salida"] * ps) / 1_000_000

    def extraer(self, sistema: str, usuario: str) -> list[dict[str, Any]] | None:
        kwargs: dict[str, Any] = dict(
            model=self.modelo,
            max_tokens=16000,
            system=[{"type": "text", "text": sistema, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": usuario}],
            output_config={"format": {"type": "json_schema", "schema": ESQUEMA_SALIDA}},
        )
        if "haiku" not in self.modelo:
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

        u = resp.usage
        self.tokens["entrada"] += u.input_tokens
        self.tokens["salida"] += u.output_tokens
        self.tokens["cache_lectura"] += getattr(u, "cache_read_input_tokens", 0) or 0
        self.tokens["cache_escritura"] += getattr(u, "cache_creation_input_tokens", 0) or 0

        if resp.stop_reason == "refusal":
            det = getattr(resp, "stop_details", None)
            print(f"    ! el modelo declinó el tramo ({getattr(det, 'category', '?')})", file=sys.stderr)
            return None
        if resp.stop_reason == "max_tokens":
            print("    ! salida truncada por max_tokens; se descarta el tramo", file=sys.stderr)
            return None
        texto = next((b.text for b in resp.content if b.type == "text"), "")
        try:
            datos = json.loads(texto)
        except json.JSONDecodeError:
            print("    ! JSON inválido; se descarta el tramo", file=sys.stderr)
            return None
        return [a for a in datos.get("atomos", []) if a.get("tipo") in TIPOS]


# ---------------------------------------------------------------------------
# Heurísticas sin modelo (para probar la cadena sin gastar)
# ---------------------------------------------------------------------------
_RE_FRASE = re.compile(r"(?<=[.!?»”])\s+(?=[A-ZÁÉÍÓÚÑ¿¡«“])")
_RE_CONTRASTE = re.compile(r"\bno (es|son)\b[^.;:]{3,120}?[:;]\s*(es|son)\b", re.IGNORECASE)


def extraer_heuristico(tramo: Tramo) -> list[dict[str, Any]]:
    limpio = re.sub(r"^#{1,6} .*$", "", tramo.texto, flags=re.MULTILINE)
    limpio = re.sub(r"[*_`>]+", "", limpio)
    frases = [f.strip() for f in _RE_FRASE.split(" ".join(limpio.split()))]
    atomos: list[dict[str, Any]] = []
    for f in frases:
        if len(f) > 220:
            continue
        tipo = None
        if len(f) >= 30 and _RE_CONTRASTE.search(f):
            tipo = "contraste"
        elif f.endswith("?") and 25 <= len(f) <= 160:
            tipo = "pregunta"
        elif len(f) >= 45 and f.endswith(".") and (f.lower().startswith("no ") or ": " in f):
            tipo = "cita"
        if not tipo:
            continue
        atomos.append({
            "tipo": tipo, "texto": f, "es_literal": True, "ancla": f,
            "temas": [], "intensidad": 3, "gancho": f[:90].rsplit(" ", 1)[0],
            "formatos": ["cita", "pin"] if tipo != "pregunta" else ["hilo", "carrusel"],
        })
        if len(atomos) >= 12:
            break
    return atomos


# ---------------------------------------------------------------------------
# Orquestación
# ---------------------------------------------------------------------------
def minar_libro(sello: Sello, serie: Serie, libro: Libro, con, *, extractor: Extractor | None,
                sin_ia: bool, rehacer: bool, max_tramos: int | None) -> dict[str, int]:
    ruta = sello.ruta_manuscrito(libro)
    if not ruta.exists():
        print(f"  ✗ {libro.titulo}: no encuentro {ruta}")
        return {"tramos": 0, "atomos": 0, "verificados": 0}
    manuscrito = ruta.read_text(encoding="utf-8")
    h = hash_texto(manuscrito)
    if not rehacer and db.hash_libro_guardado(con, libro.id) == h and not max_tramos:
        print(f"  = {libro.titulo}: sin cambios desde el último minado (usa --rehacer para forzar)")
        return {"tramos": 0, "atomos": 0, "verificados": 0}

    tramos = trocear(manuscrito)
    if max_tramos:
        tramos = tramos[:max_tramos]
    print(f"  ▸ {libro.titulo}: {len(manuscrito.split()):,} palabras · {len(tramos)} tramos")

    if rehacer or not max_tramos:
        borrados = db.borrar_atomos_de(con, libro.id)
        if borrados:
            print(f"    (se retiran {borrados} átomos anteriores)")
    db.registrar_libro(con, id=libro.id, sello=sello.id, serie=serie.id, numero=libro.numero, slug=libro.slug,
                       titulo=libro.titulo, subtitulo=libro.subtitulo, palabras=len(manuscrito.split()),
                       hash_manuscrito=h if not max_tramos else "parcial")
    con.commit()

    sistema = construir_sistema(sello, serie)
    cache_libro = normalizar_con_mapa(manuscrito)
    idioma = sello.datos["sello"].get("idioma", "es")
    total = verificados = 0
    for n, tramo in enumerate(tramos, 1):
        cache_tramo = normalizar_con_mapa(tramo.texto)
        if sin_ia:
            crudos = extraer_heuristico(tramo)
        else:
            assert extractor is not None
            crudos = extractor.extraer(sistema, mensaje_usuario(libro, tramo, n, len(tramos)))
            if crudos is None:
                continue
        filas = []
        for a in crudos:
            v = verificar_atomo(a, tramo, manuscrito, cache_tramo, cache_libro, idioma)
            v["libro_id"] = libro.id
            filas.append(v)
        insertados = db.insertar_atomos(con, filas)
        con.commit()
        ok = sum(1 for f in filas if f["verificado"])
        total += insertados
        verificados += ok
        print(f"    tramo {n:>2}/{len(tramos)} «{tramo.titulo[:48]}» → {len(filas)} átomos, {ok} verificados")
    return {"tramos": len(tramos), "atomos": total, "verificados": verificados}


def estimar(sello: Sello, libros: list[Libro], modelo: str) -> None:
    pe, ps = sello.precio(modelo)
    tot_in = tot_out = 0
    for lib in libros:
        ruta = sello.ruta_manuscrito(lib)
        if not ruta.exists():
            print(f"  ✗ {lib.titulo}: falta {ruta}")
            continue
        texto = ruta.read_text(encoding="utf-8")
        tramos = trocear(texto)
        entrada = int(len(texto.split()) * 1.6) + len(tramos) * 250  # palabras→tokens aprox. + mensaje por tramo
        salida = len(tramos) * 900
        tot_in += entrada
        tot_out += salida
        print(f"  {lib.numero:>2}. {lib.titulo:<34} {len(tramos):>3} tramos  ~{entrada:>7,} tokens entrada")
    coste = (tot_in * pe + tot_out * ps) / 1_000_000
    print(f"\n  Modelo {modelo}: ~{tot_in:,} tokens de entrada, ~{tot_out:,} de salida → ~{coste:.2f} USD "
          f"(el sistema se cachea; el coste real suele quedar por debajo)")


def listar(con, serie_id: str | None, limite: int) -> None:
    sql = """SELECT a.id, l.numero, l.titulo, a.tipo, a.texto, a.gancho, a.verificado, a.motivo_no_verificado
             FROM atomos a JOIN libros l ON l.id = a.libro_id"""
    args: tuple = ()
    if serie_id:
        sql += " WHERE l.serie = ?"
        args = (serie_id,)
    sql += " ORDER BY a.verificado DESC, RANDOM() LIMIT ?"
    for f in con.execute(sql, args + (limite,)):
        marca = "✓" if f["verificado"] else "✗"
        print(f"{marca} #{f['id']} [{f['tipo']}] L{f['numero']} {f['titulo']}")
        print(f"    {f['texto']}")
        if f["gancho"]:
            print(f"    gancho: {f['gancho']}")
        if f["motivo_no_verificado"]:
            print(f"    motivo: {f['motivo_no_verificado']}")


def main(argv: list[str] | None = None) -> int:
    consola_utf8()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sello", default="kaizen")
    p.add_argument("--serie", help="id de serie del YAML (p. ej. mente_distinta). Por defecto, todas las activas")
    p.add_argument("--libro", action="append", help="slug de libro; repetible")
    p.add_argument("--db", type=Path, default=DB_POR_DEFECTO)
    p.add_argument("--modelo", help="anula ia.modelo_minero del YAML")
    p.add_argument("--sin-ia", action="store_true", help="heurísticas locales, sin API")
    p.add_argument("--rehacer", action="store_true", help="vuelve a minar aunque el manuscrito no haya cambiado")
    p.add_argument("--max-tramos", type=int, help="solo los N primeros tramos de cada libro (pruebas)")
    p.add_argument("--estimar", action="store_true", help="estima tokens y coste sin llamar a la API")
    p.add_argument("--listar", action="store_true", help="muestra una muestra de átomos guardados")
    p.add_argument("--limite", type=int, default=20)
    args = p.parse_args(argv)

    sello = cargar_sello(args.sello)
    series = [sello.series[args.serie]] if args.serie else sello.series_activas()
    libros: list[tuple[Serie, Libro]] = []
    for s in series:
        for lib in s.libros:
            if not args.libro or lib.slug in args.libro:
                libros.append((s, lib))
    if not libros:
        print("No hay libros que minar con esos filtros.", file=sys.stderr)
        return 2

    modelo = args.modelo or sello.ia.get("modelo_minero", "claude-sonnet-5")
    print(f"Sello {sello.nombre} · fuentes en {sello.raiz_fuentes}")

    if args.estimar:
        estimar(sello, [l for _, l in libros], modelo)
        return 0

    con = db.conectar(args.db)
    if args.listar:
        listar(con, args.serie, args.limite)
        return 0

    extractor = None if args.sin_ia else Extractor(sello, modelo, sello.ia.get("esfuerzo_minero", "medium"))
    id_ej = db.abrir_ejecucion(con, "minero", None if args.sin_ia else modelo)
    resumen = {"tramos": 0, "atomos": 0, "verificados": 0}
    ok = True
    try:
        for serie, lib in libros:
            r = minar_libro(sello, serie, lib, con, extractor=extractor, sin_ia=args.sin_ia,
                            rehacer=args.rehacer, max_tramos=args.max_tramos)
            for k in resumen:
                resumen[k] += r[k]
    except KeyboardInterrupt:
        ok = False
        print("\nInterrumpido; lo ya guardado se conserva.")
    finally:
        detalle = json.dumps({**resumen, "libros": len(libros), "sin_ia": args.sin_ia}, ensure_ascii=False)
        if extractor:
            t = extractor.tokens
            db.cerrar_ejecucion(con, id_ej, ok=ok, detalle=detalle, tokens_entrada=t["entrada"],
                                tokens_salida=t["salida"], tokens_cache_lectura=t["cache_lectura"],
                                coste_usd=extractor.coste_usd())
            print(f"\nTokens: {t['entrada']:,} entrada · {t['salida']:,} salida · {t['cache_lectura']:,} de caché"
                  f" → {extractor.coste_usd():.3f} USD")
        else:
            db.cerrar_ejecucion(con, id_ej, ok=ok, detalle=detalle)
    print(f"Resultado: {resumen['atomos']} átomos nuevos ({resumen['verificados']} verificados) en {resumen['tramos']} tramos")
    print(f"Base de datos: {args.db.relative_to(RAIZ_REPO) if args.db.is_relative_to(RAIZ_REPO) else args.db}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
