"""
conexion.py · NbaPontevedresa · Datos de la liga de Yahoo.

Lo ejecuta el Action "Actualizar liga" (varias veces al día). Mientras Yahoo no
apruebe la app, termina sin error con un aviso ⏳ y no guarda nada: así, el día
que aprueben, los datos empiezan a llegar solos.

Qué hace:
  1. Renueva el token con los Secrets.
  2. Busca la liga de la temporada actual SIN ID FIJO:
       a) sigue la cadena "renewed" desde la última liga guardada en data/liga/liga.json;
       b) si no, la única liga NBA de la cuenta (o la del mismo nombre, o la de LIGA_ID).
  3. Lee settings, equipos, clasificación, enfrentamientos de la semana, plantillas
     de hoy y las posiciones de Yahoo de los mejores agentes libres.
  4. Guarda JSON limpios en data/liga/ (lo que lee la web):
       liga.json            -> configuración, categorías, huecos, equipos (sin emails)
       clasificacion.json   -> récord y puesto de cada equipo
       enfrentamientos.json -> semana actual: estadísticas de cada equipo por categoría
       plantillas.json      -> jugadores de cada equipo, hueco de hoy, estado, posiciones
       posiciones.json      -> {id NBA: "PG,SG"} posición oficial de Yahoo (la usa nba.py)

IMPORTANTE: el repositorio y sus logs son públicos. Nunca se imprimen tokens ni se
guardan emails. Solo librería estándar de Python.

Pruebas sin Yahoo: con la variable YAHOO_FIXTURES=<carpeta> lee las respuestas de
archivos JSON en vez de llamar a Yahoo (ver scripts/pruebas/).
"""

import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from perfiles import normalizar  # noqa: E402

LIGA_ID = os.environ.get("LIGA_ID", "9972")          # solo como último recurso
TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"
API = "https://fantasysports.yahooapis.com/fantasy/v2"
REDIRECT_URI = "https://localhost:8080"
PAUSA = 0.4                                          # entre consultas (Yahoo no publica límites)
LIBRES_PAGINAS = 8                                   # 8 x 25 = 200 mejores agentes libres

RAIZ = Path(__file__).resolve().parent.parent
DATA = RAIZ / "data"
DIR_LIGA = Path(os.environ.get("LIGA_SALIDA") or DATA / "liga")   # pruebas: data/liga_prueba
FIXTURES = os.environ.get("YAHOO_FIXTURES")

# stat_id de Yahoo (baloncesto) -> nombre corto que usa la web
STATS = {"5": "fg_pct", "8": "ft_pct", "10": "tpm", "12": "pts", "15": "reb",
         "16": "ast", "17": "stl", "18": "blk", "19": "to",
         "9004003": "fgm_fga", "9007006": "ftm_fta"}
# Abreviaturas de Yahoo -> NBA
YAHOO_A_NBA = {"GS": "GSW", "NY": "NYK", "SA": "SAS", "NO": "NOP", "PHO": "PHX",
               "UTAH": "UTA", "WSH": "WAS", "BRK": "BKN"}


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


def no_autorizada(e):
    return e.codigo == 403 and "not authorized" in e.cuerpo.lower()


def peticion(url, datos=None, cabeceras=None):
    req = urllib.request.Request(url, data=datos, headers=cabeceras or {})
    for intento in range(3):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            cuerpo = e.read().decode(errors="replace")[:800]
            if e.code in (429, 500, 502, 503, 999) and intento < 2:   # saturado: esperar y repetir
                time.sleep(10 * (intento + 1))
                continue
            raise ErrorAPI(e.code, url.split("?")[0], cuerpo)
        except urllib.error.URLError as e:
            if intento < 2:
                time.sleep(5)
                continue
            fallo(f"No se pudo conectar con {url.split('?')[0]}: {e.reason}")


def obtener_token():
    if FIXTURES:
        return "token-de-prueba"
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


