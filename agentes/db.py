"""Base de datos SQLite compartida por todos los agentes.

Tablas:
  libros        — un registro por libro minado (hash del manuscrito para detectar cambios)
  atomos        — fragmentos citables verificados contra el manuscrito
  cola          — piezas en producción (Fase 1: Redactor → Guardián → humano → Publicador)
  publicaciones — lo que salió, con su identificador externo
  metricas      — cifras recogidas por el Analista
  ejecuciones   — cada corrida de un agente, con tokens y coste
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ESQUEMA = """
CREATE TABLE IF NOT EXISTS libros (
    id              TEXT PRIMARY KEY,          -- serie/slug
    sello           TEXT NOT NULL,
    serie           TEXT NOT NULL,
    numero          INTEGER NOT NULL,
    slug            TEXT NOT NULL,
    titulo          TEXT NOT NULL,
    subtitulo       TEXT,
    palabras        INTEGER,
    hash_manuscrito TEXT,
    minado_en       TEXT
);

CREATE TABLE IF NOT EXISTS atomos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    libro_id        TEXT NOT NULL REFERENCES libros(id) ON DELETE CASCADE,
    tipo            TEXT NOT NULL,             -- cita | microleccion | pregunta | contraste | herramienta | escena | dato_honesto
    texto           TEXT NOT NULL,
    es_literal      INTEGER NOT NULL DEFAULT 0,
    ancla           TEXT NOT NULL,             -- fragmento literal del manuscrito que respalda el átomo
    capitulo        TEXT,
    inicio          INTEGER,                   -- offset del ancla en el manuscrito
    fin             INTEGER,
    hash_fragmento  TEXT,
    temas           TEXT,                      -- JSON lista
    intensidad      INTEGER,                   -- 1 (sereno) … 5 (muy emocional)
    gancho          TEXT,
    formatos        TEXT,                      -- JSON lista
    verificado      INTEGER NOT NULL DEFAULT 0,
    motivo_no_verificado TEXT,
    usos            INTEGER NOT NULL DEFAULT 0,
    ultimo_uso      TEXT,
    creado_en       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_atomos_libro ON atomos(libro_id);
CREATE INDEX IF NOT EXISTS ix_atomos_tipo ON atomos(tipo, verificado);
CREATE UNIQUE INDEX IF NOT EXISTS ux_atomos_dedupe ON atomos(libro_id, tipo, texto);

