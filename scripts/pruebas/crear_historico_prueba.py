"""
crear_historico_prueba.py · Histórico INVENTADO (6 temporadas) para probar la ficha de
jugador de la web sin datos de Yahoo. Escribe en data/historico_prueba/ con el mismo
formato que historico.py y después construye el índice de jugadores.

Uso (desde la raíz):  python scripts/pruebas/crear_historico_prueba.py
Requiere antes data/liga_prueba/ (crear_fixtures.py + conexion.py con YAHOO_FIXTURES).
"""

import json
import os
import random
import shutil
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
SALIDA = RAIZ / "data" / "historico_prueba"
TEMPORADAS = [2021, 2022, 2023, 2024, 2025, 2026]
GAMES = {2021: "410", 2022: "418", 2023: "428", 2024: "441", 2025: "454", 2026: "466"}
APODOS = ["Old School", "Tiburones", "Los del Puerto", "Galácticos", "Mareas", "Furia"]
CATS = [("fg_pct", "FG%", False), ("ft_pct", "FT%", False), ("tpm", "3PTM", False), ("pts", "PTS", False),
        ("reb", "REB", False), ("ast", "AST", False), ("stl", "ST", False), ("blk", "BLK", False), ("to", "TO", True)]
MEDIAS = {"fga": (400, 35), "fg_pct": (.47, .02), "fta": (100, 15), "ft_pct": (.78, .035), "tpm": (60, 10),
          "pts": (500, 50), "reb": (200, 25), "ast": (115, 18), "stl": (32, 6), "blk": (22, 6), "to": (60, 9)}


def stats_semana(fuerza):
    s = {}
    for k, (m, d) in MEDIAS.items():
        v = random.gauss(m + fuerza.get(k, 0) * d, d)
        s[k] = round(v, 3) if k.endswith("pct") else max(0, round(v))
    s["fgm"], s["ftm"] = round(s["fga"] * s["fg_pct"]), round(s["fta"] * s["ft_pct"])
    s["fg_pct"], s["ft_pct"] = round(s["fgm"] / s["fga"], 3), round(s["ftm"] / s["fta"], 3)
    return s


def resultado(sa, sb):
    ga = gb = 0
    for k, _, menos in CATS:
        if sa[k] != sb[k]:
            if (sa[k] < sb[k]) == menos:
                ga += 1
            else:
                gb += 1
    return ga, gb


def semanas_temporada(key, n_reg, con_playoffs):
    """Calendario liga (método del círculo) + playoffs de 4. Devuelve (semanas, puestos)."""
    fuerza = {i: {k: random.gauss(0, .5) for k in MEDIAS} for i in range(12)}
    rec = {i: [0, 0, 0] for i in range(12)}
    semanas, ids = [], list(range(12))
    for w in range(n_reg):
        r = w % 11
        rot = [ids[0]] + ids[1:][r:] + ids[1:][:r]
        pares = [(rot[i], rot[11 - i]) for i in range(6)]
        partidos = []
        for a, b in pares:
            sa, sb = stats_semana(fuerza[a]), stats_semana(fuerza[b])
            ga, gb = resultado(sa, sb)
            rec[a][0 if ga > gb else 1 if ga < gb else 2] += 1
            rec[b][0 if gb > ga else 1 if gb < ga else 2] += 1
            partidos.append({"estado": "postevent", "playoffs": False, "consolacion": False,
                             "equipos": [{"key": key(a), "stats": sa}, {"key": key(b), "stats": sb}]})
        semanas.append({"semana": w + 1, "partidos": partidos})
    orden = sorted(range(12), key=lambda i: (-(rec[i][0] + rec[i][2] / 2), random.random()))
    puestos = {i: None for i in range(12)}
    if con_playoffs:
        def jugar(a, b, cons=False):
            sa, sb = stats_semana(fuerza[a]), stats_semana(fuerza[b])
            ga, gb = resultado(sa, sb)
            if ga == gb:
                ga += 1 if random.random() < .5 else 0
                gb += 0 if ga > gb else 1
            p = {"estado": "postevent", "playoffs": True, "consolacion": cons,
                 "equipos": [{"key": key(a), "stats": sa}, {"key": key(b), "stats": sb}]}
            return p, (a, b) if ga > gb else (b, a)
        s1, w1 = jugar(orden[0], orden[3]); s2, w2 = jugar(orden[1], orden[2])
        semanas.append({"semana": n_reg + 1, "partidos": [s1, s2]})
        f, (camp, sub) = jugar(w1[0], w2[0]); t3, (ter, cua) = jugar(w1[1], w2[1], True)
        semanas.append({"semana": n_reg + 2, "partidos": [f, t3]})
        for n, i in enumerate([camp, sub, ter, cua] + [i for i in orden if i not in (camp, sub, ter, cua)]):
            puestos[i] = n + 1
    else:
        for n, i in enumerate(orden):
            puestos[i] = n + 1
    return semanas, puestos, rec


def escribir(ruta, datos):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")


