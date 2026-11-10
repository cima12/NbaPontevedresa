"""
nba.py · NbaPontevedresa · Datos públicos de la NBA (no necesita Yahoo).

Descarga de la CDN pública de la NBA el calendario y las estadísticas de cada
partido terminado, y genera en data/nba/:
  calendario.json      -> todos los partidos de temporada regular
  lineas/AAAA-MM.json  -> estadísticas partido a partido (caché por meses: solo baja lo nuevo)
  nombres.json         -> id de jugador -> nombre
  jugadores.json       -> promedios y valor 9-cat: temporada y últimos 7/14/30 días
  semanas.json         -> partidos de cada equipo por semana (lunes a domingo)

Solo reescribe un archivo si su contenido ha cambiado (para no inflar el repositorio).
Solo usa la librería estándar de Python.
"""

import http.client
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import valor

URL_CALENDARIO = "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json"
URL_BOX = "https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{}.json"
MAX_PARTIDOS_POR_EJECUCION = 400
PAUSA = 0.25
REINTENTOS = 3          # intentos por descarga antes de rendirse
ESPERAS = (5, 20)       # segundos de espera entre intentos
DIA_LIGERO = 7          # días con 7 partidos NBA o menos

RAIZ = Path(__file__).resolve().parent.parent
DIR = RAIZ / "data" / "nba"

COLS = ["jugador", "equipo", "rival", "fecha", "min", "fgm", "fga", "ftm", "fta",
        "tpm", "pts", "reb", "ast", "stl", "blk", "to"]

CABECERAS = {
    "User-Agent": "Mozilla/5.0 (NbaPontevedresa; uso personal)",
    "Accept": "application/json",
    "Referer": "https://www.nba.com/",
}


# ---------------------------------------------------------------- utilidades
def fallo(msg):
    print("ERROR:", msg)
    sys.exit(1)


# Fallos de red pasajeros (la CDN de la NBA a veces corta, tarda o devuelve error)
ERRORES_RED = (urllib.error.URLError, TimeoutError, ConnectionError,
               http.client.HTTPException, OSError, json.JSONDecodeError)


def descargar(url, reintentos=REINTENTOS):
    """Descarga un JSON; si falla por un problema pasajero, espera y lo vuelve a intentar."""
    for intento in range(1, reintentos + 1):
        try:
            req = urllib.request.Request(url, headers=CABECERAS)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404 or intento == reintentos:   # 404 = no existe: no insistir
                raise
            error = e
        except ERRORES_RED as e:
            if intento == reintentos:
                raise
            error = e
        espera = ESPERAS[min(intento - 1, len(ESPERAS) - 1)]
        print(f"AVISO  Intento {intento} fallido ({error}). Reintento en {espera} s…")
        time.sleep(espera)


def leer_json(ruta, defecto):
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return defecto


def _sin_fecha(d):
    return {k: v for k, v in d.items() if k != "actualizado"} if isinstance(d, dict) else d


def guardar(ruta, datos):
    """Escribe en formato compacto solo si el contenido (sin 'actualizado') ha cambiado."""
    if ruta.exists() and _sin_fecha(leer_json(ruta, None)) == _sin_fecha(datos):
        return False
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return True


def hoy_eeuu():
    return (datetime.now(timezone.utc) - timedelta(hours=5)).date()   # hora aprox. de Nueva York


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
        ls = raw["leagueSchedule"]
    except (*ERRORES_RED, KeyError, TypeError) as e:
        # Plan B: usar el calendario guardado en la última ejecución buena
        guardado = leer_json(DIR / "calendario.json", None)
        if not guardado or not guardado.get("partidos"):
            fallo(f"No se pudo descargar el calendario de la NBA y no hay copia guardada: {e}")
        print(f"AVISO  No se pudo descargar el calendario ({e}). Uso la copia guardada.")
        return guardado.get("temporada"), guardado["partidos"]

    partidos = []
    for dia in ls.get("gameDates", []):
        for g in dia.get("games", []):
            gid = g.get("gameId", "")
            if not gid.startswith("002"):          # solo temporada regular
                continue
            partidos.append({
                "id": gid,
                "fecha": (g.get("gameDateEst") or "")[:10],
                "hora_utc": g.get("gameDateTimeUTC"),
                "local": g["homeTeam"].get("teamTricode"),
                "visitante": g["awayTeam"].get("teamTricode"),
                "estado": g.get("gameStatus"),     # 1 pendiente, 2 en juego, 3 final
            })
    partidos.sort(key=lambda p: (p["fecha"], p["hora_utc"] or "", p["id"]))
    return ls.get("seasonYear"), partidos


# ---------------------------------------------------------------- caché de líneas
def cargar_cache():
    partidos = {}
    for f in sorted((DIR / "lineas").glob("*.json")):
        partidos.update(leer_json(f, {}).get("partidos", {}))
    nombres = leer_json(DIR / "nombres.json", {})

    antiguo = DIR / "lineas.json"            # formato de la primera versión: se migra
    if antiguo.exists():
        viejo = leer_json(antiguo, {})
        partidos.update(viejo.get("partidos", {}))
        nombres.update(viejo.get("nombres", {}))
        antiguo.unlink()
        print("OK  Migrado lineas.json al nuevo formato por meses.")
    return {"partidos": partidos, "nombres": nombres}


