"""
conexion.py · NbaPontevedresa · Paso 1: comprobar la conexión con Yahoo.

Lo ejecuta GitHub Actions. Lee las claves de los Secrets (variables de entorno),
pide a Yahoo la configuración de la liga y la lista de equipos y lo guarda en:
  data/liga.json            -> resumen limpio (lo que usará la web)
  data/raw/settings.json    -> respuesta original de settings (para estudiarla)

IMPORTANTE: el repositorio es público, y sus logs también. Nunca se imprimen
tokens ni se guardan emails o datos personales de los managers.
Solo usa la librería estándar de Python.
"""

import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

LIGA_ID = "9972"
TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"
API = "https://fantasysports.yahooapis.com/fantasy/v2"
REDIRECT_URI = "https://localhost:8080"

RAIZ = Path(__file__).resolve().parent.parent
DATA = RAIZ / "data"


# ---------------------------------------------------------------- utilidades
def fallo(msg):
    print("ERROR:", msg)
    sys.exit(1)


class ErrorAPI(Exception):
    def __init__(self, codigo, url, cuerpo):
        self.codigo, self.url, self.cuerpo = codigo, url, cuerpo
        super().__init__(f"HTTP {codigo} en {url}")


def descripcion_error(e):
    try:
        return json.loads(e.cuerpo)["error"]["description"]
    except Exception:
        return e.cuerpo[:300]


def peticion(url, datos=None, cabeceras=None):
    req = urllib.request.Request(url, data=datos, headers=cabeceras or {})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise ErrorAPI(e.code, url.split("?")[0], e.read().decode(errors="replace")[:800])
    except urllib.error.URLError as e:
        fallo(f"No se pudo conectar con {url.split('?')[0]}: {e.reason}")


def obtener_token():
    cid = os.environ.get("YAHOO_CLIENT_ID", "").strip()
    sec = os.environ.get("YAHOO_CLIENT_SECRET", "").strip()
    ref = os.environ.get("YAHOO_REFRESH_TOKEN", "").strip()
    faltan = [n for n, v in (("YAHOO_CLIENT_ID", cid), ("YAHOO_CLIENT_SECRET", sec),
                             ("YAHOO_REFRESH_TOKEN", ref)) if not v]
    if faltan:
        fallo("Faltan estos Secrets en GitHub: " + ", ".join(faltan))

    basic = base64.b64encode(f"{cid}:{sec}".encode()).decode()
    datos = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "redirect_uri": REDIRECT_URI,
        "refresh_token": ref,
    }).encode()
    try:
        resp = peticion(TOKEN_URL, datos, {
            "Authorization": "Basic " + basic,
            "Content-Type": "application/x-www-form-urlencoded",
        })
    except ErrorAPI as e:
        fallo(f"Yahoo rechaza las claves al renovar el token (HTTP {e.codigo}): {e.cuerpo[:300]}")
    token = resp.get("access_token")
    if not token:
        fallo("Yahoo no ha devuelto access_token (revisa los Secrets).")
    print("OK  Token de acceso renovado.")
    return token


def api(token, ruta):
    url = f"{API}/{ruta}?format=json"
    return peticion(url, cabeceras={"Authorization": "Bearer " + token})["fantasy_content"]


def fusionar(lista):
    """Yahoo devuelve objetos como listas de diccionarios de una clave. Los une."""
    res = {}
    for item in lista if isinstance(lista, list) else [lista]:
        if isinstance(item, dict):
            res.update(item)
        elif isinstance(item, list):
            res.update(fusionar(item))
    return res


def elementos(contenedor, clave):
    """Convierte {'0': {clave: ...}, '1': ..., 'count': N} en una lista."""
    if isinstance(contenedor, list):
        return [x.get(clave) for x in contenedor if isinstance(x, dict) and clave in x]
    if not isinstance(contenedor, dict):
        return []
    out = []
    for k in sorted((k for k in contenedor if k.isdigit()), key=int):
        v = contenedor[k]
        if isinstance(v, dict) and clave in v:
            out.append(v[clave])
    return out


# ---------------------------------------------------------------- lectura
def buscar_liga(token):
    """Diagnóstico + busca la clave real de la liga entre las ligas NBA del usuario."""
    # 1) Recurso público: si esto falla, la app de Yahoo no tiene permiso de Fantasy Sports.
    try:
        juego = fusionar(api(token, "game/nba")["game"])
        print(f"OK  Juego NBA actual: game_key {juego.get('game_key')}, temporada {juego.get('season')}")
    except ErrorAPI as e:
        fallo(f"Yahoo no deja leer ni datos públicos de Fantasy (HTTP {e.codigo}: {descripcion_error(e)}).\n"
              "    -> Casi seguro la app no tiene el permiso 'Fantasy Sports - Read', o se añadió\n"
              "       después de autorizar. Revisa la app y vuelve a ejecutar autorizar_yahoo.py.")

    # 2) Ligas NBA de la cuenta autorizada.
    try:
        fc = api(token, "users;use_login=1/games;game_keys=nba/leagues")
    except ErrorAPI as e:
        fallo(f"No puedo leer tus ligas (HTTP {e.codigo}: {descripcion_error(e)}).")

    ligas = []
    for u in elementos(fc.get("users", {}), "user"):
        for g in elementos(fusionar(u).get("games", {}), "game"):
            for lg in elementos(fusionar(g).get("leagues", {}), "league"):
                ligas.append(fusionar(lg))

    print(f"OK  La cuenta autorizada está en {len(ligas)} liga(s) NBA esta temporada:")
    for lg in ligas:
        print(f"      - {lg.get('name')}  (id {lg.get('league_id')}, clave {lg.get('league_key')})")

    for lg in ligas:
        if str(lg.get("league_id")) == LIGA_ID:
            return lg["league_key"]
    fallo(f"La liga {LIGA_ID} no aparece entre las ligas de esta cuenta. ¿Autorizaste con la\n"
          "    cuenta de Yahoo con la que juegas? ¿Es correcto el ID?")