def _fixture(ruta):
    ruta = re.sub(r"date=[\d-]+", "date=FECHA", ruta)
    nombre = re.sub(r"[^A-Za-z0-9]+", "_", ruta).strip("_") + ".json"
    f = Path(FIXTURES) / nombre
    if not f.exists():
        raise ErrorAPI(404, ruta, f"(prueba) falta el archivo {nombre}")
    return json.loads(f.read_text(encoding="utf-8"))["fantasy_content"]


def api(token, ruta):
    if FIXTURES:
        return _fixture(ruta)
    url = f"{API}/{ruta}?format=json"
    res = peticion(url, cabeceras={"Authorization": "Bearer " + token})["fantasy_content"]
    time.sleep(PAUSA)
    return res


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
        out = []
        for x in contenedor:
            if isinstance(x, dict) and clave in x:
                out.append(x[clave])
            elif isinstance(x, dict):
                out.extend(elementos(x, clave))
        return out
    if not isinstance(contenedor, dict):
        return []
    out = []
    for k in sorted((k for k in contenedor if str(k).isdigit()), key=int):
        v = contenedor[k]
        if isinstance(v, dict) and clave in v:
            out.append(v[clave])
    return out


def bloque(fc_liga, clave):
    """En fantasy_content.league = [meta, {clave: ...}] devuelve el contenido de 'clave'."""
    for parte in fc_liga if isinstance(fc_liga, list) else [fc_liga]:
        if isinstance(parte, dict) and clave in parte:
            return parte[clave]
    return {}


def clave_renovada(valor):
    """'428_12345' -> '428.l.12345'."""
    if not valor:
        return None
    m = re.fullmatch(r"(\d+)_(\d+)", str(valor))
    return f"{m.group(1)}.l.{m.group(2)}" if m else None


def leer_json(ruta, defecto):
    try:
        return json.loads(Path(ruta).read_text(encoding="utf-8"))
    except Exception:
        return defecto


def guardar(nombre, datos):
    """Escribe data/liga/<nombre> solo si cambia algo más que la fecha."""
    ruta = DIR_LIGA / nombre
    nuevo = json.dumps(datos, ensure_ascii=False, indent=1)
    viejo = leer_json(ruta, None)
    if viejo is not None:
        a = {k: v for k, v in viejo.items() if k != "actualizado"}
        b = {k: v for k, v in datos.items() if k != "actualizado"}
        if a == b:
            return
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(nuevo, encoding="utf-8")


def hoy_eeuu():
    """Fecha de hoy en la costa este de EE. UU. (la que usa Yahoo para las alineaciones)."""
    return (datetime.now(timezone.utc) - timedelta(hours=5)).date().isoformat()


# ---------------------------------------------------------------- liga
def comprobar_acceso(token):
    """Llamada pública: si da 403 'not authorized', Yahoo todavía no ha aprobado la app."""
    try:
        juego = fusionar(api(token, "game/nba")["game"])
    except ErrorAPI as e:
        if no_autorizada(e):
            print("⏳ Yahoo todavía no ha aprobado la app (403 'not authorized'). No se guarda nada.")
            sys.exit(0)
        fallo(f"Error inesperado al leer game/nba (HTTP {e.codigo}: {descripcion_error(e)}).")
    print(f"OK  Juego NBA actual: game_key {juego.get('game_key')}, temporada {juego.get('season')}")
    return juego


