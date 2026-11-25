"""
crear_fixtures.py · Respuestas FALSAS de Yahoo (mismo formato que la API) para probar
conexion.py y la web sin acceso a Yahoo.

Usa los jugadores reales de data/nba/jugadores.json repartidos en 12 equipos inventados.
Uso (desde la raíz del repo):
    python scripts/pruebas/crear_fixtures.py
    YAHOO_FIXTURES=scripts/pruebas/yahoo LIGA_SALIDA=data/liga_prueba python scripts/conexion.py
La web enseña esos datos de prueba abriéndola con ?prueba al final de la dirección.
"""

import json
import random
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
SALIDA = Path(__file__).resolve().parent / "yahoo"
GAME, LIGA = "466", "9972"
LK = f"{GAME}.l.{LIGA}"
NOMBRES = ["Grit & Grind", "Prueba Rías Baixas", "Prueba Lérez", "Prueba Peregrina", "Prueba Marín",
           "Prueba Poio", "Prueba Sanxenxo", "Prueba Cambados", "Prueba Vilagarcía", "Prueba Bueu",
           "Prueba Cangas", "Prueba Moaña"]
HUECOS = ["PG", "SG", "SF", "PF", "C", "Util", "Util", "Util"]
STAT_IDS = {"fg": "9004003", "fg_pct": "5", "ft": "9007006", "ft_pct": "8", "tpm": "10", "pts": "12",
            "reb": "15", "ast": "16", "stl": "17", "blk": "18", "to": "19"}
NBA_A_YAHOO = {"GSW": "GS", "NYK": "NY", "SAS": "SA", "NOP": "NO", "PHX": "PHO", "UTA": "Uta", "WAS": "Was"}


def lista(items, clave):
    d = {str(i): {clave: x} for i, x in enumerate(items)}
    d["count"] = len(items)
    return d


def escribir(ruta, contenido):
    nombre = "".join(c if c.isalnum() else "_" for c in ruta)
    while "__" in nombre:
        nombre = nombre.replace("__", "_")
    (SALIDA / (nombre.strip("_") + ".json")).write_text(
        json.dumps({"fantasy_content": contenido}, ensure_ascii=False), encoding="utf-8")


def meta_equipo(i):
    return [{"team_key": f"{LK}.t.{i + 1}"}, {"team_id": str(i + 1)}, {"name": NOMBRES[i]}, [],
            {"url": f"https://basketball.fantasysports.yahoo.com/nba/{LIGA}/{i + 1}"},
            {"team_logos": [{"team_logo": {"size": "large", "url": ""}}]},
            {"managers": [{"manager": {"manager_id": str(i + 1), "nickname": f"Mánager {i + 1}",
                                       "guid": "X", "email": "nunca@se.guarda"}}]}]


def jugador(j, hueco=None, eleg=None):
    pos = eleg or j["_pos"]
    d = [[{"player_key": f"{GAME}.p.{j['id']}"}, {"player_id": str(j["id"])},
          {"name": {"full": j["nombre"], "first": j["nombre"].split()[0], "last": j["nombre"].split()[-1]}},
          {"editorial_team_abbr": NBA_A_YAHOO.get(j["equipo"], j["equipo"].title() if len(j["equipo"]) == 3 else j["equipo"])},
          {"display_position": ",".join(pos)},
          {"eligible_positions": [{"position": p} for p in pos + ["G" if {"PG", "SG"} & set(pos) else "F", "Util"]]},
          *([{"status": j["_estado"]}] if j.get("_estado") else [])]]
    if hueco:
        d.append({"selected_position": [{"coverage_type": "date", "date": "FECHA"}, {"position": hueco}]})
    return d


