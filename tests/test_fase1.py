import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from agentes import db
from agentes.config import cargar_sello
from agentes.guardian.cola import revisar_determinista, revisar_pendientes
from agentes.planificador import hora_utc, planificar_dia
from agentes.redactor.redactar import redactar_pieza

ATOMOS = [
    ("cita", "No vas a encontrar aquí la promesa de que, si aplicas tal método, tu vida va a dar un vuelco radical en unas semanas.", 1),
    ("microleccion", "La fuerza de voluntad nunca fue el problema: lo que falla es la activación, y eso se arregla con sistemas, no con culpa.", 0),
    ("contraste", "No es falta de atención: es atención que no obedece.", 1),
    ("herramienta", "Saca una sola cosa de tu cabeza y déjala escrita donde vayas a verla mañana.", 0),
]


@pytest.fixture
def entorno(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_APROBACION", raising=False)
    sello = cargar_sello("kaizen")
    sello.datos["publicacion"]["aprobacion"] = "manual"   # los tests base usan el flujo manual
    sello.datos["plan"]["arranque"] = []                   # sin piezas institucionales salvo que el test las pida
    sello.datos["plan"]["institucional_cada_dias"] = 0
    from dataclasses import replace

    for sid in list(sello.series):                          # los tests trabajan solo con Mente distinta
        if sid != "mente_distinta":
            sello.series[sid] = replace(sello.series[sid], activa=False)
    con = db.conectar(tmp_path / "t.sqlite")
    serie = sello.series["mente_distinta"]
    for lib in serie.libros[:3]:
        db.registrar_libro(con, id=lib.id, sello="kaizen", serie="mente_distinta", numero=lib.numero, slug=lib.slug,
                           titulo=lib.titulo, subtitulo=lib.subtitulo, palabras=1000, hash_manuscrito="h")
        db.insertar_atomos(con, [
            {"libro_id": lib.id, "tipo": t, "texto": f"{tx} ({lib.numero})", "es_literal": lit, "ancla": tx,
             "verificado": 1, "temas": ["culpa"], "intensidad": 3, "gancho": "Gancho", "formatos": ["cita"]}
            for t, tx, lit in ATOMOS
        ])
    con.commit()
    return sello, con


def contenido_valido(titulo_libro: str, formato: str, cita: str = "") -> dict:
    if formato == "cita":
        diapositivas = [{"titulo": "", "cuerpo": cita}]
    else:
        diapositivas = [{"titulo": "No te falta voluntad", "cuerpo": ""}] + [
            {"titulo": "", "cuerpo": f"Idea {i} explicada con calma y sin promesas."} for i in range(2, 7)
        ] + [{"titulo": "No eras tú el problema.", "cuerpo": f"Está en «{titulo_libro}», libro 1 de la serie. Enlace en la bio."}]
    return {
        "ganchos": ["Si te pasa esto, no estás solo", "Lo que llaman pereza tiene otro nombre", "¿Y si nunca fue voluntad?"],
        "diapositivas": diapositivas,
        "caption_instagram": f"Si te pasa esto, no estás solo.\n\nUna idea del libro «{titulo_libro}». Enlace en la bio.",
        "hashtags": ["tdahadulto", "neurodivergencia", "kaizen", "noespereza", "mentedistinta"],
        "pin": {"titulo": "TDAH adulto: por qué no es falta de voluntad", "descripcion": f"Qué es el TDAH en un adulto explicado sin jerga. Del libro «{titulo_libro}», serie Mente distinta. " * 2},
        "telegram": f"Una idea de «{titulo_libro}» para hoy: la fuerza de voluntad nunca fue el problema.",
        "alt_texto": "Texto sobre fondo beige con el título del libro.",
    }


def test_hora_utc_convierte_zona():
    assert hora_utc(date(2026, 10, 12), "12:30", "Europe/Madrid") == "2026-10-12T10:30+00:00"
    assert hora_utc(date(2026, 12, 14), "12:30", "Europe/Madrid") == "2026-12-14T11:30+00:00"


def test_planificar_lunes_crea_dos_piezas_y_no_repite(entorno):
    sello, con = entorno
    lunes = date(2026, 10, 12)
    ids = planificar_dia(con, sello, lunes)
    assert len(ids) == 2
    formatos = [db.pieza(con, i)["formato"] for i in ids]
    assert formatos == ["carrusel", "cita"]
    assert planificar_dia(con, sello, lunes) == []  # ya planificado
    p = db.pieza(con, ids[0])
    assert p["estado"] == "planificada" and p["programado_para"].startswith("2026-10-12T10:30")
    usados = con.execute("SELECT COUNT(*) FROM atomos WHERE usos > 0").fetchone()[0]
    assert usados == 2


def test_guardian_determinista_acepta_y_rechaza(entorno):
    sello, con = entorno
    ids = planificar_dia(con, sello, date(2026, 10, 12))
    fila = db.pieza(con, ids[0])  # carrusel
    bueno = contenido_valido(fila["libro_titulo"], "carrusel")
    motivos, avisos = revisar_determinista(fila, bueno, sello)
    assert motivos == []
    malo = dict(bueno)
    malo["caption_instagram"] = "Este libro cura la ansiedad y mejora tu concentración. " + fila["libro_titulo"]
    malo["hashtags"] = ["a"] * 12
    motivos, _ = revisar_determinista(fila, malo, sello)
    assert any("cura" in m for m in motivos) and any("hashtags" in m for m in motivos)
    sin_libro = dict(bueno)
    sin_libro["diapositivas"] = bueno["diapositivas"][:-1] + [{"titulo": "Fin", "cuerpo": "Enlace en la bio."}]
    sin_libro["caption_instagram"] = "Sin nombrar nada."
    sin_libro["telegram"] = "Nada."
    sin_libro["pin"] = {"titulo": "x", "descripcion": "y"}
    motivos, _ = revisar_determinista(fila, sin_libro, sello)
    assert any("no nombra el libro" in m for m in motivos)


def test_cita_literal_intacta(entorno):
    sello, con = entorno
    ids = planificar_dia(con, sello, date(2026, 10, 12))
    fila = db.pieza(con, ids[1])  # cita
    ok = contenido_valido(fila["libro_titulo"], "cita", cita=fila["atomo_texto"])
    assert revisar_determinista(fila, ok, sello)[0] == []
    tocada = contenido_valido(fila["libro_titulo"], "cita", cita=fila["atomo_texto"].replace("que", "cuando", 1))
    assert tocada["diapositivas"][0]["cuerpo"] != fila["atomo_texto"]
    assert any("letra a letra" in m for m in revisar_determinista(fila, tocada, sello)[0])


class IAFalsa:
    modelo = "falso"
    tokens = {"entrada": 0, "salida": 0, "cache_lectura": 0, "cache_escritura": 0}

    def __init__(self, respuesta):
        self.respuesta = respuesta
        self.llamadas = 0

    def json(self, sistema, usuario, esquema, max_tokens=8000):
        self.llamadas += 1
        assert "Kai Zen" in sistema
        return self.respuesta

    def coste_usd(self):
        return 0.0

    def resumen(self):
        return "falso"


def test_redactor_fuerza_cita_y_guardian_pasa_al_humano(entorno):
    sello, con = entorno
    ids = planificar_dia(con, sello, date(2026, 10, 12))
    fila = db.pieza(con, ids[1])
    respuesta = contenido_valido(fila["libro_titulo"], "cita", cita="el modelo cambió la cita")
    assert redactar_pieza(con, sello, fila, IAFalsa(respuesta))
    fila = db.pieza(con, ids[1])
    assert fila["estado"] == "redactada"
    assert db.contenido_de(fila)["diapositivas"][0]["cuerpo"] == fila["atomo_texto"]
    r = revisar_pendientes(con, sello, IAFalsa({"aprobado": True, "motivos": [], "avisos": ["gancho flojo"]}))
    assert r == {"aprobadas": 1, "rechazadas": 0, "automaticas": 0}
    fila = db.pieza(con, ids[1])
    assert fila["estado"] == "pendiente_humano"
    assert db.contenido_de(fila)["avisos"] == ["criterio: gancho flojo"]


def test_guardian_criterio_rechaza(entorno):
    sello, con = entorno
    ids = planificar_dia(con, sello, date(2026, 10, 12))
    fila = db.pieza(con, ids[0])
    redactar_pieza(con, sello, fila, IAFalsa(contenido_valido(fila["libro_titulo"], "carrusel")))
    r = revisar_pendientes(con, sello, IAFalsa({"aprobado": False, "motivos": ["promesa velada"], "avisos": []}))
    assert r["rechazadas"] == 1
    fila = db.pieza(con, ids[0])
    assert fila["estado"] == "rechazada" and "criterio: promesa velada" in fila["motivo_rechazo"] and fila["intentos"] == 1


class TelegramFalso:
    disponible = True

    def __init__(self, updates):
        self.updates = updates
        self.enviados = []

    def actualizaciones(self, desde):
        return [u for u in self.updates if u["update_id"] >= desde]

    def responder_callback(self, *a):
        pass

    def quitar_botones(self, *a):
        pass

    def enviar_texto(self, chat, texto, teclado=None):
        self.enviados.append(texto)
        return {"message_id": 99}


def test_telegram_respuestas(entorno, monkeypatch):
    from agentes.aprobacion.telegram import procesar_respuestas

    sello, con = entorno
    monkeypatch.setenv("TELEGRAM_CHAT_APROBACION", "555")
    ids = planificar_dia(con, sello, date(2026, 10, 12))
    for i in ids:
        db.actualizar_pieza(con, i, estado="pendiente_humano", contenido={"x": 1})
    cb = lambda uid, data, chat="555": {"update_id": uid, "callback_query": {"id": str(uid), "data": data, "message": {"message_id": 1, "chat": {"id": int(chat)}}}}
    updates = [
        cb(10, f"ok:{ids[0]}"),
        cb(11, f"ok:{ids[1]}", chat="666"),          # otro chat: se ignora
        cb(12, f"ed:{ids[1]}"),
        {"update_id": 13, "message": {"chat": {"id": 555}, "text": "Quita la segunda frase del caption"}},
    ]
    r = procesar_respuestas(con, sello, TelegramFalso(updates))
    assert r["aprobadas"] == 1 and r["ignoradas"] == 1 and r["editar"] == 2
    assert db.pieza(con, ids[0])["estado"] == "aprobada"
    p1 = db.pieza(con, ids[1])
    assert p1["estado"] == "planificada" and p1["nota_humano"] == "Quita la segunda frase del caption"
    assert db.kv_get(con, "telegram_offset") == "14"


def test_publicar_vencidas_con_conector_falso(entorno, monkeypatch, tmp_path):
    from agentes.publicador import publicar as pub
    from agentes.publicador.base import NoDisponible, Publicador, Resultado

    sello, con = entorno
    ids = planificar_dia(con, sello, date(2026, 10, 12))
    carpeta = tmp_path / "piezas" / str(ids[0])
    carpeta.mkdir(parents=True)
    (carpeta / "01.jpg").write_bytes(b"x")
    monkeypatch.setattr("agentes.disenador.render.activos_de", lambda fila: [carpeta / "01.jpg"])
    monkeypatch.setattr(pub, "activos_de", lambda fila: [carpeta / "01.jpg"])

    class Bueno(Publicador):
        nombre = "telegram"
        def disponible(self): return True
        def publicar(self, fila, contenido, activos, sello): return Resultado("1", "https://t.me/x/1")

    class Espera(Publicador):
        nombre = "instagram"
        def disponible(self): return True
        def publicar(self, fila, contenido, activos, sello): raise NoDisponible("aún no")

    class Ausente(Publicador):
        nombre = "pinterest"
        def disponible(self): return False

    monkeypatch.setattr(pub, "CONECTORES", {"telegram": Bueno, "instagram": Espera, "pinterest": Ausente})
    db.actualizar_pieza(con, ids[0], estado="aprobada", contenido={"telegram": "hola"})
    r = pub.publicar_vencidas(con, sello, ahora=datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc))
    assert r["esperando"] == 1  # aún no es la hora
    r = pub.publicar_vencidas(con, sello, ahora=datetime(2026, 10, 12, 11, 0, tzinfo=timezone.utc))
    assert r["parciales"] == 1 and db.pieza(con, ids[0])["estado"] == "aprobada"
    assert db.canales_publicados(con, ids[0]) == {"telegram"}
    monkeypatch.setattr(pub, "CONECTORES", {"telegram": Bueno, "instagram": Bueno, "pinterest": Ausente})
    r = pub.publicar_vencidas(con, sello, ahora=datetime(2026, 10, 12, 11, 0, tzinfo=timezone.utc))
    assert r["publicadas"] == 1 and db.pieza(con, ids[0])["estado"] == "publicada"
    assert db.canales_publicados(con, ids[0]) == {"telegram", "instagram"}


