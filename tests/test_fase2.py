import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from agentes import db
from agentes.config import RAIZ_REPO, cargar_sello
from agentes.estratega.planificar import clave_plan, piezas_planificadas_para, proximo_lunes, validar_plan
from agentes.planificador import planificar_dia
from tests.test_fase1 import ATOMOS


@pytest.fixture
def entorno(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_APROBACION", raising=False)
    sello = cargar_sello("kaizen")
    sello.datos["publicacion"]["aprobacion"] = "manual"
    con = db.conectar(tmp_path / "t.sqlite")
    for lib in sello.series["mente_distinta"].libros[:4]:
        db.registrar_libro(con, id=lib.id, sello="kaizen", serie="mente_distinta", numero=lib.numero, slug=lib.slug,
                           titulo=lib.titulo, subtitulo=lib.subtitulo, palabras=1000, hash_manuscrito="h")
        db.insertar_atomos(con, [
            {"libro_id": lib.id, "tipo": t, "texto": f"{tx} ({lib.numero})", "es_literal": lit, "ancla": tx,
             "verificado": 1, "temas": ["culpa"], "intensidad": 3, "gancho": "Gancho", "formatos": ["cita"]}
            for t, tx, lit in ATOMOS
        ])
    con.commit()
    return sello, con


def test_proximo_lunes():
    assert proximo_lunes(date(2026, 9, 16)) == date(2026, 9, 21)   # miércoles → lunes siguiente
    assert proximo_lunes(date(2026, 9, 20)) == date(2026, 9, 21)   # domingo → lunes siguiente
    assert proximo_lunes(date(2026, 9, 21)) == date(2026, 9, 21)   # lunes → ese lunes


def test_validar_plan_respeta_plantilla_y_filtra(entorno):
    sello, con = entorno
    lunes = date(2026, 10, 12)
    crudo = {"resumen": "ok", "sugerencias_bibliotecario": ["gratis No es pereza el 10-10"], "dias": [
        {"fecha": "2026-10-12", "piezas": [
            {"formato": "cita", "libro_slug": "dopamina", "tipo_preferido": "cita", "angulo": "a", "motivo": "m"},
            {"formato": "carrusel", "libro_slug": "no-es-pereza", "tipo_preferido": "herramienta", "angulo": "b", "motivo": "m"},
            {"formato": "carrusel", "libro_slug": "libro-inventado", "tipo_preferido": "cita", "angulo": "c", "motivo": "m"},
        ]},
        {"fecha": "2026-10-19", "piezas": [{"formato": "cita", "libro_slug": "dopamina", "tipo_preferido": "cita", "angulo": "x", "motivo": "m"}]},
    ]}
    plan = validar_plan(crudo, sello, "mente_distinta", lunes)
    lunes_piezas = plan["dias"][0]["piezas"]
    assert [p["formato"] for p in lunes_piezas] == ["carrusel", "cita"]      # orden de la plantilla del lunes
    assert lunes_piezas[0]["libro_slug"] == "no-es-pereza" and lunes_piezas[1]["libro_slug"] == "dopamina"
    assert all(d["fecha"] >= "2026-10-12" and d["fecha"] <= "2026-10-18" for d in plan["dias"])
    assert plan["sugerencias_bibliotecario"] == ["gratis No es pereza el 10-10"]


def test_planificador_sigue_el_plan_del_estratega(entorno):
    sello, con = entorno
    lunes = date(2026, 10, 12)
    plan = validar_plan({"resumen": "", "sugerencias_bibliotecario": [], "dias": [{"fecha": "2026-10-12", "piezas": [
        {"formato": "carrusel", "libro_slug": "sistemas-para-mentes-caoticas", "tipo_preferido": "herramienta", "angulo": "Sistemas que aguantan un día malo", "motivo": ""},
        {"formato": "cita", "libro_slug": "el-tiempo-no-me-obedece", "tipo_preferido": "cita", "angulo": "", "motivo": ""},
    ]}]}, sello, "mente_distinta", lunes)
    db.kv_set(con, clave_plan(lunes), json.dumps(plan))
    assert len(piezas_planificadas_para(con, lunes)) == 2
    ids = planificar_dia(con, sello, lunes)
    p0, p1 = db.pieza(con, ids[0]), db.pieza(con, ids[1])
    assert p0["libro_slug"] == "sistemas-para-mentes-caoticas" and p0["atomo_tipo"] == "herramienta"
    assert p0["angulo"] == "Sistemas que aguantan un día malo"
    assert p1["libro_slug"] == "el-tiempo-no-me-obedece" and p1["formato"] == "cita"


def test_planificador_audio_usa_canales_por_formato(entorno):
    sello, con = entorno
    miercoles = date(2026, 10, 14)   # plantilla: [audio, cita]
    ids = planificar_dia(con, sello, miercoles)
    p = db.pieza(con, ids[0])
    assert p["formato"] == "audio" and p["canal"].startswith("podcast,")


def test_calendario_promos_sin_solapes_y_dentro_del_limite(entorno):
    from agentes.bibliotecario.calendario import calendario_promos

    sello, con = entorno
    promos = calendario_promos(sello, date(2026, 9, 22), 180)
    assert promos
    dias_ocupados: dict[str, str] = {}
    for p in promos:
        d = date.fromisoformat(p["inicio"])
        while d <= date.fromisoformat(p["fin"]):
            assert d.isoformat() not in dias_ocupados, "dos libros gratis el mismo día"
            dias_ocupados[d.isoformat()] = p["libro_slug"]
            d += timedelta(days=1)
    por_libro: dict[str, int] = {}
    for p in promos:
        if p["inicio"] < "2026-12-21":   # ventana de 90 días desde el 22-09
            por_libro[p["libro_slug"]] = por_libro.get(p["libro_slug"], 0) + p["dias"]
    assert max(por_libro.values()) <= 5


def test_recordatorios_bibliotecario(entorno):
    from agentes.bibliotecario.calendario import recordatorios

    sello, con = entorno
    avisos = recordatorios(con, sello, date(2026, 9, 20))
    assert any("GRATIS" in a for a in avisos)
    assert any("ASIN" in a for a in avisos)
    assert db.kv_get(con, "bibliotecario:promos")


def test_kdp_importa_csv_ingles_y_espanol(entorno, tmp_path):
    from agentes.analista.kdp import importar_dir, resumen_kdp

    sello, con = entorno
    (tmp_path / "kdp").mkdir()
    (tmp_path / "kdp" / "orders.csv").write_text(
        "Royalty Date,Title,Marketplace,Net Units Sold,Free Units,Royalty\n"
        "2026-09-10,No es pereza,Amazon.es,3,0,\"6,15\"\n2026-09-11,Dopamina,Amazon.com,1,12,2.05\n", encoding="utf-8")
    (tmp_path / "kdp" / "kenp.csv").write_text(
        "Fecha;Título;Tienda;KENP\n2026-09-10;No es pereza;Amazon.es;420\n", encoding="utf-8")
    assert importar_dir(con, tmp_path / "kdp") == 3
    assert importar_dir(con, tmp_path / "kdp") == 3   # idempotente: INSERT OR IGNORE
    filas = {r["titulo"]: r for r in resumen_kdp(con, 3650)}
    assert filas["No es pereza"]["unidades"] == 3 and filas["No es pereza"]["kenp"] == 420
    assert abs(filas["No es pereza"]["regalias"] - 6.15) < 0.01 and filas["Dopamina"]["gratis"] == 12


def test_bluesky_componer_texto_recorta_y_marca_enlace():
    from agentes.publicador.bluesky import componer_texto

    enlace = "https://krakent2026.github.io/KaiZenLibros/ir/no-es-pereza/?c=bs"
    texto, facets = componer_texto("palabra " * 80, enlace)
    assert len(texto) <= 300 and texto.endswith(enlace) and "…" in texto
    f = facets[0]["index"]
    assert texto.encode("utf-8")[f["byteStart"]:f["byteEnd"]].decode() == enlace


def test_feed_podcast(entorno, monkeypatch, tmp_path):
    from agentes.locutor import sintetizar as loc

    sello, con = entorno
    monkeypatch.setattr(loc, "dir_podcast", lambda s: tmp_path / "podcast")
    ids = planificar_dia(con, sello, date(2026, 10, 14))  # audio + cita
    (tmp_path / "podcast").mkdir()
    (tmp_path / "podcast" / f"{ids[0]}.mp3").write_bytes(b"\xff\xfb" * 6000)
    db.actualizar_pieza(con, ids[0], ruta_audio=str((tmp_path / "podcast" / f"{ids[0]}.mp3").relative_to(RAIZ_REPO)).replace("\\", "/")
                        if (tmp_path / "podcast").is_relative_to(RAIZ_REPO) else None,
                        contenido={"titulo_episodio": "Un paso hoy", "guion_audio": "texto " * 700, "telegram": "resumen"})
    if db.pieza(con, ids[0])["ruta_audio"] is None:
        pytest.skip("tmp_path fuera del repo; el feed usa rutas relativas al repo")
    db.registrar_publicacion(con, ids[0], "podcast", "x", None)
    ruta = loc.generar_feed(con, sello)
    xml = ruta.read_text(encoding="utf-8")
    assert "<item>" in xml and "Un paso hoy" in xml and "enclosure" in xml


def test_guardian_audio_exige_guion(entorno):
    from agentes.guardian.cola import revisar_determinista

    sello, con = entorno
    ids = planificar_dia(con, sello, date(2026, 10, 14))
    fila = db.pieza(con, ids[0])
    base = {"ganchos": ["a", "b", "c"], "diapositivas": [{"titulo": "Título del episodio", "cuerpo": ""}],
            "caption_instagram": f"Episodio sobre «{fila['libro_titulo']}». Enlace en la bio.", "hashtags": ["a", "b", "c", "d", "e"],
            "pin": {"titulo": "t", "descripcion": f"d {fila['libro_titulo']}"}, "telegram": f"t {fila['libro_titulo']}",
            "bluesky": "b", "threads": "t", "x": "x", "alt_texto": "alt", "titulo_episodio": "Título del episodio",
            "guion_audio": "palabra " * 700}
    assert revisar_determinista(fila, base, sello)[0] == []
    corto = {**base, "guion_audio": "palabra " * 100}
    assert any("guion" in m for m in revisar_determinista(fila, corto, sello)[0])
    largo_x = {**base, "x": "y" * 300}
    assert any("x de" in m for m in revisar_determinista(fila, largo_x, sello)[0])
