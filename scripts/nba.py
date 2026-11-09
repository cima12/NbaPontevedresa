"""
nba.py · NbaPontevedresa · Datos públicos de la NBA (no necesita Yahoo).

Descarga de la CDN pública de la NBA:
  - el calendario de la temporada regular
  - las estadísticas de cada jugador en cada partido ya terminado
y genera:
  data/nba/calendario.json   -> todos los partidos (fecha EE. UU., equipos, estado)
  data/nba/lineas.json       -> estadísticas partido a partido (caché: solo baja lo nuevo)
  data/nba/jugadores.json    -> promedios por jugador: temporada y últimos 7/14/30 días

Solo usa la librería estándar de Python.
"""

import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

URL_CALENDARIO = "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json"
URL_BOX = "https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{}.json"
MAX_PARTIDOS_POR_EJECUCION = 400   # la primera vez baja todo lo jugado; luego solo lo nuevo
PAUSA = 0.25                       # segundos entre descargas, para no abusar

RAIZ = Path(__file__).resolve().parent.parent
DIR = RAIZ / "data" / "nba"

# Orden de las columnas de cada línea en lineas.json
COLS = ["jugador", "equipo", "rival", "fecha", "min", "fgm", "fga", "ftm", "fta",
        "tpm", "pts", "reb", "ast", "stl", "blk", "to"]

CABECERAS = {
    "User-Agent": "Mozilla/5.0 (NbaPontevedresa; uso personal)",
    "Accept": "application/json",
    "Referer": "https://www.nba.com/",
}


def fallo(msg):
    print("ERROR:", msg)
    sys.exit(1)