def test_modo_auto_aprueba_y_rechazadas_van_a_manual(entorno):
    from agentes.guardian.cola import estado_tras_guardian

    sello, con = entorno
    ids = planificar_dia(con, sello, date(2026, 10, 12))
    fila = db.pieza(con, ids[1])
    sello.datos["publicacion"]["aprobacion"] = "auto"
    assert estado_tras_guardian(fila, ["aviso"], sello) == "aprobada"
    db.actualizar_pieza(con, ids[1], intentos=1)
    assert estado_tras_guardian(db.pieza(con, ids[1]), [], sello) == "pendiente_humano"
    sello.datos["publicacion"]["aprobacion"] = "mixto"
    fila = db.pieza(con, ids[1])  # cita literal
    db.actualizar_pieza(con, ids[1], intentos=0)
    fila = db.pieza(con, ids[1])
    assert estado_tras_guardian(fila, [], sello) == "aprobada"
    assert estado_tras_guardian(fila, ["gancho flojo"], sello) == "pendiente_humano"
    carrusel = db.pieza(con, ids[0])
    assert estado_tras_guardian(carrusel, [], sello) == "pendiente_humano"


def test_ventana_de_cancelacion(entorno, monkeypatch, tmp_path):
    from agentes.publicador import publicar as pub
    from agentes.publicador.base import Publicador, Resultado

    sello, con = entorno
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
    monkeypatch.setenv("TELEGRAM_CHAT_APROBACION", "1")
    sello.datos["publicacion"]["antelacion_minima_min"] = 60
    ids = planificar_dia(con, sello, date(2026, 10, 12))
    carpeta = tmp_path / "p"; carpeta.mkdir(); (carpeta / "01.jpg").write_bytes(b"x")
    monkeypatch.setattr(pub, "activos_de", lambda fila: [carpeta / "01.jpg"])

    class Bueno(Publicador):
        nombre = "telegram"
        def disponible(self): return True
        def publicar(self, fila, contenido, activos, sello): return Resultado("1", None)

    monkeypatch.setattr(pub, "CONECTORES", {"telegram": Bueno})
    db.actualizar_pieza(con, ids[0], estado="aprobada", contenido={"telegram": "hola"}, canal="telegram")
    tarde = datetime(2026, 10, 12, 11, 0, tzinfo=timezone.utc)   # ya pasó la hora programada
    # sin aviso enviado: espera
    assert pub.publicar_vencidas(con, sello, ahora=tarde)["esperando"] == 1
    # aviso hace 10 minutos: sigue esperando
    db.actualizar_pieza(con, ids[0], enviado_humano_en=(tarde - timedelta(minutes=10)).isoformat())
    assert pub.publicar_vencidas(con, sello, ahora=tarde)["esperando"] == 1
    # aviso hace 61 minutos: publica
    db.actualizar_pieza(con, ids[0], enviado_humano_en=(tarde - timedelta(minutes=61)).isoformat())
    assert pub.publicar_vencidas(con, sello, ahora=tarde)["publicadas"] == 1