def leer_settings(token, league_key):
    fc = api(token, f"league/{league_key}/settings")
    liga = fc["league"]
    meta = liga[0]
    sets = fusionar(liga[1]["settings"])

    posiciones = []
    for rp in sets.get("roster_positions", []):
        p = rp.get("roster_position", rp)
        posiciones.append({"posicion": p.get("position"), "huecos": int(p.get("count", 1))})

    categorias = []
    for st in sets.get("stat_categories", {}).get("stats", []):
        s = st.get("stat", st)
        if s.get("is_only_display_stat") == "1":
            continue
        categorias.append({
            "id": s.get("stat_id"),
            "nombre": s.get("display_name") or s.get("abbr") or s.get("name"),
            "menos_es_mejor": s.get("sort_order") == "0",
        })

    resumen = {
        "league_key": meta.get("league_key"),
        "nombre": meta.get("name"),
        "temporada": meta.get("season"),
        "equipos": meta.get("num_teams"),
        "semana_actual": meta.get("current_week"),
        "semana_inicio": meta.get("start_week"),
        "semana_fin": meta.get("end_week"),
        "fecha_inicio": meta.get("start_date"),
        "fecha_fin": meta.get("end_date"),
        "tipo_puntuacion": meta.get("scoring_type"),
        "renew": meta.get("renew"),
        "renewed": meta.get("renewed"),
        "posiciones": posiciones,
        "categorias": categorias,
        "max_fichajes_temporada": sets.get("max_adds"),
        "max_fichajes_semana": sets.get("max_weekly_adds"),
        "tipo_draft": sets.get("draft_type"),
        "playoffs_semana_inicio": sets.get("playoff_start_week"),
        "equipos_playoffs": sets.get("num_playoff_teams"),
        "fecha_limite_traspasos": sets.get("trade_end_date"),
    }
    return resumen, fc


def leer_equipos(token, league_key):
    fc = api(token, f"league/{league_key}/teams")
    equipos = []
    for t in elementos(fc["league"][1]["teams"], "team"):
        d = fusionar(t[0] if isinstance(t, list) else t)
        managers = [m.get("nickname") for m in elementos(d.get("managers", []), "manager")
                    if isinstance(m, dict)]
        logo = ""
        logos = elementos(d.get("team_logos", []), "team_logo")
        if logos and isinstance(logos[0], dict):
            logo = logos[0].get("url", "")
        equipos.append({
            "team_key": d.get("team_key"),
            "id": d.get("team_id"),
            "nombre": d.get("name"),
            "manager": ", ".join(m for m in managers if m),  # solo apodo, nunca email
            "logo": logo,
        })
    return equipos


# ---------------------------------------------------------------- principal
def main():
    token = obtener_token()
    league_key = buscar_liga(token)
    try:
        resumen, raw = leer_settings(token, league_key)
        equipos = leer_equipos(token, resumen["league_key"])
    except ErrorAPI as e:
        fallo(f"HTTP {e.codigo} en {e.url}\n{e.cuerpo}")
    print(f"OK  Liga: {resumen['nombre']}  ({resumen['league_key']}, temporada {resumen['temporada']})")
    print(f"OK  {len(equipos)} equipos leídos.")

    resumen["lista_equipos"] = equipos
    resumen["actualizado"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    (DATA / "raw").mkdir(parents=True, exist_ok=True)
    (DATA / "liga.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=2), encoding="utf-8")
    (DATA / "raw" / "settings.json").write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n--- Resumen ---")
    print("Semana actual:", resumen["semana_actual"], "| Fechas:", resumen["fecha_inicio"], "->", resumen["fecha_fin"])
    print("Posiciones:", ", ".join(f"{p['posicion']}x{p['huecos']}" for p in resumen["posiciones"]))
    print("Categorías:", ", ".join(c["nombre"] + (" (menos=mejor)" if c["menos_es_mejor"] else "")
                                   for c in resumen["categorias"]))
    print("Fichajes máx. semana/temporada:", resumen["max_fichajes_semana"], "/", resumen["max_fichajes_temporada"])
    print("Equipos:")
    for e in equipos:
        print(f"  - {e['nombre']}")
    print("\nGuardado en data/liga.json")


if __name__ == "__main__":
    main()
