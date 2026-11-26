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
        puestos = random.sample(range(1, 13), 12)
        # Draft de novatos: 2 rondas con jugadores de la plantilla inicial (los más jóvenes)
        picks, n = [], 0
        for r in range(2):
            for i in (range(12) if r == 0 else range(11, -1, -1)):
                n += 1
                cand = final[i][-(r + 1)]
                picks.append({"pick": n, "ronda": r + 1, "equipo": key(i), "jugador": f"{g}.p.{cand}", "nombre": nombre_de.get(cand)})
        historia[t] = {
            "liga.json": {"league_key": lk, "nombre": f"NBA Pontevedresa {t}-{str(t + 1)[2:]} (PRUEBA)", "temporada": str(t),
                          "fecha_inicio": str(inicio), "equipos": equipos},
            "clasificacion.json": {"equipos": [{"key": key(i), "puesto": puestos[i], "g": 0, "p": 0, "e": 0} for i in range(12)]},
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
