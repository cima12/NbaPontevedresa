"""
avisos.py · NbaPontevedresa · Avisos de alineación al móvil por Telegram.

Lo ejecuta el Action "Actualizar liga" después de conexion.py. Solo hace algo si
existen los Secrets TELEGRAM_TOKEN y TELEGRAM_CHAT_ID (ver el resumen del proyecto
para crear el bot). Si no, termina sin hacer nada.

Mira la alineación de HOY (hora de EE. UU.) del equipo MI_EQUIPO (por defecto
"Grit & Grind") y avisa de:
  - titulares de baja (O, INJ...) que juegan hoy,
  - jugadores en el banquillo que juegan hoy mientras un titular no juega,
  - huecos de titular vacíos,
  - jugadores en IL que Yahoo ya no marca como lesionados.
Solo envía por la tarde-noche en España (antes de los partidos) y no repite el
mismo aviso el mismo día (guarda una huella en data/liga/avisos.json).
"""

import hashlib
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DATA = RAIZ / "data"
FUERA = {"O", "INJ", "NA", "SUSP"}
NO_TITULAR = {"BN", "IL", "IL+", "NA"}


def leer(ruta, defecto=None):
    try:
        return json.loads(Path(ruta).read_text(encoding="utf-8"))
    except Exception:
        return defecto


def enviar(token, chat, texto):
    datos = urllib.parse.urlencode({"chat_id": chat, "text": texto, "disable_web_page_preview": "true"}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=datos)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode()).get("ok", False)
    except Exception as e:                 # nunca imprimir el token
        print(f"AVISO  Telegram no ha aceptado el mensaje ({type(e).__name__}).")
        return False


def avisos_de_hoy(liga, plant, cal, mi_equipo, hoy):
    equipo = next((e for e in liga.get("equipos", []) if e["nombre"] == mi_equipo or e["key"] == mi_equipo), None)
    if not equipo:
        return None, [f"No encuentro el equipo «{mi_equipo}» en la liga."]
    juegan = {g["local"] for g in cal if g["fecha"] == hoy and g["estado"] == 1} | \
             {g["visitante"] for g in cal if g["fecha"] == hoy and g["estado"] == 1}
    jug = plant["equipos"].get(equipo["key"], [])
    titular = lambda j: j.get("hueco") and j["hueco"] not in NO_TITULAR      # noqa: E731
    out = []
    for j in jug:
        if titular(j) and j.get("estado") in FUERA and j["equipo_nba"] in juegan:
            out.append(f"⛔ {j['nombre']} es titular y está de baja ({j['estado']}).")
    banq = [j for j in jug if j.get("hueco") == "BN" and j["equipo_nba"] in juegan and j.get("estado") not in FUERA]
    titulares_parados = [j for j in jug if titular(j) and (j["equipo_nba"] not in juegan or j.get("estado") in FUERA)]
    if banq and titulares_parados:
        out.append("🪑 Juegan hoy y están en el banquillo: " + ", ".join(j["nombre"] for j in banq) +
                   ". Titulares que no juegan: " + ", ".join(j["nombre"] for j in titulares_parados) + ".")
    huecos = sum(p["huecos"] for p in liga.get("posiciones", []) if p["posicion"] not in NO_TITULAR)
    n_tit = sum(1 for j in jug if titular(j))
    if huecos and n_tit < huecos:
        out.append(f"🕳️ Tienes {huecos - n_tit} hueco(s) de titular vacío(s).")
    for j in jug:
        if j.get("hueco") in ("IL", "IL+") and not j.get("estado"):
            out.append(f"🩹 {j['nombre']} está en IL pero ya no figura lesionado.")
    return equipo, out


def main():
    token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        print("Avisos por Telegram desactivados (faltan los Secrets TELEGRAM_TOKEN / TELEGRAM_CHAT_ID).")
        return
    if os.environ.get("PRUEBA_TELEGRAM") == "1":
        ok = enviar(token, chat, "🏀 NBA Pontevedresa: los avisos por Telegram funcionan ✅")
        print("OK  Mensaje de prueba enviado." if ok else "ERROR: no se pudo enviar (revisa el token y el chat id).")
        return 0 if ok else 1
    ahora = datetime.now(timezone.utc)
    forzar = os.environ.get("FORZAR_AVISO") == "1"
    if not forzar and not (14 <= ahora.hour <= 23):          # solo antes de los partidos
        print("Fuera del horario de avisos (14:00–23:59 UTC).")
        return
    liga = leer(DATA / "liga" / "liga.json")
    plant = leer(DATA / "liga" / "plantillas.json")
    cal = (leer(DATA / "nba" / "calendario.json") or {}).get("partidos", [])
    if not liga or not plant:
        print("Todavía no hay datos de la liga: no hay nada que avisar.")
        return
    hoy = (ahora - timedelta(hours=5)).date().isoformat()
    equipo, avisos = avisos_de_hoy(liga, plant, cal, os.environ.get("MI_EQUIPO") or "Grit & Grind", hoy)
    if not avisos:
        print("OK  Alineación de hoy sin problemas: no se envía nada.")
        return
    texto = f"🏀 {equipo['nombre'] if equipo else 'NBA Pontevedresa'} · alineación de hoy\n\n" + "\n".join(avisos) + \
            "\n\nhttps://cima12.github.io/NbaPontevedresa/"
    huella = hashlib.sha1(texto.encode()).hexdigest()[:12]
    previo = leer(DATA / "liga" / "avisos.json", {})
    if not forzar and previo.get("fecha") == hoy and previo.get("huella") == huella:
        print("Ese aviso ya se envió hoy.")
        return
    if enviar(token, chat, texto):
        (DATA / "liga" / "avisos.json").write_text(json.dumps({"fecha": hoy, "huella": huella}), encoding="utf-8")
        print(f"OK  Aviso enviado por Telegram ({len(avisos)} punto(s)).")


if __name__ == "__main__":
    sys.exit(main())
