"""Comprueba las credenciales de .env y ayuda a obtener los ids que faltan.

    python herramientas/comprobar_credenciales.py                 # revisa todo lo que haya
    python herramientas/comprobar_credenciales.py --oauth-pinterest   # obtiene el token de Pinterest (una vez)
    python herramientas/comprobar_credenciales.py --renovar-instagram # renueva el token largo de Instagram (cada <60 días)

No modifica .env: imprime lo que hay que pegar.
"""
from __future__ import annotations

import argparse
import base64
import os
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agentes.config import consola_utf8  # noqa: E402  (importar agentes.config carga .env)

consola_utf8()
OK, KO, PEND = "✓", "✗", "·"


def anthropic_() -> None:
    clave = os.environ.get("ANTHROPIC_API_KEY", "")
    if not clave:
        print(f"{PEND} ANTHROPIC_API_KEY vacía")
        return
    try:
        import anthropic

        modelos = [m.id for m in anthropic.Anthropic().models.list(limit=50)]
        print(f"{OK} Anthropic: clave válida ({len(modelos)} modelos visibles)")
    except Exception as e:  # noqa: BLE001
        print(f"{KO} Anthropic: {e}")


def telegram() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat = os.environ.get("TELEGRAM_CHAT_APROBACION", "")
    canal = os.environ.get("TELEGRAM_CANAL", "")
    if not token:
        print(f"{PEND} TELEGRAM_BOT_TOKEN vacío → crea el bot en @BotFather")
        return
    base = f"https://api.telegram.org/bot{token}"
    r = requests.get(f"{base}/getMe", timeout=30).json()
    if not r.get("ok"):
        print(f"{KO} Telegram: token inválido ({r.get('description')})")
        return
    print(f"{OK} Telegram: bot @{r['result']['username']}")
    if not chat:
        u = requests.get(f"{base}/getUpdates", timeout=30).json().get("result", [])
        chats = {(m["chat"]["id"], m["chat"].get("first_name") or m["chat"].get("title") or m["chat"].get("username"))
                 for x in u if (m := x.get("message") or x.get("channel_post"))}
        if chats:
            print(f"{PEND} TELEGRAM_CHAT_APROBACION vacío. Chats que han escrito al bot:")
            for cid, nombre in chats:
                print(f"     TELEGRAM_CHAT_APROBACION={cid}    ({nombre})")
        else:
            print(f"{PEND} TELEGRAM_CHAT_APROBACION vacío: escribe cualquier mensaje al bot desde tu Telegram y vuelve a ejecutar")
    else:
        r = requests.post(f"{base}/sendMessage", data={"chat_id": chat, "text": "Promoción IA: conexión correcta."}, timeout=30).json()
        print(f"{OK if r.get('ok') else KO} Telegram: chat de aprobación {chat} {'recibe mensajes' if r.get('ok') else r.get('description')}")
    if canal:
        r = requests.get(f"{base}/getChat", params={"chat_id": canal}, timeout=30).json()
        if r.get("ok"):
            adm = requests.get(f"{base}/getChatMember", params={"chat_id": canal, "user_id": requests.get(f"{base}/getMe", timeout=30).json()["result"]["id"]}, timeout=30).json()
            estado = adm.get("result", {}).get("status")
            print(f"{OK if estado in ('administrator', 'creator') else KO} Telegram: canal {canal} · el bot es {estado or 'desconocido'} (debe ser administrator)")
        else:
            print(f"{KO} Telegram: canal {canal}: {r.get('description')}")
    else:
        print(f"{PEND} TELEGRAM_CANAL vacío (canal público de lectores; opcional hasta que exista)")


def pinterest_token_desde_refresh() -> str | None:
    app, secreto, refresh = (os.environ.get(k, "") for k in ("PINTEREST_APP_ID", "PINTEREST_APP_SECRET", "PINTEREST_REFRESH_TOKEN"))
    if not (app and secreto and refresh):
        return None
    r = requests.post("https://api.pinterest.com/v5/oauth/token",
                      headers={"Authorization": "Basic " + base64.b64encode(f"{app}:{secreto}".encode()).decode()},
                      data={"grant_type": "refresh_token", "refresh_token": refresh}, timeout=30)
    return r.json().get("access_token") if r.ok else None