def buscar_liga(token, juego):
    """Clave de la liga de la temporada actual, sin depender de un ID fijo."""
    guardada = leer_json(DIR_LIGA / "liga.json", {}) or leer_json(DATA / "liga.json", {})
    temporada = str(juego.get("season"))

    # a) Cadena de renovaciones desde la última liga conocida
    clave = guardada.get("league_key")
    vistas = set()
    while clave and clave not in vistas:
        vistas.add(clave)
        try:
            meta = fusionar(api(token, f"league/{clave}")["league"])
        except ErrorAPI as e:
            print(f"AVISO  No pude leer la liga guardada {clave} (HTTP {e.codigo}).")
            break
        if str(meta.get("season")) == temporada:
            print(f"OK  Liga encontrada siguiendo las renovaciones: {meta.get('name')} ({clave})")
            return clave
        clave = clave_renovada(meta.get("renewed"))

    # b) Ligas NBA de la cuenta en la temporada actual
    try:
        fc = api(token, "users;use_login=1/games;game_keys=nba/leagues")
    except ErrorAPI as e:
        fallo(f"No puedo leer tus ligas (HTTP {e.codigo}: {descripcion_error(e)}).")
    ligas = []
    for u in elementos(fc.get("users", {}), "user"):
        for g in elementos(fusionar(u).get("games", {}), "game"):
            for lg in elementos(fusionar(g).get("leagues", {}), "league"):
                ligas.append(fusionar(lg))
    print(f"OK  La cuenta está en {len(ligas)} liga(s) NBA esta temporada:")
    for lg in ligas:
        print(f"      - {lg.get('name')}  (id {lg.get('league_id')}, clave {lg.get('league_key')})")

    if len(ligas) == 1:
        return ligas[0]["league_key"]
    for lg in ligas:
        if guardada.get("nombre") and lg.get("name") == guardada.get("nombre"):
            return lg["league_key"]
    for lg in ligas:
        if str(lg.get("league_id")) == LIGA_ID:
            return lg["league_key"]
    fallo("No sé cuál de tus ligas es la buena. Pon su ID en la variable LIGA_ID del workflow.")


def leer_settings(token, league_key):
    fc = api(token, f"league/{league_key}/settings")
    meta = fusionar(fc["league"][0])
    sets = fusionar(bloque(fc["league"], "settings"))

    posiciones = []
    for rp in sets.get("roster_positions", []):
        p = rp.get("roster_position", rp)
        posiciones.append({"posicion": p.get("position"), "huecos": int(p.get("count", 1))})

    categorias = []
    for st in sets.get("stat_categories", {}).get("stats", []):
        s = st.get("stat", st)
        if str(s.get("is_only_display_stat")) == "1":
            continue
        categorias.append({
            "id": str(s.get("stat_id")),
            "clave": STATS.get(str(s.get("stat_id"))),
            "nombre": s.get("display_name") or s.get("abbr") or s.get("name"),
            "menos_es_mejor": str(s.get("sort_order")) == "0",
        })

    liga = {
        "league_key": meta.get("league_key"),
        "nombre": meta.get("name"),
        "temporada": meta.get("season"),
        "num_equipos": meta.get("num_teams"),
        "semana_actual": meta.get("current_week"),
        "semana_inicio": meta.get("start_week"),
        "semana_fin": meta.get("end_week"),
        "fecha_inicio": meta.get("start_date"),
        "fecha_fin": meta.get("end_date"),
        "tipo_puntuacion": meta.get("scoring_type"),
        "renew": meta.get("renew"),
        "renewed": meta.get("renewed"),
        "url": meta.get("url"),
        "posiciones": posiciones,
        "categorias": categorias,
        "max_fichajes_temporada": sets.get("max_adds"),
        "max_fichajes_semana": sets.get("max_weekly_adds"),
        "playoffs_semana_inicio": sets.get("playoff_start_week"),
        "equipos_playoffs": sets.get("num_playoff_teams"),
        "fecha_limite_traspasos": sets.get("trade_end_date"),
    }
    return liga, fc


def datos_equipo(t):
    """Datos básicos de un equipo (sin emails)."""
    d = fusionar(t)
    managers = [fusionar(m).get("nickname") for m in elementos(d.get("managers", []), "manager")]
    logos = elementos(d.get("team_logos", []), "team_logo")
    return d, {
        "key": d.get("team_key"),
        "id": str(d.get("team_id")),
        "nombre": d.get("name"),
        "manager": ", ".join(m for m in managers if m and m != "--hidden--"),
        "logo": fusionar(logos[0]).get("url", "") if logos else "",
    }


def leer_equipos(token, league_key):
    fc = api(token, f"league/{league_key}/teams")
    return [datos_equipo(t)[1] for t in elementos(bloque(fc["league"], "teams"), "team")]