def guardar_cache(cache, fechas):
    por_mes = {}
    for gid, lineas in cache["partidos"].items():
        mes = fechas.get(gid, lineas[0][3] if lineas else "0000-00")[:7]
        por_mes.setdefault(mes, {})[gid] = lineas
    for mes, partidos in por_mes.items():
        guardar(DIR / "lineas" / f"{mes}.json",
                {"columnas": COLS, "partidos": dict(sorted(partidos.items()))})
    guardar(DIR / "nombres.json", dict(sorted(cache["nombres"].items(), key=lambda kv: int(kv[0]))))


def leer_box(gid, fecha):
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
        except (*ERRORES_RED, KeyError, TypeError) as e:
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


# ---------------------------------------------------------------- promedios y valor
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

    hoy = hoy_eeuu()
    cortes = {d: (hoy - timedelta(days=d)).isoformat() for d in (7, 14, 30)}
    jugadores = []
    for pid, lineas in por_jugador.items():
        lineas.sort(key=lambda l: l[3])
        j = {
            "id": int(pid),
            "nombre": cache["nombres"].get(pid, pid),
            "equipo": lineas[-1][1],
            "ultimo_partido": lineas[-1][3],
            "temporada": acumular(lineas),
        }
        for d, corte in cortes.items():
            rec = [l for l in lineas if l[3] > corte]
            j[f"ult{d}"] = acumular(rec) if rec else None
        jugadores.append(j)

    # Partidos mínimos para entrar en el ranking de cada periodo
    max_pj = max((j["temporada"]["pj"] for j in jugadores), default=0)
    minimos = {"temporada": max(3, round(max_pj * 0.3)), "ult7": 2, "ult14": 3,
               "ult30": max(3, round(min(max_pj, 15) * 0.3))}
    for ventana, pj_min in minimos.items():
        n = valor.calcular(jugadores, ventana, pj_min)
        print(f"OK  Valor 9-cat '{ventana}': {n} jugadores elegibles (mín. {pj_min} PJ).")

    jugadores.sort(key=lambda j: -(j["temporada"].get("valor") or -99))
    return jugadores, minimos


# ---------------------------------------------------------------- semanas
def calcular_semanas(calendario):
    por_dia = {}
    for p in calendario:
        por_dia[p["fecha"]] = por_dia.get(p["fecha"], 0) + 1

    semanas = {}
    for p in calendario:
        d = date.fromisoformat(p["fecha"])
        lunes = (d - timedelta(days=d.weekday())).isoformat()
        s = semanas.setdefault(lunes, {"inicio": lunes,
                                       "fin": (date.fromisoformat(lunes) + timedelta(days=6)).isoformat(),
                                       "equipos": {}, "por_dia": {}})
        s["por_dia"][p["fecha"]] = por_dia[p["fecha"]]
        ligero = por_dia[p["fecha"]] <= DIA_LIGERO
        for eq in (p["local"], p["visitante"]):
            e = s["equipos"].setdefault(eq, {"p": 0, "lig": 0, "dias": []})
            e["p"] += 1
            e["lig"] += ligero
            e["dias"].append(d.weekday())          # 0 = lunes
    return {"dia_ligero_max": DIA_LIGERO, "semanas": [semanas[k] for k in sorted(semanas)]}


# ---------------------------------------------------------------- principal
def main():
    temporada, calendario = leer_calendario()
    jugados = sum(1 for p in calendario if p["estado"] == 3)
    print(f"OK  Calendario {temporada}: {len(calendario)} partidos de temporada regular ({jugados} terminados).")

    cache = cargar_cache()
    nuevos, errores, quedan = actualizar_lineas(calendario, cache)
    print(f"OK  Box scores: {nuevos} partidos nuevos, {len(cache['partidos'])} en total"
          + (f", {errores} con error" if errores else "")
          + (f". Quedan {quedan} para la próxima ejecución." if quedan else "."))
    if errores and not cache["partidos"]:
        fallo("No se ha podido descargar ningún box score. Puede que la NBA bloquee a GitHub.")

    jugadores, minimos = calcular_jugadores(cache)
    ahora = datetime.now(timezone.utc).isoformat(timespec="seconds")

    guardar_cache(cache, {p["id"]: p["fecha"] for p in calendario})
    guardar(DIR / "calendario.json", {"temporada": temporada, "partidos": calendario})
    guardar(DIR / "semanas.json", calcular_semanas(calendario))
    cambio = guardar(DIR / "jugadores.json", {
        "temporada": temporada, "actualizado": ahora, "hoy_eeuu": hoy_eeuu().isoformat(),
        "categorias": valor.CATEGORIAS, "pj_minimos": minimos, "jugadores": jugadores,
    })

    print(f"OK  {len(jugadores)} jugadores." + ("" if cambio else " (Sin cambios desde la última vez.)"))
    print("\n--- Comprobación: top 10 por valor 9-cat (temporada) ---")
    for j in [j for j in jugadores if j["temporada"].get("elegible")][:10]:
        t = j["temporada"]
        print(f"  {j['nombre']:<26} {j['equipo']}  {t['pj']:>2} PJ  valor {t['valor']:>6}  "
              f"{t['pts']:>5} pts {t['reb']:>4} reb {t['ast']:>4} ast")
    print("\nGuardado en data/nba/")


if __name__ == "__main__":
    main()
