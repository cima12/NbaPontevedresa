"""
perfiles.py · NbaPontevedresa · Posición y fecha de nacimiento de cada jugador.

La CDN de la NBA no da ni posición ni edad, así que se leen de las plantillas
públicas de ESPN (30 consultas, una por equipo) y se guardan en
data/nba/perfiles.json:

  {"actualizado": "...", "fuente": "ESPN",
   "jugadores": {"<id NBA>": {"pos": "PG", "nac": "2001-05-12"}}}

Se enlazan con los ids de la NBA por nombre (sin acentos ni sufijos Jr./III) y equipo.
Los jugadores que ya no aparecen en ninguna plantilla conservan su dato anterior.
Si ESPN falla, se mantiene el archivo anterior y no se para nada.

Cuando haya acceso a Yahoo, la posición oficial de Yahoo (elegibilidad, p. ej.
"PG,SG") se añadirá como "pos_yahoo" y la web la preferirá a la de ESPN.
"""

import json
import re
import time
import unicodedata
import urllib.request
from datetime import datetime, timezone

URL_EQUIPOS = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams"
URL_PLANTILLA = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{}/roster"
CABECERAS = {"User-Agent": "Mozilla/5.0 (NbaPontevedresa; uso personal)", "Accept": "application/json"}
PAUSA = 0.3

# Abreviaturas de ESPN que no coinciden con las de la NBA
ESPN_A_NBA = {"GS": "GSW", "NY": "NYK", "SA": "SAS", "NO": "NOP", "UTAH": "UTA", "WSH": "WAS"}
SUFIJOS = {"jr", "sr", "ii", "iii", "iv", "v"}


def _get(url):
    ultimo = None
    for intento in range(3):
        try:
            req = urllib.request.Request(url, headers=CABECERAS)
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:          # cualquier fallo de red o de formato
            ultimo = e
            time.sleep(3 * (intento + 1))
    raise ultimo


def normalizar(nombre):
    """'Nikola Jokić' -> 'nikola jokic'; 'Jaren Jackson Jr.' -> 'jaren jackson'."""
    t = unicodedata.normalize("NFKD", nombre or "").encode("ascii", "ignore").decode().lower()
    t = re.sub(r"[^a-z ]", "", t.replace("-", " "))
    partes = [p for p in t.split() if p not in SUFIJOS]
    return " ".join(partes)


def leer_espn():
    """Devuelve lista de {nombre, equipo, pos, nac} de todas las plantillas."""
    raw = _get(URL_EQUIPOS)
    equipos = [t["team"] for t in raw["sports"][0]["leagues"][0]["teams"]]
    out = []
    for eq in equipos:
        abr = ESPN_A_NBA.get(eq.get("abbreviation"), eq.get("abbreviation"))
        try:
            plant = _get(URL_PLANTILLA.format(eq["id"]))
        except Exception as e:
            print(f"AVISO  ESPN: no se pudo leer la plantilla de {abr}: {e}")
            continue
        atletas = plant.get("athletes", [])
        if atletas and isinstance(atletas[0], dict) and "items" in atletas[0]:   # formato agrupado
            atletas = [a for grupo in atletas for a in grupo.get("items", [])]
        for a in atletas:
            out.append({
                "nombre": a.get("fullName") or a.get("displayName") or "",
                "equipo": abr,
                "pos": (a.get("position") or {}).get("abbreviation") or None,
                "nac": (a.get("dateOfBirth") or "")[:10] or None,
            })
        time.sleep(PAUSA)
    return out


def enlazar(jugadores, espn):
    """Empareja cada jugador NBA (id, nombre, equipo) con su ficha de ESPN."""
    por_nombre, por_apellido = {}, {}
    for e in espn:
        n = normalizar(e["nombre"])
        por_nombre.setdefault(n, []).append(e)
        if n:
            por_apellido.setdefault((n.split()[-1], e["equipo"]), []).append(e)

    res, sin = {}, []
    for j in jugadores:
        n = normalizar(j["nombre"])
        cand = por_nombre.get(n, [])
        if len(cand) > 1:                                   # mismo nombre: decide el equipo
            cand = [e for e in cand if e["equipo"] == j["equipo"]]
        if not cand and n:                                  # 'Herb Jones' / 'Herbert Jones'
            cand = por_apellido.get((n.split()[-1], j["equipo"]), [])
            cand = [e for e in cand if normalizar(e["nombre"])[:1] == n[:1]]
        if len(cand) == 1:
            res[str(j["id"])] = {"pos": cand[0]["pos"], "nac": cand[0]["nac"]}
        else:
            sin.append(j)
    return res, sin


def actualizar(jugadores, ruta, leer_json, guardar):
    """Actualiza perfiles.json y devuelve el diccionario id -> perfil. Nunca para el proceso."""
    previo = leer_json(ruta, {}).get("jugadores", {})
    try:
        espn = leer_espn()
        if len(espn) < 300:
            raise ValueError(f"solo {len(espn)} jugadores en las plantillas")
    except Exception as e:
        print(f"AVISO  No se pudieron leer posiciones/edades de ESPN ({e}). Uso las guardadas ({len(previo)}).")
        return previo

    nuevos, sin = enlazar(jugadores, espn)
    perfiles = dict(previo)
    for pid, p in nuevos.items():
        perfiles[pid] = {**perfiles.get(pid, {}), **{k: v for k, v in p.items() if v}}
    guardar(ruta, {"actualizado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "fuente": "ESPN", "jugadores": dict(sorted(perfiles.items(), key=lambda kv: int(kv[0])))})

    print(f"OK  Perfiles: {len(nuevos)} de {len(jugadores)} jugadores enlazados con ESPN.")
    faltan = [j for j in sin if str(j["id"]) not in perfiles]
    if faltan:
        print(f"AVISO  {len(faltan)} jugadores sin posición/edad: "
              + ", ".join(f"{j['nombre']} ({j['equipo']})" for j in faltan[:25])
              + (" …" if len(faltan) > 25 else ""))
    return perfiles