def main():
    random.seed(7)
    SALIDA.mkdir(parents=True, exist_ok=True)
    nba = json.loads((RAIZ / "data/nba/jugadores.json").read_text())["jugadores"]
    cal = json.loads((RAIZ / "data/nba/calendario.json").read_text())["partidos"]
    for j in nba:
        p = (j.get("pos") or "SF").replace("G", "PG,SG").replace("F", "SF,PF") if len(j.get("pos") or "") == 1 else (j.get("pos") or "SF")
        j["_pos"] = p.split(",")
        j["_estado"] = random.choice(["", "", "", "", "", "", "", "", "GTD", "O", "INJ"])
    # Reparto tipo draft serpiente de los 168 mejores por valor de temporada
    buenos = sorted([j for j in nba if j["temporada"]["pj"] >= 3], key=lambda j: -j["temporada"]["valor"])[:168]
    equipos = [[] for _ in range(12)]
    for r in range(14):
        orden = range(12) if r % 2 == 0 else range(11, -1, -1)
        for i in orden:
            equipos[i].append(buenos[r * 12 + (i if r % 2 == 0 else 11 - i)])
    libres = sorted([j for j in nba if j not in buenos], key=lambda j: -j["temporada"]["valor"])[:60]

    hoy = (datetime.now(timezone.utc) - timedelta(hours=5)).date()
    lunes = hoy - timedelta(days=hoy.weekday())
    domingo = lunes + timedelta(days=6)
    semana = (lunes - date(2026, 10, 19)).days // 7 + 1

    escribir("game/nba", {"game": [{"game_key": GAME, "game_id": GAME, "name": "Basketball", "code": "nba",
                                     "season": "2026"}]})
    meta_liga = {"league_key": LK, "league_id": LIGA, "name": "NBA Pontevedresa (PRUEBA)",
                 "url": f"https://basketball.fantasysports.yahoo.com/nba/{LIGA}", "num_teams": 12,
                 "scoring_type": "head", "current_week": semana, "start_week": "1", "end_week": "22",
                 "start_date": "2026-10-19", "end_date": "2027-03-21", "season": "2026",
                 "renew": "454_1234", "renewed": ""}
    escribir(f"league/{LK}", {"league": [meta_liga]})
    escribir("users;use_login=1/games;game_keys=nba/leagues", {"users": lista([[
        {"guid": "X"}, {"games": lista([[{"game_key": GAME}, {"leagues": lista([[meta_liga]], "league")}]], "game")}
    ]], "user")})
    stats = [{"stat": {"stat_id": v, "enabled": "1", "name": k, "display_name": k.upper(),
                       "sort_order": "0" if k == "to" else "1",
                       **({"is_only_display_stat": "1"} if k in ("fg", "ft") else {})}}
             for k, v in STAT_IDS.items()]
    escribir(f"league/{LK}/settings", {"league": [meta_liga, {"settings": [{
        "draft_type": "live", "max_adds": "", "max_weekly_adds": "5", "playoff_start_week": "20",
        "num_playoff_teams": "6", "trade_end_date": "2027-02-26",
        "roster_positions": [{"roster_position": {"position": p, "position_type": "P", "count": c}}
                             for p, c in [("PG", 1), ("SG", 1), ("SF", 1), ("PF", 1), ("C", 1), ("Util", 3),
                                          ("BN", 6), ("IL", 1)]],
        "stat_categories": {"stats": stats}}]}]})
    escribir(f"league/{LK}/teams", {"league": [meta_liga, {"teams": lista([[meta_equipo(i)] for i in range(12)], "team")}]})

    # Plantillas de hoy: 8 titulares (los mejores), resto banquillo, un lesionado en IL
    eq_bloques = []
    for i, plant in enumerate(equipos):
        jug = []
        for n, j in enumerate(plant):
            hueco = HUECOS[n] if n < 8 else ("IL" if n == 13 else "BN")
            jug.append({"player": jugador(j, hueco)})
        roster = {"coverage_type": "date", "date": hoy.isoformat(), "0": {"players": {**{str(k): v for k, v in enumerate(jug)}, "count": len(jug)}}}
        eq_bloques.append([meta_equipo(i), {"roster": roster}])
    escribir(f"league/{LK}/teams/roster;date=FECHA", {"league": [meta_liga, {"teams": lista(eq_bloques, "team")}]})

    # Agentes libres
    for pag in range(8):
        lote = libres[pag * 25:(pag + 1) * 25]
        escribir(f"league/{LK}/players;status=A;sort=AR;start={pag * 25};count=25",
                 {"league": [meta_liga, {"players": lista([jugador(j) for j in lote], "player")}]})
        if len(lote) < 25:
            break

    # Clasificación
    recs = [(random.randint(10, 60), random.randint(10, 60)) for _ in range(12)]
    ordenados = sorted(range(12), key=lambda i: -(recs[i][0] / (recs[i][0] + recs[i][1])))
    escribir(f"league/{LK}/standings", {"league": [meta_liga, {"standings": [{"teams": lista([[
        meta_equipo(i), {"team_standings": {"rank": str(ordenados.index(i) + 1),
                                            "outcome_totals": {"wins": str(recs[i][0]), "losses": str(recs[i][1]),
                                                               "ties": "2", "percentage": f"{recs[i][0] / (recs[i][0] + recs[i][1]):.3f}"},
                                            "games_back": "-"}}] for i in range(12)], "team")}]}]})

    # Enfrentamientos: estadísticas de la semana hasta ayer (partidos terminados x promedios)
    def stats_semana(plant):
        tot = {k: 0.0 for k in ("fgm", "fga", "ftm", "fta", "tpm", "pts", "reb", "ast", "stl", "blk", "to")}
        for j in plant[:8]:
            n = sum(1 for g in cal if lunes.isoformat() <= g["fecha"] < hoy.isoformat()
                    and j["equipo"] in (g["local"], g["visitante"]) and g["estado"] == 3)
            s = j["temporada"]
            for k in ("tpm", "pts", "reb", "ast", "stl", "blk", "to"):
                tot[k] += n * s[k] * random.uniform(.7, 1.3)
            tot["fga"] += n * s["fga"]; tot["fgm"] += n * s["fga"] * s["fg_pct"] * random.uniform(.9, 1.1)
            tot["fta"] += n * s["fta"]; tot["ftm"] += n * s["fta"] * s["ft_pct"] * random.uniform(.9, 1.1)
        out = [{"stat": {"stat_id": "9004003", "value": f"{round(tot['fgm'])}/{round(tot['fga'])}"}},
               {"stat": {"stat_id": "5", "value": f"{tot['fgm'] / tot['fga']:.3f}" if tot["fga"] else ""}},
               {"stat": {"stat_id": "9007006", "value": f"{round(tot['ftm'])}/{round(tot['fta'])}"}},
               {"stat": {"stat_id": "8", "value": f"{tot['ftm'] / tot['fta']:.3f}" if tot["fta"] else ""}}]
        out += [{"stat": {"stat_id": STAT_IDS[k], "value": str(round(tot[k]))}}
                for k in ("tpm", "pts", "reb", "ast", "stl", "blk", "to")]
        return {"coverage_type": "week", "week": str(semana), "stats": out}

    cruces = [(0, 5), (1, 2), (3, 4), (6, 7), (8, 9), (10, 11)]
    mats = []
    for a, b in cruces:
        mats.append({"week": str(semana), "week_start": lunes.isoformat(), "week_end": domingo.isoformat(),
                     "status": "midevent", "is_playoffs": "0",
                     "0": {"teams": lista([[meta_equipo(i), {"team_stats": stats_semana(equipos[i]),
                                                              "team_points": {"coverage_type": "week", "total": "4"}}]
                                           for i in (a, b)], "team")}})
    escribir(f"league/{LK}/scoreboard", {"league": [meta_liga, {"scoreboard": {"week": str(semana),
                                                                              "0": {"matchups": lista(mats, "matchup")}}}]})
    print(f"OK  Respuestas de prueba en {SALIDA} (semana {semana}: {lunes} a {domingo}).")


if __name__ == "__main__":
    main()
