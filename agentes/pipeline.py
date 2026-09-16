"""Punto de entrada de los workflows y de la operación manual.

    python -m agentes.pipeline diario        # planificar → redactar → guardián → imágenes y audio → previas a Telegram → respuestas → publicar → métricas
    python -m agentes.pipeline aprobaciones  # respuestas de Telegram → publicar lo vencido → limpieza (cada 2 h)
    python -m agentes.pipeline semanal       # Estratega (plan) → Bibliotecario (recordatorios) → Analista (informe) → resumen a Telegram
    python -m agentes.pipeline estado        # inventario
    python -m agentes.pipeline cola          # piezas vivas con su estado
    python -m agentes.pipeline ver --id 12   # contenido completo de una pieza
    python -m agentes.pipeline aprobar --id 12 [--nota "..."]
    python -m agentes.pipeline rechazar --id 12 [--nota "..."]
    python -m agentes.pipeline editar --id 12 --nota "..."

Todo paso que llama a la API registra tokens y coste en `ejecuciones`.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from agentes import db
from agentes.config import DB_POR_DEFECTO, RAIZ_REPO, Sello, cargar_sello, consola_utf8


def _hay_api() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def _telegram():
    from agentes.aprobacion.telegram import Telegram

    tg, chat = Telegram(), os.environ.get("TELEGRAM_CHAT_APROBACION", "")
    return (tg, chat) if tg.disponible and chat else (None, "")


def _paso(titulo: str) -> None:
    print(f"\n▸ {titulo}")


# ---- consultas ---------------------------------------------------------------------
def estado(ruta_db: Path) -> int:
    con = db.conectar(ruta_db)
    print("== Átomos por libro ==")
    filas = db.resumen_atomos(con)
    if not filas:
        print("  (ninguno; ejecuta el Minero)")
    for f in filas:
        print(f"  {f['serie']:<22} {f['numero']:>2}. {f['titulo']:<34} {f['total'] or 0:>4} átomos "
              f"({f['verificados'] or 0} verificados, {f['literales'] or 0} citas literales)")
    print("== Átomos por tipo ==")
    for f in db.resumen_por_tipo(con):
        print(f"  {f['tipo']:<14} {f['n']:>4} ({f['ok'] or 0} verificados)")
    print("== Cola ==")
    cola_ = db.resumen_cola(con)
    print("  vacía" if not cola_ else "\n".join(f"  {f['estado']:<18} {f['n']}" for f in cola_))
    c = db.coste_acumulado(con)
    print(f"== Coste acumulado == {c['corridas']} corridas · {c['entrada']:,} tokens entrada · "
          f"{c['salida']:,} salida · {c['usd']:.3f} USD")
    return 0


def cola(ruta_db: Path) -> int:
    con = db.conectar(ruta_db)
    vivas = db.piezas(con, "planificada", "redactada", "rechazada", "pendiente_humano", "aprobada", "programada")
    if not vivas:
        print("Cola vacía")
        return 0
    for f in vivas:
        print(f"#{f['id']:<4} {f['estado']:<17} {f['formato']:<8} {f['programado_para'] or '—':<22} "
              f"L{f['libro_numero']} {f['libro_titulo']:<30} int={f['intentos']} "
              f"{'img' if f['ruta_activos'] else '   '} {'mp3' if f['ruta_audio'] else '   '} "
              f"{('| ' + (f['motivo_rechazo'] or '')[:70]) if f['motivo_rechazo'] else ''}")
    return 0


def ver(ruta_db: Path, id_pieza: int) -> int:
    con = db.conectar(ruta_db)
    f = db.pieza(con, id_pieza)
    if not f:
        print("no existe")
        return 1
    print(f"Pieza #{f['id']} · {f['estado']} · {f['formato']} · {f['canal']} · {f['programado_para']}")
    print(f"Libro {f['libro_numero']}: {f['libro_titulo']} — átomo [{f['atomo_tipo']}] «{f['atomo_texto']}»")
    if f["angulo"]:
        print(f"Ángulo: {f['angulo']}")
    if f["motivo_rechazo"]:
        print(f"Motivo de rechazo: {f['motivo_rechazo']}")
    if f["nota_humano"]:
        print(f"Nota humana: {f['nota_humano']}")
    print(json.dumps(db.contenido_de(f), ensure_ascii=False, indent=2))
    return 0


def decidir(ruta_db: Path, id_pieza: int, decision: str, nota: str | None) -> int:
    from agentes.aprobacion.telegram import aplicar_decision

    con = db.conectar(ruta_db)
    print(f"#{id_pieza}: {aplicar_decision(con, id_pieza, decision, nota)}")
    return 0


# ---- utilidades de ciclo -----------------------------------------------------------
def limpiar_piezas_antiguas(con, sello: Sello) -> int:
    dias = int(sello.datos.get("publicacion", {}).get("dias_conservar_piezas", 21))
    limite = (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat()
    n = 0
    for f in con.execute(
        "SELECT id, ruta_activos FROM cola WHERE ruta_activos IS NOT NULL AND estado IN ('publicada','descartada') AND actualizado_en < ?",
        (limite,)).fetchall():
        ruta = RAIZ_REPO / f["ruta_activos"]
        if ruta.exists():
            shutil.rmtree(ruta, ignore_errors=True)
        db.actualizar_pieza(con, f["id"], ruta_activos=None)
        n += 1
    return n


def recoger_metricas_diarias(con, sello: Sello) -> dict:
    from agentes.analista.recoger import recoger_metricas

    clave = f"metricas:{date.today().isoformat()}"
    if db.kv_get(con, clave):
        return {"ya_recogidas": 1}
    r = recoger_metricas(con, sello)
    db.kv_set(con, clave, json.dumps(r))
    return r


# ---- ciclos --------------------------------------------------------------------------
def aprobaciones(ruta_db: Path, sello_id: str) -> int:
    from agentes.aprobacion.telegram import procesar_respuestas
    from agentes.publicador.publicar import publicar_vencidas

    sello = cargar_sello(sello_id)
    con = db.conectar(ruta_db)
    ej = db.abrir_ejecucion(con, "pipeline_aprobaciones")
    _paso("Respuestas de Telegram")
    r1 = procesar_respuestas(con, sello)
    print(f"  {r1}")
    _paso("Publicar lo aprobado y vencido")
    r2 = publicar_vencidas(con, sello)
    print(f"  {r2}")
    n = limpiar_piezas_antiguas(con, sello)
    if n:
        print(f"  limpieza: {n} carpetas de piezas antiguas retiradas")
    db.cerrar_ejecucion(con, ej, ok=True, detalle=json.dumps({"respuestas": r1, "publicacion": r2, "limpieza": n}))
    return 0


def diario(ruta_db: Path, sello_id: str) -> int:
    from agentes.aprobacion.telegram import enviar_previas, procesar_respuestas
    from agentes.guardian.cola import revisar_pendientes
    from agentes.ia import cliente_para
    from agentes.planificador import planificar
    from agentes.publicador.publicar import publicar_vencidas
    from agentes.redactor.redactar import redactar_pendientes

    sello = cargar_sello(sello_id)
    con = db.conectar(ruta_db)
    ej = db.abrir_ejecucion(con, "pipeline_diario")
    detalle: dict = {}
    n_atomos = con.execute("SELECT COUNT(*) FROM atomos WHERE verificado = 1").fetchone()[0]
    print(f"Sello {sello.nombre}: {len(sello.libros_activos())} libros activos, {n_atomos} átomos verificados")
    if n_atomos == 0:
        print("Sin átomos verificados: ejecuta el Minero en local y sube datos/atomos.sqlite. Nada que planificar.")
        db.cerrar_ejecucion(con, ej, ok=True, detalle="sin átomos")
        return 0

    _paso("Planificar")
    detalle["planificadas"] = planificar(con, sello)

    coste = 0.0
    if not _hay_api():
        print("\n! Sin ANTHROPIC_API_KEY: no se redacta ni se revisa con criterio. Las piezas quedan planificadas.")
    else:
        redactor = cliente_para(sello, "redactor")
        guardian = cliente_para(sello, "guardian")
        max_int = int(sello.datos.get("plan", {}).get("max_reintentos_redaccion", 2))
        for vuelta in range(max_int + 1):
            _paso(f"Redactar (vuelta {vuelta + 1})")
            r = redactar_pendientes(con, sello, redactor)
            print(f"  {r}")
            _paso("Guardián")
            g = revisar_pendientes(con, sello, guardian)
            print(f"  {g}")
            if g["rechazadas"] == 0:
                break
        detalle["ia"] = {"redactor": redactor.resumen(), "guardian": guardian.resumen()}
        coste = redactor.coste_usd() + guardian.coste_usd()
        print(f"  {redactor.resumen()}\n  {guardian.resumen()}")

    _paso("Producir imágenes")
    try:
        from agentes.disenador.render import producir_pendientes

        detalle["producidas"] = producir_pendientes(con, sello)
        print(f"  {detalle['producidas']} piezas producidas")
    except RuntimeError as e:
        print(f"  ! {e}")

    _paso("Producir audio (episodios)")
    try:
        from agentes.locutor.sintetizar import sintetizar_pendientes

        detalle["audios"] = sintetizar_pendientes(con, sello)
        print(f"  {detalle['audios']} audios")
    except Exception as e:  # noqa: BLE001
        print(f"  ! {e}")

    _paso("Enviar previas a Telegram")
    detalle["previas"] = enviar_previas(con, sello)
    _paso("Respuestas de Telegram")
    detalle["respuestas"] = procesar_respuestas(con, sello)
    _paso("Publicar lo aprobado y vencido")
    detalle["publicacion"] = publicar_vencidas(con, sello)
    print(f"  {detalle['publicacion']}")
    _paso("Métricas del día")
    try:
        detalle["metricas"] = recoger_metricas_diarias(con, sello)
        print(f"  {detalle['metricas']}")
    except Exception as e:  # noqa: BLE001
        print(f"  ! {e}")
    detalle["limpieza"] = limpiar_piezas_antiguas(con, sello)

    con.execute("UPDATE ejecuciones SET detalle = ?, fin = ?, ok = 1, coste_usd = ? WHERE id = ?",
                (json.dumps(detalle, ensure_ascii=False, default=str), db.ahora(), coste, ej))
    con.commit()
    print()
    return cola(ruta_db)


def semanal(ruta_db: Path, sello_id: str) -> int:
    from agentes.analista.informe import generar_informe, guardar, resumen_telegram
    from agentes.analista.kdp import importar_dir
    from agentes.bibliotecario.calendario import recordatorios
    from agentes.estratega.planificar import generar_plan, proximo_lunes

    sello = cargar_sello(sello_id)
    con = db.conectar(ruta_db)
    ej = db.abrir_ejecucion(con, "pipeline_semanal")
    detalle: dict = {}
    partes_digest: list[str] = []

    _paso("Bibliotecario")
    avisos = recordatorios(con, sello)
    for a in avisos:
        print(f"  · {a}")
    detalle["bibliotecario"] = len(avisos)
    if avisos:
        partes_digest.append("RECORDATORIOS\n" + "\n".join(f"• {a}" for a in avisos))

    _paso("Analista")
    try:
        n_kdp = importar_dir(con, RAIZ_REPO / sello.datos.get("analista", {}).get("dir_kdp", "datos/kdp"))
        if n_kdp:
            print(f"  KDP: {n_kdp} filas importadas")
        recoger_metricas_diarias(con, sello)
    except Exception as e:  # noqa: BLE001
        print(f"  ! métricas: {e}")
    texto = generar_informe(con, sello, 7)
    ruta = guardar(texto)
    print(f"  informe en {ruta.relative_to(RAIZ_REPO)}")
    partes_digest.append(resumen_telegram(texto, 2500))

    coste = 0.0
    _paso("Estratega")
    if _hay_api():
        from agentes.ia import cliente_para

        ia = cliente_para(sello, "estratega")
        plan = generar_plan(con, sello, ia, proximo_lunes())
        coste = ia.coste_usd()
        print(f"  {ia.resumen()}")
        if plan:
            detalle["plan_semana"] = plan["semana"]
            partes_digest.insert(0, f"PLAN DE LA SEMANA DEL {plan['semana']}\n{plan.get('resumen', '')}")
    else:
        print("  ! sin API: el planificador diario usará la plantilla del YAML")

    tg, chat = _telegram()
    if tg and partes_digest:
        try:
            tg.enviar_texto(chat, "\n\n".join(partes_digest)[:4000])
            print("  → resumen semanal enviado a Telegram")
        except RuntimeError as e:
            print(f"  ! Telegram: {e}")
    db.cerrar_ejecucion(con, ej, ok=True, detalle=json.dumps(detalle, ensure_ascii=False), coste_usd=coste)
    return 0


def main(argv: list[str] | None = None) -> int:
    consola_utf8()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("orden", choices=("estado", "cola", "ver", "aprobar", "rechazar", "editar", "diario", "aprobaciones", "semanal"))
    p.add_argument("--sello", default="kaizen")
    p.add_argument("--db", type=Path, default=DB_POR_DEFECTO)
    p.add_argument("--id", type=int)
    p.add_argument("--nota")
    a = p.parse_args(argv)
    if a.orden == "estado":
        return estado(a.db)
    if a.orden == "cola":
        return cola(a.db)
    if a.orden in ("ver", "aprobar", "rechazar", "editar"):
        if a.id is None:
            p.error("--id es obligatorio")
        if a.orden == "ver":
            return ver(a.db, a.id)
        if a.orden == "editar" and not a.nota:
            p.error("--nota es obligatoria para editar")
        return decidir(a.db, a.id, {"aprobar": "ok", "rechazar": "no", "editar": "ed"}[a.orden], a.nota)
    if a.orden == "diario":
        return diario(a.db, a.sello)
    if a.orden == "aprobaciones":
        return aprobaciones(a.db, a.sello)
    return semanal(a.db, a.sello)


if __name__ == "__main__":
    sys.exit(main())
