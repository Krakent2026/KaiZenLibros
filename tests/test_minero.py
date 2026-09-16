from pathlib import Path

from agentes import db
from agentes.config import cargar_sello
from agentes.minero.extraer import Tramo, extraer_heuristico, trocear, verificar_atomo
from agentes.guardian.verificar_citas import normalizar_con_mapa

MANUSCRITO = """# Título

## Subtítulo del libro

## Introducción — Algo

Texto de introducción. No es pereza: es atención que no obedece. ¿Cuántas veces te lo han dicho?

# Parte I — Qué es

## Capítulo 1. Todo lo que te han dicho

""" + ("Frase de relleno número uno con suficientes palabras para contar. " * 80) + """

### Un paso hoy

Hoy anota una sola cosa que hayas terminado. No hace falta que sea grande.

## Capítulo 2. Otra cosa

""" + ("Más relleno para el segundo capítulo del libro de prueba. " * 80)


def test_trocear_funde_cortos_y_respeta_offsets():
    tramos = trocear(MANUSCRITO, min_palabras=100)
    assert len(tramos) >= 2
    for t in tramos:
        assert MANUSCRITO[t.inicio:t.inicio + len(t.texto)] == t.texto
    assert "".join(t.texto for t in tramos) == MANUSCRITO


def test_heuristico_encuentra_contraste_y_pregunta():
    tramos = trocear(MANUSCRITO, min_palabras=1)
    todos = [a for t in tramos for a in extraer_heuristico(t)]
    tipos = {a["tipo"] for a in todos}
    assert "contraste" in tipos or "cita" in tipos
    assert any(a["texto"].endswith("?") for a in todos)


def test_verificar_atomo_marca_lo_inventado():
    tramo = Tramo("Intro", MANUSCRITO, 0)
    cache = normalizar_con_mapa(MANUSCRITO)
    bueno = {"tipo": "cita", "texto": "No es pereza: es atención que no obedece.", "es_literal": True,
             "ancla": "No es pereza: es atención que no obedece. ¿Cuántas veces te lo han dicho?",
             "temas": ["culpa"], "intensidad": 3, "gancho": "Lo que te han dicho toda la vida", "formatos": ["cita"]}
    malo = {**bueno, "texto": "Este libro cura el TDAH en tres semanas.", "ancla": "frase que no existe en ninguna parte del texto"}
    v1 = verificar_atomo(bueno, tramo, MANUSCRITO, cache, cache, "es")
    v2 = verificar_atomo(malo, tramo, MANUSCRITO, cache, cache, "es")
    assert v1["verificado"] and v1["inicio"] is not None and v1["hash_fragmento"]
    assert not v2["verificado"]
    assert "ancla no encontrada" in v2["motivo_no_verificado"]
    assert "vocabulario vetado" in v2["motivo_no_verificado"]


def test_db_dedupe(tmp_path: Path):
    con = db.conectar(tmp_path / "t.sqlite")
    db.registrar_libro(con, id="s/l", sello="k", serie="s", numero=1, slug="l", titulo="T", subtitulo="",
                       palabras=10, hash_manuscrito="h")
    fila = {"libro_id": "s/l", "tipo": "cita", "texto": "x" * 50, "es_literal": 1, "ancla": "x" * 60,
            "verificado": 1}
    assert db.insertar_atomos(con, [fila, fila]) == 1


def test_config_carga_y_rutas():
    sello = cargar_sello("kaizen")
    serie = sello.series["mente_distinta"]
    assert serie.activa and len(serie.libros) == 12
    lib = serie.libro("no-es-pereza")
    assert sello.ruta_manuscrito(lib).name == "11_Version_Definitiva.md"
    assert lib.id == "mente_distinta/no-es-pereza"