CREATE TABLE IF NOT EXISTS cola (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    atomo_id        INTEGER REFERENCES atomos(id),
    libro_id        TEXT,
    serie           TEXT,
    canal           TEXT NOT NULL,
    formato         TEXT NOT NULL,
    estado          TEXT NOT NULL DEFAULT 'planificada',
    -- planificada | redactada | producida | en_revision | rechazada | pendiente_humano | aprobada | programada | publicada | descartada
    contenido       TEXT,                      -- JSON con textos por variante
    ruta_activos    TEXT,
    motivo_rechazo  TEXT,
    intentos        INTEGER NOT NULL DEFAULT 0,
    programado_para TEXT,
    fecha_plan      TEXT,                      -- día para el que se planificó (YYYY-MM-DD)
    telegram_msg_id INTEGER,                   -- mensaje con botones enviado al humano
    enviado_humano_en TEXT,
    nota_humano     TEXT,
    publicada_en    TEXT,
    creado_en       TEXT NOT NULL,
    actualizado_en  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_cola_estado ON cola(estado, programado_para);

CREATE TABLE IF NOT EXISTS kv (
    clave           TEXT PRIMARY KEY,
    valor           TEXT
);

CREATE TABLE IF NOT EXISTS ventas_kdp (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha           TEXT NOT NULL,             -- YYYY-MM-DD (o YYYY-MM si el informe es mensual)
    titulo          TEXT NOT NULL,
    tienda          TEXT,
    unidades        REAL NOT NULL DEFAULT 0,
    gratis          REAL NOT NULL DEFAULT 0,
    kenp            REAL NOT NULL DEFAULT 0,
    regalias        REAL NOT NULL DEFAULT 0,
    fichero         TEXT,
    UNIQUE(fecha, titulo, tienda, fichero)
);

CREATE TABLE IF NOT EXISTS publicaciones (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    cola_id         INTEGER REFERENCES cola(id),
    canal           TEXT NOT NULL,
    id_externo      TEXT,
    url             TEXT,
    publicado_en    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS metricas (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    publicacion_id  INTEGER REFERENCES publicaciones(id),
    fecha           TEXT NOT NULL,
    impresiones     INTEGER,
    clics           INTEGER,
    guardados       INTEGER,
    comentarios     INTEGER,
    fuente          TEXT,
    UNIQUE(publicacion_id, fecha, fuente)
);

CREATE TABLE IF NOT EXISTS ejecuciones (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    agente          TEXT NOT NULL,
    inicio          TEXT NOT NULL,
    fin             TEXT,
    ok              INTEGER,
    detalle         TEXT,
    modelo          TEXT,
    tokens_entrada  INTEGER NOT NULL DEFAULT 0,
    tokens_salida   INTEGER NOT NULL DEFAULT 0,
    tokens_cache_lectura INTEGER NOT NULL DEFAULT 0,
    coste_usd       REAL NOT NULL DEFAULT 0
);
"""


def ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def conectar(ruta: Path) -> sqlite3.Connection:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(ruta)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    # La base viaja en git: modo DELETE para que todo quede en el fichero principal (WAL deja cambios en -wal, que git ignora).
    con.execute("PRAGMA journal_mode = DELETE")
    con.executescript(ESQUEMA)
    _migrar(con)
    return con


_COLUMNAS_NUEVAS = {
    "cola": {
        "fecha_plan": "TEXT", "telegram_msg_id": "INTEGER", "enviado_humano_en": "TEXT",
        "nota_humano": "TEXT", "publicada_en": "TEXT", "angulo": "TEXT", "ruta_audio": "TEXT",
    },
    "metricas": {"alcance": "INTEGER", "me_gusta": "INTEGER", "compartidos": "INTEGER"},
}


def _migrar(con: sqlite3.Connection) -> None:
    """Añade columnas nuevas a bases de datos creadas con esquemas anteriores."""
    for tabla, columnas in _COLUMNAS_NUEVAS.items():
        existentes = {f["name"] for f in con.execute(f"PRAGMA table_info({tabla})")}
        for col, tipo in columnas.items():
            if col not in existentes:
                con.execute(f"ALTER TABLE {tabla} ADD COLUMN {col} {tipo}")
    con.commit()


# ---- kv -------------------------------------------------------------------------
def kv_get(con: sqlite3.Connection, clave: str, por_defecto: str | None = None) -> str | None:
    fila = con.execute("SELECT valor FROM kv WHERE clave = ?", (clave,)).fetchone()
    return fila["valor"] if fila else por_defecto


def kv_set(con: sqlite3.Connection, clave: str, valor: str) -> None:
    con.execute("INSERT INTO kv (clave, valor) VALUES (?, ?) ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor",
                (clave, valor))
    con.commit()


# ---- cola -------------------------------------------------------------------------
ESTADOS = ("planificada", "redactada", "producida", "en_revision", "rechazada", "pendiente_humano",
           "aprobada", "programada", "publicada", "descartada")


def nueva_pieza(con: sqlite3.Connection, *, atomo_id: int | None, libro_id: str, serie: str, canal: str,
                formato: str, programado_para: str | None, fecha_plan: str, angulo: str | None = None) -> int:
    t = ahora()
    cur = con.execute(
        """INSERT INTO cola (atomo_id, libro_id, serie, canal, formato, estado, programado_para, fecha_plan, angulo, creado_en, actualizado_en)
           VALUES (?, ?, ?, ?, ?, 'planificada', ?, ?, ?, ?, ?)""",
        (atomo_id, libro_id, serie, canal, formato, programado_para, fecha_plan, angulo, t, t),
    )
    con.commit()
    return int(cur.lastrowid)


def publicaciones_recientes(con: sqlite3.Connection, dias: int = 30) -> list[sqlite3.Row]:
    return con.execute(
        """SELECT p.*, c.formato, c.libro_id, c.serie, l.titulo AS libro_titulo, l.numero AS libro_numero
           FROM publicaciones p JOIN cola c ON c.id = p.cola_id LEFT JOIN libros l ON l.id = c.libro_id
           WHERE p.publicado_en >= datetime('now', ?) ORDER BY p.publicado_en DESC""",
        (f"-{int(dias)} days",)).fetchall()


def guardar_metrica(con: sqlite3.Connection, publicacion_id: int, fecha: str, fuente: str, **valores: Any) -> None:
    campos = {k: v for k, v in valores.items() if k in ("impresiones", "clics", "guardados", "comentarios", "alcance", "me_gusta", "compartidos")}
    cols = ", ".join(campos)
    marcas = ", ".join("?" * len(campos))
    actualiza = ", ".join(f"{k} = excluded.{k}" for k in campos)
    con.execute(
        f"""INSERT INTO metricas (publicacion_id, fecha, fuente{', ' + cols if cols else ''})
            VALUES (?, ?, ?{', ' + marcas if marcas else ''})
            ON CONFLICT(publicacion_id, fecha, fuente) DO UPDATE SET {actualiza or 'fuente = excluded.fuente'}""",
        (publicacion_id, fecha, fuente, *campos.values()),
    )
    con.commit()


def ultimas_metricas(con: sqlite3.Connection, dias: int = 30) -> list[sqlite3.Row]:
    """La última medición de cada publicación reciente, con su pieza y libro."""
    return con.execute(
        """SELECT m.*, p.canal, p.url, c.id AS cola_id, c.formato, l.titulo AS libro_titulo, l.numero AS libro_numero,
                  a.gancho, a.tipo AS atomo_tipo
           FROM metricas m JOIN publicaciones p ON p.id = m.publicacion_id
           JOIN cola c ON c.id = p.cola_id LEFT JOIN libros l ON l.id = c.libro_id LEFT JOIN atomos a ON a.id = c.atomo_id
           WHERE m.id IN (SELECT MAX(id) FROM metricas GROUP BY publicacion_id)
             AND p.publicado_en >= datetime('now', ?)
           ORDER BY COALESCE(m.alcance, m.impresiones, 0) DESC""",
        (f"-{int(dias)} days",)).fetchall()


def uso_por_libro(con: sqlite3.Connection, serie: str) -> list[sqlite3.Row]:
    return con.execute(
        """SELECT l.slug, l.numero, l.titulo,
                  COUNT(a.id) AS atomos, SUM(CASE WHEN a.usos > 0 THEN 1 ELSE 0 END) AS usados,
                  (SELECT COUNT(*) FROM cola c WHERE c.libro_id = l.id AND c.estado NOT IN ('descartada')) AS piezas,
                  (SELECT MAX(c.fecha_plan) FROM cola c WHERE c.libro_id = l.id AND c.estado NOT IN ('descartada')) AS ultima
           FROM libros l LEFT JOIN atomos a ON a.libro_id = l.id AND a.verificado = 1
           WHERE l.serie = ? GROUP BY l.id ORDER BY l.numero""", (serie,)).fetchall()


def pieza(con: sqlite3.Connection, id_pieza: int) -> sqlite3.Row | None:
    return con.execute(
        """SELECT c.*, a.texto AS atomo_texto, a.tipo AS atomo_tipo, a.es_literal, a.ancla, a.capitulo,
                  a.gancho AS atomo_gancho, a.temas, l.titulo AS libro_titulo, l.subtitulo AS libro_subtitulo,
                  l.numero AS libro_numero, l.slug AS libro_slug
           FROM cola c LEFT JOIN atomos a ON a.id = c.atomo_id LEFT JOIN libros l ON l.id = c.libro_id
           WHERE c.id = ?""", (id_pieza,)).fetchone()


def piezas(con: sqlite3.Connection, *estados: str, limite: int = 200) -> list[sqlite3.Row]:
    marcas = ",".join("?" * len(estados)) or "''"
    return con.execute(
        f"""SELECT c.*, a.texto AS atomo_texto, a.tipo AS atomo_tipo, a.es_literal, a.ancla, a.capitulo,
                   a.gancho AS atomo_gancho, a.temas, l.titulo AS libro_titulo, l.subtitulo AS libro_subtitulo,
                   l.numero AS libro_numero, l.slug AS libro_slug
            FROM cola c LEFT JOIN atomos a ON a.id = c.atomo_id LEFT JOIN libros l ON l.id = c.libro_id
            WHERE c.estado IN ({marcas}) ORDER BY c.programado_para, c.id LIMIT ?""",
        (*estados, limite)).fetchall()


def actualizar_pieza(con: sqlite3.Connection, id_pieza: int, **campos: Any) -> None:
    if "contenido" in campos and not isinstance(campos["contenido"], (str, type(None))):
        campos["contenido"] = json.dumps(campos["contenido"], ensure_ascii=False)
    campos["actualizado_en"] = ahora()
    asignaciones = ", ".join(f"{k} = ?" for k in campos)
    con.execute(f"UPDATE cola SET {asignaciones} WHERE id = ?", (*campos.values(), id_pieza))
    con.commit()


def contenido_de(fila: sqlite3.Row) -> dict[str, Any]:
    return json.loads(fila["contenido"]) if fila["contenido"] else {}


def marcar_uso_atomo(con: sqlite3.Connection, atomo_id: int) -> None:
    con.execute("UPDATE atomos SET usos = usos + 1, ultimo_uso = ? WHERE id = ?", (ahora(), atomo_id))
    con.commit()


# ---- publicaciones -------------------------------------------------------------------
def registrar_publicacion(con: sqlite3.Connection, cola_id: int, canal: str, id_externo: str | None, url: str | None) -> int:
    cur = con.execute("INSERT INTO publicaciones (cola_id, canal, id_externo, url, publicado_en) VALUES (?, ?, ?, ?, ?)",
                      (cola_id, canal, id_externo, url, ahora()))
    con.commit()
    return int(cur.lastrowid)


def canales_publicados(con: sqlite3.Connection, cola_id: int) -> set[str]:
    return {f["canal"] for f in con.execute("SELECT canal FROM publicaciones WHERE cola_id = ?", (cola_id,))}


def atomos_candidatos(con: sqlite3.Connection, serie: str, tipos: tuple[str, ...], limite: int = 40) -> list[sqlite3.Row]:
    """Átomos verificados de la serie, los menos usados primero y repartidos entre libros."""
    marcas = ",".join("?" * len(tipos))
    return con.execute(
        f"""SELECT a.*, l.numero AS libro_numero, l.titulo AS libro_titulo, l.slug AS libro_slug
            FROM atomos a JOIN libros l ON l.id = a.libro_id
            WHERE l.serie = ? AND a.verificado = 1 AND a.tipo IN ({marcas})
            ORDER BY a.usos ASC, COALESCE(a.ultimo_uso, '') ASC, RANDOM() LIMIT ?""",
        (serie, *tipos, limite)).fetchall()


# ---- libros -----------------------------------------------------------------
def hash_libro_guardado(con: sqlite3.Connection, libro_id: str) -> str | None:
    fila = con.execute("SELECT hash_manuscrito FROM libros WHERE id = ?", (libro_id,)).fetchone()
    return fila["hash_manuscrito"] if fila else None


def registrar_libro(con: sqlite3.Connection, *, id: str, sello: str, serie: str, numero: int,
                    slug: str, titulo: str, subtitulo: str, palabras: int, hash_manuscrito: str) -> None:
    con.execute(
        """INSERT INTO libros (id, sello, serie, numero, slug, titulo, subtitulo, palabras, hash_manuscrito, minado_en)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET palabras = excluded.palabras,
               hash_manuscrito = excluded.hash_manuscrito, minado_en = excluded.minado_en,
               titulo = excluded.titulo, subtitulo = excluded.subtitulo""",
        (id, sello, serie, numero, slug, titulo, subtitulo, palabras, hash_manuscrito, ahora()),
    )


def borrar_atomos_de(con: sqlite3.Connection, libro_id: str) -> int:
    cur = con.execute("DELETE FROM atomos WHERE libro_id = ?", (libro_id,))
    return cur.rowcount


# ---- átomos -----------------------------------------------------------------
def insertar_atomos(con: sqlite3.Connection, filas: Iterable[dict[str, Any]]) -> int:
    n = 0
    for a in filas:
        cur = con.execute(
            """INSERT OR IGNORE INTO atomos
               (libro_id, tipo, texto, es_literal, ancla, capitulo, inicio, fin, hash_fragmento,
                temas, intensidad, gancho, formatos, verificado, motivo_no_verificado, creado_en)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                a["libro_id"], a["tipo"], a["texto"], int(bool(a["es_literal"])), a["ancla"],
                a.get("capitulo"), a.get("inicio"), a.get("fin"), a.get("hash_fragmento"),
                json.dumps(a.get("temas", []), ensure_ascii=False), a.get("intensidad"),
                a.get("gancho"), json.dumps(a.get("formatos", []), ensure_ascii=False),
                int(bool(a.get("verificado"))), a.get("motivo_no_verificado"), ahora(),
            ),
        )
        n += cur.rowcount
    return n