def leer_clasificacion(token, league_key):
    fc = api(token, f"league/{league_key}/standings")
    st = bloque(fc["league"], "standings")
    contenedor = st[0]["teams"] if isinstance(st, list) else st.get("teams", st)
    out = []
    for t in elementos(contenedor, "team"):
        d, info = datos_equipo(t)
        ts = d.get("team_standings", {})
        tot = ts.get("outcome_totals", {})
        out.append({"key": info["key"], "puesto": int(ts.get("rank") or 0),
                    "g": int(tot.get("wins") or 0), "p": int(tot.get("losses") or 0),
                    "e": int(tot.get("ties") or 0), "pct": tot.get("percentage"),
                    "detras": ts.get("games_back")})
    return sorted(out, key=lambda x: x["puesto"] or 99)


def estadisticas(team_stats):
    """[{'stat': {'stat_id': '5', 'value': '.475'}}] -> {'fg_pct': 0.475, 'fgm': .., 'fga': ..}"""
    out = {}
    for s in (team_stats or {}).get("stats", []):
        s = s.get("stat", s)
        k, v = STATS.get(str(s.get("stat_id"))), s.get("value")
        if not k or v in (None, "", "-"):
            continue
        if "/" in str(v):                                   # "245/520"
            a, b = str(v).split("/")
            n = "fg" if k == "fgm_fga" else "ft"
            out[n + "m"], out[n + "a"] = float(a or 0), float(b or 0)
        else:
            out[k] = float(v)
    return out


def leer_enfrentamientos(token, league_key, semana=None):
    ruta = f"league/{league_key}/scoreboard" + (f";week={semana}" if semana else "")
    sb = bloque(api(token, ruta)["league"], "scoreboard")
    sb = fusionar(sb) if isinstance(sb, list) else sb
    matchups = sb.get("0", {}).get("matchups", sb.get("matchups", {}))
    res = {"semana": None, "inicio": None, "fin": None, "partidos": []}
    for m in elementos(matchups, "matchup"):
        res["semana"] = res["semana"] or m.get("week")
        res["inicio"] = res["inicio"] or m.get("week_start")
        res["fin"] = res["fin"] or m.get("week_end")
        equipos = []
        for t in elementos(m.get("0", {}).get("teams", m.get("teams", {})), "team"):
            d, info = datos_equipo(t)
            equipos.append({"key": info["key"], "stats": estadisticas(d.get("team_stats")),
                            "puntos": (d.get("team_points") or {}).get("total")})
        res["partidos"].append({"estado": m.get("status"), "playoffs": str(m.get("is_playoffs")) == "1",
                                "equipos": equipos})
    return res


def datos_jugador(p):
    d = fusionar(p)
    nombre = d.get("name", {})
    eleg = [x.get("position") if isinstance(x, dict) else x
            for x in (d.get("eligible_positions") or [])]
    sel = fusionar(d.get("selected_position", []))
    abr = str(d.get("editorial_team_abbr") or "").upper()
    return {
        "yahoo_id": str(d.get("player_id")),
        "nombre": nombre.get("full") if isinstance(nombre, dict) else nombre,
        "equipo_nba": YAHOO_A_NBA.get(abr, abr),
        "pos": [x for x in eleg if x in ("PG", "SG", "SF", "PF", "C")],
        "hueco": sel.get("position"),                       # PG, SG, ..., Util, BN, IL
        "estado": d.get("status") or "",                    # INJ, O, GTD, DTD, NA...
        "lesion": d.get("injury_note") or "",
    }


def leer_plantillas(token, league_key, fecha):
    fc = api(token, f"league/{league_key}/teams/roster;date={fecha}")
    plantillas = {}
    for t in elementos(bloque(fc["league"], "teams"), "team"):
        d, info = datos_equipo(t)
        roster = d.get("roster", {})
        cont = roster.get("0", {}).get("players", roster.get("players", {}))
        plantillas[info["key"]] = [datos_jugador(p) for p in elementos(cont, "player")]
    return plantillas