def main():
    random.seed(11)
    if SALIDA.exists():
        shutil.rmtree(SALIDA)
    liga_act = json.loads((RAIZ / "data/liga_prueba/liga.json").read_text())
    plant_act = json.loads((RAIZ / "data/liga_prueba/plantillas.json").read_text())["equipos"]
    nba = json.loads((RAIZ / "data/nba/jugadores.json").read_text())["jugadores"]
    nombre_de = {str(j["id"]): j["nombre"] for j in nba}
    equipos_act = liga_act["equipos"]

    # Plantillas hacia atrás: partimos de las actuales y deshacemos movimientos inventados
    plantillas = {i: [str(j["yahoo_id"]) for j in plant_act[e["key"]]] for i, e in enumerate(equipos_act)}
    todos = [str(j["id"]) for j in nba]
    historia = {}
    for t in reversed(TEMPORADAS):
        g = GAMES[t]
        lk = liga_act["league_key"] if t == 2026 else f"{g}.l.{1000 + t}"
        key = lambda i: f"{lk}.t.{i + 1}"   # noqa: E731
        inicio = date(t, 10, 20)
        movs = []
        # Movimientos de la temporada (se inventan a partir de la plantilla del final)
        final = {i: list(v) for i, v in plantillas.items()}
        # Se deshacen movimientos desde el final hacia atrás, con fechas cada vez más antiguas
        libres = [p for p in todos if not any(p in v for v in final.values())]
        fecha = inicio + timedelta(days=170)
        for n in range(85):
            fecha -= timedelta(days=random.choice([1, 2, 2, 3]))
            if fecha <= inicio:
                break
            if random.random() < 0.5:                         # traspaso 1x1
                a, b = random.sample(range(12), 2)
                ja, jb = random.choice(final[a]), random.choice(final[b])
                # después del traspaso ja está en a y jb en b -> antes estaban al revés
                final[a].remove(ja); final[b].remove(jb); final[a].append(jb); final[b].append(ja)
                movs.append({"id": f"{lk}.tr.{n}", "tipo": "trade", "estado": "successful", "fecha": f"{fecha}T20:00:00+00:00",
                             "propone": key(b), "recibe": key(a),
                             "jugadores": [{"jugador": f"{g}.p.{ja}", "nombre": nombre_de.get(ja), "tipo": "trade", "de": key(b), "a": key(a)},
                                           {"jugador": f"{g}.p.{jb}", "nombre": nombre_de.get(jb), "tipo": "trade", "de": key(a), "a": key(b)}]})
            else:                                             # fichaje de un libre con su baja
                i = random.randrange(12)
                entra, sale = random.choice(final[i]), random.choice(libres)
                final[i].remove(entra); final[i].append(sale); libres.remove(sale); libres.append(entra)
                movs.append({"id": f"{lk}.ad.{n}", "tipo": "add/drop", "estado": "successful", "fecha": f"{fecha}T09:00:00+00:00",
                             "jugadores": [{"jugador": f"{g}.p.{entra}", "nombre": nombre_de.get(entra), "tipo": "add", "de": "freeagents", "a": key(i)},
                                           {"jugador": f"{g}.p.{sale}", "nombre": nombre_de.get(sale), "tipo": "drop", "de": key(i), "a": "waivers"}]})
        # 'final' es ahora la plantilla al empezar la temporada
        nombres = [e["nombre"] if t == 2026 else (e["nombre"] if random.random() < .6 else f"{e['nombre'].split()[-1]} {random.choice(APODOS)}")
                   for e in equipos_act]
        equipos = [{"key": key(i), "id": str(i + 1), "nombre": nombres[i], "manager": equipos_act[i]["manager"], "logo": ""}
                   for i in range(12)]
        en_curso = t == 2026
        semanas, puesto_de, rec = semanas_temporada(key, 5 if en_curso else 20, not en_curso)
        # Draft de novatos: 2 rondas con jugadores de la plantilla inicial (los más jóvenes)
        picks, n = [], 0
        for r in range(2):
            for i in (range(12) if r == 0 else range(11, -1, -1)):
                n += 1
                cand = final[i][-(r + 1)]
                picks.append({"pick": n, "ronda": r + 1, "equipo": key(i), "jugador": f"{g}.p.{cand}", "nombre": nombre_de.get(cand)})
        historia[t] = {
            "liga.json": {"league_key": lk, "nombre": f"NBA Pontevedresa {t}-{str(t + 1)[2:]} (PRUEBA)", "temporada": str(t),
                          "fecha_inicio": str(inicio), "fecha_fin": f"{t + 1}-03-28", "playoffs_semana_inicio": "21",
                          "categorias": [{"id": str(n), "clave": k, "nombre": nm, "menos_es_mejor": m} for n, (k, nm, m) in enumerate(CATS)],
                          "equipos": equipos},
            "clasificacion.json": {"equipos": [{"key": key(i), "puesto": puesto_de[i], "g": rec[i][0], "p": rec[i][1], "e": rec[i][2]} for i in range(12)]},
            **{f"semanas/{w['semana']:02d}.json": w for w in semanas},
            "draft.json": {"picks": picks},
            "movimientos.json": {"movimientos": sorted(movs, key=lambda m: m["fecha"])},
            "plantillas_inicio.json": {"semana": 1, "equipos": {key(i): [{"yahoo_id": p, "nombre": nombre_de.get(p)} for p in final[i]] for i in range(12)}},
        }
        plantillas = final                                    # el final de la anterior = inicio de esta

    for t, archivos in historia.items():
        for nombre, datos in archivos.items():
            escribir(SALIDA / str(t) / nombre, datos)
    env = {**os.environ, "MODO": "indice", "HISTORICO_SALIDA": str(SALIDA)}
    subprocess.run([sys.executable, str(RAIZ / "scripts/historico.py")], env=env, check=True)


if __name__ == "__main__":
    main()