def resumen_atomos(con: sqlite3.Connection) -> list[sqlite3.Row]:
    return con.execute(
        """SELECT l.serie, l.numero, l.titulo,
                  COUNT(a.id) AS total,
                  SUM(a.verificado) AS verificados,
                  SUM(CASE WHEN a.es_literal = 1 AND a.verificado = 1 THEN 1 ELSE 0 END) AS literales
           FROM libros l LEFT JOIN atomos a ON a.libro_id = l.id
           GROUP BY l.id ORDER BY l.serie, l.numero"""
    ).fetchall()


def resumen_por_tipo(con: sqlite3.Connection) -> list[sqlite3.Row]:
    return con.execute(
        "SELECT tipo, COUNT(*) AS n, SUM(verificado) AS ok FROM atomos GROUP BY tipo ORDER BY n DESC"
    ).fetchall()


# ---- ejecuciones ------------------------------------------------------------
def abrir_ejecucion(con: sqlite3.Connection, agente: str, modelo: str | None = None) -> int:
    cur = con.execute(
        "INSERT INTO ejecuciones (agente, inicio, modelo) VALUES (?, ?, ?)", (agente, ahora(), modelo)
    )
    con.commit()
    return int(cur.lastrowid)


def cerrar_ejecucion(con: sqlite3.Connection, id_ejecucion: int, *, ok: bool, detalle: str,
                     tokens_entrada: int = 0, tokens_salida: int = 0,
                     tokens_cache_lectura: int = 0, coste_usd: float = 0.0) -> None:
    con.execute(
        """UPDATE ejecuciones SET fin = ?, ok = ?, detalle = ?, tokens_entrada = ?, tokens_salida = ?,
                  tokens_cache_lectura = ?, coste_usd = ? WHERE id = ?""",
        (ahora(), int(ok), detalle, tokens_entrada, tokens_salida, tokens_cache_lectura, coste_usd, id_ejecucion),
    )
    con.commit()


def resumen_cola(con: sqlite3.Connection) -> list[sqlite3.Row]:
    return con.execute("SELECT estado, COUNT(*) AS n FROM cola GROUP BY estado ORDER BY n DESC").fetchall()


def coste_acumulado(con: sqlite3.Connection) -> sqlite3.Row:
    return con.execute(
        """SELECT COUNT(*) AS corridas, COALESCE(SUM(tokens_entrada),0) AS entrada,
                  COALESCE(SUM(tokens_salida),0) AS salida, COALESCE(SUM(coste_usd),0) AS usd
           FROM ejecuciones"""
    ).fetchone()