def leer_libres(token, league_key):
    """Posiciones de Yahoo de los mejores agentes libres (por ranking real de Yahoo)."""
    libres = []
    for pag in range(LIBRES_PAGINAS):
        try:
            fc = api(token, f"league/{league_key}/players;status=A;sort=AR;start={pag * 25};count=25")
        except ErrorAPI as e:
            print(f"AVISO  Agentes libres, página {pag + 1}: HTTP {e.codigo}. Me quedo con {len(libres)}.")
            break
        lote = [datos_jugador(p) for p in elementos(bloque(fc["league"], "players"), "player")]
        libres += lote
        if len(lote) < 25:
            break
    return libres


# ---------------------------------------------------------------- enlace con la NBA
def enlazar_nba(jugadores_yahoo):
    """Añade 'nba_id' a cada jugador de Yahoo buscando por nombre (y equipo si hay duplicados)."""
    nba = leer_json(DATA / "nba" / "jugadores.json", {}).get("jugadores", [])
    por_nombre = {}
    for j in nba:
        por_nombre.setdefault(normalizar(j["nombre"]), []).append(j)
    sin = []
    for y in jugadores_yahoo:
        cand = por_nombre.get(normalizar(y["nombre"]), [])
        if len(cand) > 1:
            cand = [j for j in cand if j["equipo"] == y["equipo_nba"]]
        y["nba_id"] = cand[0]["id"] if len(cand) == 1 else None
        if not y["nba_id"]:
            sin.append(y["nombre"])
    return sin


# ---------------------------------------------------------------- principal
def main():
    token = obtener_token()
    juego = comprobar_acceso(token)
    league_key = buscar_liga(token, juego)
    try:
        liga, raw = leer_settings(token, league_key)
        liga["equipos"] = leer_equipos(token, league_key)
        clasif = leer_clasificacion(token, league_key)
        enfr = leer_enfrentamientos(token, league_key)
        fecha = hoy_eeuu()
        plantillas = leer_plantillas(token, league_key, fecha)
        libres = leer_libres(token, league_key)
    except ErrorAPI as e:
        fallo(f"HTTP {e.codigo} en {e.url}\n{descripcion_error(e)}")

    todos = [j for lista in plantillas.values() for j in lista] + libres
    sin = enlazar_nba(todos)
    ahora = datetime.now(timezone.utc).isoformat(timespec="seconds")

    guardar("liga.json", {**liga, "actualizado": ahora})
    guardar("clasificacion.json", {"equipos": clasif, "actualizado": ahora})
    guardar("enfrentamientos.json", {**enfr, "actualizado": ahora})
    guardar("plantillas.json", {"fecha": fecha, "equipos": plantillas, "actualizado": ahora})
    posiciones = {str(j["nba_id"]): ",".join(j["pos"]) for j in todos if j["nba_id"] and j["pos"]}
    guardar("posiciones.json", {"jugadores": dict(sorted(posiciones.items(), key=lambda kv: int(kv[0]))),
                                "actualizado": ahora})
    if not FIXTURES:
        (DATA / "raw").mkdir(parents=True, exist_ok=True)
        (DATA / "raw" / "settings.json").write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"OK  Liga: {liga['nombre']} ({liga['league_key']}, temporada {liga['temporada']}, "
          f"semana {liga['semana_actual']})")
    print(f"OK  {len(liga['equipos'])} equipos · {sum(len(v) for v in plantillas.values())} jugadores en plantillas "
          f"· {len(libres)} libres · {len(enfr['partidos'])} enfrentamientos (semana {enfr['semana']})")
    print("    Categorías:", ", ".join(c["nombre"] + (" (menos=mejor)" if c["menos_es_mejor"] else "")
                                       for c in liga["categorias"]))
    print("    Huecos:", ", ".join(f"{p['posicion']}x{p['huecos']}" for p in liga["posiciones"]))
    if sin:
        print(f"AVISO  {len(sin)} jugadores de Yahoo sin enlazar con la NBA (sin partidos esta temporada "
              f"o nombre distinto): {', '.join(sin[:20])}{' …' if len(sin) > 20 else ''}")


if __name__ == "__main__":
    main()