def pinterest() -> None:
    token = pinterest_token_desde_refresh() or os.environ.get("PINTEREST_TOKEN", "")
    tablero = os.environ.get("PINTEREST_TABLERO_ID", "")
    if not token:
        print(f"{PEND} Pinterest: sin token → ejecuta con --oauth-pinterest")
        return
    h = {"Authorization": f"Bearer {token}"}
    r = requests.get("https://api.pinterest.com/v5/user_account", headers=h, timeout=30)
    if not r.ok:
        print(f"{KO} Pinterest: token inválido o caducado ({r.status_code}) → --oauth-pinterest")
        return
    print(f"{OK} Pinterest: cuenta @{r.json().get('username')}")
    tableros = requests.get("https://api.pinterest.com/v5/boards", headers=h, params={"page_size": 50}, timeout=30).json().get("items", [])
    if not tablero:
        print(f"{PEND} PINTEREST_TABLERO_ID vacío. Tableros:")
        for t in tableros:
            print(f"     PINTEREST_TABLERO_ID={t['id']}    ({t['name']})")
        if not tableros:
            print("     (ninguno: crea un tablero «Mente distinta» en Pinterest y vuelve a ejecutar)")
    else:
        ok = any(t["id"] == tablero for t in tableros)
        print(f"{OK if ok else KO} Pinterest: tablero {tablero} {'existe' if ok else 'no aparece entre tus tableros'}")


def oauth_pinterest() -> None:
    app = os.environ.get("PINTEREST_APP_ID") or input("App ID de Pinterest: ").strip()
    secreto = os.environ.get("PINTEREST_APP_SECRET") or input("App secret: ").strip()
    redirect = "https://localhost/"
    url = ("https://www.pinterest.com/oauth/?response_type=code&client_id=" + app +
           "&redirect_uri=" + redirect + "&scope=boards:read,pins:read,pins:write,user_accounts:read")
    print("\n1. En la app de Pinterest, añade esta Redirect URI exacta:", redirect)
    print("2. Abre esta URL en el navegador, autoriza, y copia el parámetro code= de la URL a la que te redirige (dará error de página, es normal):\n")
    print(url, "\n")
    code = input("code: ").strip()
    r = requests.post("https://api.pinterest.com/v5/oauth/token",
                      headers={"Authorization": "Basic " + base64.b64encode(f"{app}:{secreto}".encode()).decode()},
                      data={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect}, timeout=30)
    d = r.json()
    if not r.ok:
        print(f"{KO} {d}")
        return
    print("\nPega en .env (y como Secrets en GitHub):")
    print(f"PINTEREST_APP_ID={app}\nPINTEREST_APP_SECRET={secreto}\nPINTEREST_REFRESH_TOKEN={d.get('refresh_token')}\nPINTEREST_TOKEN={d.get('access_token')}")
    print(f"\nEl access token dura {d.get('expires_in', 0) // 86400} días; el sistema lo renueva solo con el refresh token (válido ~1 año).")


def instagram(renovar: bool = False) -> None:
    token = os.environ.get("INSTAGRAM_TOKEN", "")
    cuenta = os.environ.get("INSTAGRAM_CUENTA_ID", "")
    if not token:
        print(f"{PEND} INSTAGRAM_TOKEN vacío → panel de Meta for Developers, «Generar token»")
        return
    r = requests.get("https://graph.instagram.com/v23.0/me", params={"fields": "user_id,username,account_type", "access_token": token}, timeout=30).json()
    if "error" in r:
        print(f"{KO} Instagram: {r['error'].get('message')}")
        return
    print(f"{OK} Instagram: @{r.get('username')} ({r.get('account_type')})")
    if not cuenta:
        print(f"{PEND} INSTAGRAM_CUENTA_ID vacío. Pega:\n     INSTAGRAM_CUENTA_ID={r.get('user_id')}")
    elif str(cuenta) != str(r.get("user_id")):
        print(f"{KO} INSTAGRAM_CUENTA_ID={cuenta} no coincide con el del token ({r.get('user_id')})")
    if renovar:
        n = requests.get("https://graph.instagram.com/refresh_access_token",
                         params={"grant_type": "ig_refresh_token", "access_token": token}, timeout=30).json()
        if "access_token" in n:
            print(f"\nToken renovado ({n.get('expires_in', 0) // 86400} días). Pega en .env y en GitHub:\nINSTAGRAM_TOKEN={n['access_token']}")
        else:
            print(f"{KO} No se pudo renovar: {n}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--oauth-pinterest", action="store_true")
    p.add_argument("--renovar-instagram", action="store_true")
    a = p.parse_args()
    if a.oauth_pinterest:
        oauth_pinterest()
        return 0
    anthropic_()
    telegram()
    pinterest()
    instagram(renovar=a.renovar_instagram)
    print(f"\nKAIZEN_FUENTES: {'existe' if Path(os.environ.get('KAIZEN_FUENTES', '')).is_dir() else 'NO existe'} → {os.environ.get('KAIZEN_FUENTES', '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