def descargar(url):
    req = urllib.request.Request(url, headers=CABECERAS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def leer_json(ruta, defecto):
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return defecto


def guardar(ruta, datos, compacto=False):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    if compacto:
        texto = json.dumps(datos, ensure_ascii=False, separators=(",", ":"))
    else:
        texto = json.dumps(datos, ensure_ascii=False, indent=1)
    ruta.write_text(texto, encoding="utf-8")


def minutos(texto):
    """'PT32M10.00S' -> 32.2"""
    if not texto or not texto.startswith("PT"):
        return 0.0
    try:
        m, s = texto[2:].rstrip("S").split("M")
        return round(int(m) + float(s or 0) / 60, 1)
    except ValueError:
        return 0.0


# ---------------------------------------------------------------- calendario
def leer_calendario():
    try:
        raw = descargar(URL_CALENDARIO)
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        fallo(f"No se pudo descargar el calendario de la NBA: {e}")

    ls = raw["leagueSchedule"]
    partidos = []
    for dia in ls.get("gameDates", []):
        for g in dia.get("games", []):
            gid = g.get("gameId", "")
            if not gid.startswith("002"):          # solo temporada regular
                continue
            partidos.append({
                "id": gid,
                "fecha": (g.get("gameDateEst") or "")[:10],       # día EE. UU. (el que usa Yahoo)
                "hora_utc": g.get("gameDateTimeUTC"),
                "local": g["homeTeam"].get("teamTricode"),
                "visitante": g["awayTeam"].get("teamTricode"),
                "estado": g.get("gameStatus"),                     # 1 pendiente, 2 en juego, 3 final
            })
    partidos.sort(key=lambda p: (p["fecha"], p["hora_utc"] or "", p["id"]))
    return ls.get("seasonYear"), partidos


# ---------------------------------------------------------------- box scores
def leer_box(gid, fecha):
    """Devuelve (lineas, nombres) de un partido terminado, o None si aún no está final."""
    g = descargar(URL_BOX.format(gid))["game"]
    if g.get("gameStatus") != 3:
        return None
    lineas, nombres = [], {}
    for lado, otro in (("homeTeam", "awayTeam"), ("awayTeam", "homeTeam")):
        eq, rival = g[lado].get("teamTricode"), g[otro].get("teamTricode")
        for p in g[lado].get("players", []):
            if p.get("played") != "1":
                continue
            s = p.get("statistics", {})
            pid = p.get("personId")
            nombres[str(pid)] = p.get("name") or f"{p.get('firstName', '')} {p.get('familyName', '')}".strip()
            lineas.append([
                pid, eq, rival, fecha, minutos(s.get("minutes")),
                s.get("fieldGoalsMade", 0), s.get("fieldGoalsAttempted", 0),
                s.get("freeThrowsMade", 0), s.get("freeThrowsAttempted", 0),
                s.get("threePointersMade", 0), s.get("points", 0),
                s.get("reboundsTotal", 0), s.get("assists", 0),
                s.get("steals", 0), s.get("blocks", 0), s.get("turnovers", 0),
            ])
    return lineas, nombres


def actualizar_lineas(calendario, cache):
    hoy = datetime.now(timezone.utc).date().isoformat()
    pendientes = [p for p in calendario
                  if p["id"] not in cache["partidos"] and p["fecha"] <= hoy and p["estado"] != 1]
    nuevos, errores = 0, 0
    for p in pendientes[:MAX_PARTIDOS_POR_EJECUCION]:
        try:
            res = leer_box(p["id"], p["fecha"])
        except (urllib.error.URLError, json.JSONDecodeError, KeyError) as e:
            errores += 1
            print(f"AVISO  No se pudo leer el partido {p['id']} ({p['visitante']}@{p['local']}): {e}")
            continue
        if res is None:
            continue
        lineas, nombres = res
        cache["partidos"][p["id"]] = lineas
        cache["nombres"].update(nombres)
        nuevos += 1
        time.sleep(PAUSA)
    quedan = max(0, len(pendientes) - MAX_PARTIDOS_POR_EJECUCION)
    return nuevos, errores, quedan


# ---------------------------------------------------------------- promedios
def acumular(lineas):
    t = {"pj": 0, "min": 0.0, "fgm": 0, "fga": 0, "ftm": 0, "fta": 0,
         "tpm": 0, "pts": 0, "reb": 0, "ast": 0, "stl": 0, "blk": 0, "to": 0}
    for l in lineas:
        d = dict(zip(COLS, l))
        t["pj"] += 1
        for k in t:
            if k != "pj":
                t[k] += d[k]
    pj = t["pj"] or 1
    return {
        "pj": t["pj"],
        "min": round(t["min"] / pj, 1),
        "fg_pct": round(t["fgm"] / t["fga"], 3) if t["fga"] else None,
        "fga": round(t["fga"] / pj, 1),
        "ft_pct": round(t["ftm"] / t["fta"], 3) if t["fta"] else None,
        "fta": round(t["fta"] / pj, 1),
        **{k: round(t[k] / pj, 1) for k in ("tpm", "pts", "reb", "ast", "stl", "blk", "to")},
    }


def calcular_jugadores(cache):
    por_jugador = {}
    for lineas in cache["partidos"].values():
        for l in lineas:
            por_jugador.setdefault(str(l[0]), []).append(l)

    hoy = datetime.now(timezone.utc).date()
    cortes = {d: (hoy - timedelta(days=d)).isoformat() for d in (7, 14, 30)}
    jugadores = []
    for pid, lineas in por_jugador.items():
        lineas.sort(key=lambda l: l[3])
        j = {
            "id": int(pid),
            "nombre": cache["nombres"].get(pid, pid),
            "equipo": lineas[-1][1],                      # equipo del último partido
            "ultimo_partido": lineas[-1][3],
            "temporada": acumular(lineas),
        }
        for d, corte in cortes.items():
            rec = [l for l in lineas if l[3] > corte]
            j[f"ult{d}"] = acumular(rec) if rec else None
        jugadores.append(j)
    jugadores.sort(key=lambda j: -j["temporada"]["pts"])
    return jugadores


# ---------------------------------------------------------------- principal
def main():
    temporada, calendario = leer_calendario()
    jugados = sum(1 for p in calendario if p["estado"] == 3)
    print(f"OK  Calendario {temporada}: {len(calendario)} partidos de temporada regular ({jugados} terminados).")

    cache = leer_json(DIR / "lineas.json", {"columnas": COLS, "partidos": {}, "nombres": {}})
    cache["columnas"] = COLS
    nuevos, errores, quedan = actualizar_lineas(calendario, cache)
    print(f"OK  Box scores: {nuevos} partidos nuevos descargados, {len(cache['partidos'])} en total"
          + (f", {errores} con error" if errores else "")
          + (f". Quedan {quedan} para la próxima ejecución." if quedan else "."))
    if errores and not nuevos and not cache["partidos"]:
        fallo("No se ha podido descargar ningún box score. Puede que la NBA bloquee a GitHub.")

    jugadores = calcular_jugadores(cache)
    ahora = datetime.now(timezone.utc).isoformat(timespec="seconds")

    guardar(DIR / "calendario.json", {"temporada": temporada, "actualizado": ahora, "partidos": calendario})
    guardar(DIR / "lineas.json", cache, compacto=True)
    guardar(DIR / "jugadores.json", {"temporada": temporada, "actualizado": ahora, "jugadores": jugadores})

    print(f"OK  {len(jugadores)} jugadores con estadísticas.")
    print("\n--- Comprobación: máximos anotadores (mín. 5 partidos) ---")
    top = [j for j in jugadores if j["temporada"]["pj"] >= 5][:8]
    for j in top:
        t = j["temporada"]
        print(f"  {j['nombre']:<26} {j['equipo']}  {t['pj']:>2} PJ  {t['pts']:>5} pts  "
              f"{t['reb']:>4} reb  {t['ast']:>4} ast  FG {t['fg_pct']}")

    hoy = (datetime.now(timezone.utc) - timedelta(hours=5)).date().isoformat()  # hora aprox. de Nueva York
    hoy_partidos = [p for p in calendario if p["fecha"] == hoy]
    print(f"\nPartidos hoy ({hoy}, día EE. UU.): {len(hoy_partidos)}")
    print("\nGuardado en data/nba/")


if __name__ == "__main__":
    main()
