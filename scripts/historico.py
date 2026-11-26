"""
historico.py · NbaPontevedresa · Copia del histórico de la liga desde Yahoo.

Lo lanza a mano el Action "Importar histórico". Recorre las temporadas hacia atrás
siguiendo la cadena de renovaciones de Yahoo ("renew") desde la liga actual.

Modos (variable MODO):
  censo     -> solo mira qué guarda Yahoo de cada temporada (rápido) y lo resume en
               data/historico/censo.json. Es lo primero que hay que lanzar.
  importar  -> descarga y guarda en data/historico/<temporada>/:
                 liga.json          configuración, categorías y equipos (sin emails)
                 clasificacion.json puestos y récords
                 semanas/NN.json    enfrentamientos de cada semana con estadísticas
                 draft.json         elecciones del draft con nombres
                 movimientos.json   fichajes, bajas y traspasos
                 plantillas_inicio.json  plantillas de la semana 1
               Es reanudable: lo que ya está guardado de temporadas terminadas no se
               vuelve a pedir. Para antes de MINUTOS_MAX y guarda lo hecho; si no le da
               tiempo, basta con volver a lanzarlo.

  indice    -> solo rehace data/historico/jugadores.json (se hace también al final de importar):
               para cada jugador, todos sus pasos por la liga (draft, plantilla al empezar
               cada temporada, fichajes, bajas y traspasos) y los nombres de los equipos de
               cada temporada. Es lo que usa la ficha del jugador en la web.

Opcional: TEMPORADAS="2008-2012" para limitar el rango.
Pruebas: YAHOO_FIXTURES=scripts/pruebas/yahoo HISTORICO_SALIDA=/tmp/historico
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import conexion as cx  # noqa: E402
from conexion import ErrorAPI, api, bloque, datos_equipo, datos_jugador, elementos, fusionar  # noqa: E402

MODO = os.environ.get("MODO", "censo").strip().lower()
MINUTOS_MAX = float(os.environ.get("MINUTOS_MAX", "40"))
SALIDA = Path(os.environ.get("HISTORICO_SALIDA") or cx.DATA / "historico")
INICIO = time.time()


def rango_temporadas():
    t = os.environ.get("TEMPORADAS", "").strip()
    if not t:
        return None
    a, _, b = t.partition("-")
    return int(a), int(b or a)


def queda_tiempo():
    return (time.time() - INICIO) / 60 < MINUTOS_MAX


def escribir(ruta, datos):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")


def cadena_ligas(token):
    """[(league_key, meta)] desde la temporada actual hacia atrás."""
    juego = cx.comprobar_acceso(token)
    clave = cx.buscar_liga(token, juego)
    out, vistas = [], set()
    while clave and clave not in vistas:
        vistas.add(clave)
        try:
            meta = fusionar(api(token, f"league/{clave}")["league"])
        except ErrorAPI as e:
            print(f"AVISO  No pude leer {clave} (HTTP {e.codigo}): la cadena se corta aquí.")
            break
        out.append((clave, meta))
        clave = cx.clave_renovada(meta.get("renew"))
    print(f"OK  {len(out)} temporadas encontradas: "
          + ", ".join(f"{m.get('season')}" for _, m in out))
    return out


def contar(token, ruta, clave_bloque, clave_elem):
    try:
        return len(elementos(bloque(api(token, ruta)["league"], clave_bloque), clave_elem))
    except ErrorAPI as e:
        return f"error {e.codigo}"


# ---------------------------------------------------------------- censo
def censo(token, ligas):
    filas = []
    for clave, meta in ligas:
        f = {"temporada": meta.get("season"), "league_key": clave, "nombre": meta.get("name"),
             "equipos": meta.get("num_teams"), "puntuacion": meta.get("scoring_type"),
             "semanas": f"{meta.get('start_week')}-{meta.get('end_week')}"}
        try:
            liga, _ = cx.leer_settings(token, clave)
            f["categorias"] = [c["nombre"] for c in liga["categorias"]]
            f["huecos"] = [f"{p['posicion']}x{p['huecos']}" for p in liga["posiciones"]]
        except ErrorAPI as e:
            f["categorias"] = f"error {e.codigo}"
        f["draft"] = contar(token, f"league/{clave}/draftresults", "draft_results", "draft_result")
        f["movimientos_primeros"] = contar(token, f"league/{clave}/transactions;start=0;count=25",
                                           "transactions", "transaction")
        try:
            e1 = cx.leer_enfrentamientos(token, clave, meta.get("start_week") or 1)
            f["semana1_enfrentamientos"] = len(e1["partidos"])
            f["semana1_con_estadisticas"] = any(eq["stats"] for p in e1["partidos"] for eq in p["equipos"])
        except ErrorAPI as e:
            f["semana1_enfrentamientos"] = f"error {e.codigo}"
        try:
            eqs = cx.leer_equipos(token, clave)
            f["mánagers_con_apodo"] = sum(1 for e in eqs if e["manager"])
        except ErrorAPI as e:
            f["mánagers_con_apodo"] = f"error {e.codigo}"
        filas.append(f)
        print(f"  {f['temporada']}: {f['nombre']} · {f['equipos']} equipos · {f['puntuacion']} · "
              f"draft {f['draft']} · movimientos {f['movimientos_primeros']} · "
              f"semana 1 {f.get('semana1_enfrentamientos')} (stats: {f.get('semana1_con_estadisticas')}) · "
              f"cats {len(f['categorias']) if isinstance(f['categorias'], list) else f['categorias']}")
    escribir(SALIDA / "censo.json", {"temporadas": filas,
                                     "actualizado": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    print(f"OK  Censo guardado en {SALIDA / 'censo.json'}")


# ---------------------------------------------------------------- importar
def nombres_jugadores(token, clave, player_keys):
    """{player_key: nombre} pidiendo de 25 en 25."""
    out = {}
    keys = sorted(set(k for k in player_keys if k))
    for i in range(0, len(keys), 25):
        lote = ",".join(keys[i:i + 25])
        try:
            fc = api(token, f"league/{clave}/players;player_keys={lote}")
        except ErrorAPI as e:
            print(f"AVISO  Nombres de jugadores (lote {i // 25 + 1}): HTTP {e.codigo}")
            continue
        for p in elementos(bloque(fc["league"], "players"), "player"):
            d = fusionar(p)
            n = d.get("name", {})
            out[d.get("player_key")] = n.get("full") if isinstance(n, dict) else n
    return out


def leer_draft(token, clave):
    fc = api(token, f"league/{clave}/draftresults")
    picks = [fusionar(d) for d in elementos(bloque(fc["league"], "draft_results"), "draft_result")]
    nombres = nombres_jugadores(token, clave, [p.get("player_key") for p in picks])
    return [{"pick": int(p.get("pick") or 0), "ronda": int(p.get("round") or 0), "equipo": p.get("team_key"),
             "jugador": p.get("player_key"), "nombre": nombres.get(p.get("player_key")),
             **({"coste": p.get("cost")} if p.get("cost") else {})} for p in picks]


def leer_movimientos(token, clave):
    out, start = [], 0
    while True:
        fc = api(token, f"league/{clave}/transactions;start={start};count=25")
        lote = elementos(bloque(fc["league"], "transactions"), "transaction")
        for t in lote:
            d = fusionar(t)
            jugadores = []
            for p in elementos(d.get("players", {}), "player"):
                pd = fusionar(p)
                td = pd.get("transaction_data", {})
                td = td[0] if isinstance(td, list) and td else td
                n = pd.get("name", {})
                jugadores.append({"jugador": pd.get("player_key"),
                                  "nombre": n.get("full") if isinstance(n, dict) else n,
                                  "tipo": td.get("type"),
                                  "de": td.get("source_team_key") or td.get("source_type"),
                                  "a": td.get("destination_team_key") or td.get("destination_type")})
            mov = {"id": d.get("transaction_key"), "tipo": d.get("type"), "estado": d.get("status"),
                   "fecha": datetime.fromtimestamp(int(d.get("timestamp") or 0), timezone.utc).isoformat(timespec="seconds"),
                   "jugadores": jugadores}
            for k_y, k_n in (("trader_team_key", "propone"), ("tradee_team_key", "recibe")):
                if d.get(k_y):
                    mov[k_n] = d[k_y]
            if d.get("picks"):                                       # rondas de draft en traspasos
                mov["rondas"] = [fusionar(x) for x in elementos(d["picks"], "pick")] or d["picks"]
            out.append(mov)
        if len(lote) < 25:
            break
        start += 25
    return out


def leer_plantillas_semana(token, clave, semana):
    fc = api(token, f"league/{clave}/teams/roster;week={semana}")
    res = {}
    for t in elementos(bloque(fc["league"], "teams"), "team"):
        d, info = datos_equipo(t)
        roster = d.get("roster", {})
        cont = roster.get("0", {}).get("players", roster.get("players", {}))
        res[info["key"]] = [{k: v for k, v in datos_jugador(p).items() if k in ("yahoo_id", "nombre", "equipo_nba", "pos", "hueco")}
                            for p in elementos(cont, "player")]
    return res


def importar_temporada(token, clave, meta, actual):
    temporada = str(meta.get("season"))
    carpeta = SALIDA / temporada
    terminada = not actual
    hecho = lambda f: terminada and (carpeta / f).exists()   # noqa: E731

    pasos = [
        ("liga.json", lambda: {**cx.leer_settings(token, clave)[0], "equipos": cx.leer_equipos(token, clave)}),
        ("clasificacion.json", lambda: {"equipos": cx.leer_clasificacion(token, clave)}),
        ("draft.json", lambda: {"picks": leer_draft(token, clave)}),
        ("movimientos.json", lambda: {"movimientos": leer_movimientos(token, clave)}),
        ("plantillas_inicio.json", lambda: {"semana": meta.get("start_week") or 1,
                                            "equipos": leer_plantillas_semana(token, clave, meta.get("start_week") or 1)}),
    ]
    for nombre, fn in pasos:
        if hecho(nombre):
            continue
        if not queda_tiempo():
            return False
        try:
            escribir(carpeta / nombre, fn())
            print(f"  {temporada}: {nombre} ✓")
        except ErrorAPI as e:
            print(f"AVISO  {temporada}: {nombre} → HTTP {e.codigo} ({cx.descripcion_error(e)[:120]})")

    ini = int(meta.get("start_week") or 1)
    fin = int(meta.get("end_week") or ini)
    if actual:                                       # temporada en curso: solo semanas cerradas
        fin = min(fin, int(meta.get("current_week") or ini) - 1)
    nuevas = 0
    for s in range(ini, fin + 1):
        f = carpeta / "semanas" / f"{s:02d}.json"
        if f.exists():
            continue
        if not queda_tiempo():
            return False
        try:
            escribir(f, cx.leer_enfrentamientos(token, clave, s))
            nuevas += 1
        except ErrorAPI as e:
            print(f"AVISO  {temporada}: semana {s} → HTTP {e.codigo}")
    if nuevas:
        print(f"  {temporada}: {nuevas} semanas nuevas ✓")
    return True


# ---------------------------------------------------------------- índice de jugadores
def pid(player_key):
    """'466.p.5352' -> '5352' (el número de jugador de Yahoo no cambia entre temporadas)."""
    return str(player_key or "").split(".p.")[-1] or None


def construir_indice():
    temporadas, jugadores = {}, {}

    def ev(p, nombre, e):
        if not p:
            return
        j = jugadores.setdefault(p, {"nombre": nombre, "eventos": []})
        if nombre:
            j["nombre"] = nombre
        j["eventos"].append(e)

    for carpeta in sorted(SALIDA.glob("[0-9][0-9][0-9][0-9]")):
        t = carpeta.name
        liga = cx.leer_json(carpeta / "liga.json", {})
        inicio = liga.get("fecha_inicio") or f"{t}-10-01"
        temporadas[t] = {"nombre": liga.get("nombre"), "inicio": inicio,
                         "equipos": {e["key"]: {"nombre": e.get("nombre"), "manager": e.get("manager")}
                                     for e in liga.get("equipos", [])}}
        clasif = cx.leer_json(carpeta / "clasificacion.json", {}).get("equipos", [])
        for c in clasif:
            if c["key"] in temporadas[t]["equipos"]:
                temporadas[t]["equipos"][c["key"]]["puesto"] = c.get("puesto")
        for p in cx.leer_json(carpeta / "draft.json", {}).get("picks", []):
            ev(pid(p.get("jugador")), p.get("nombre"),
               {"t": t, "tipo": "draft", "fecha": inicio, "a": p.get("equipo"), "ronda": p.get("ronda"), "pick": p.get("pick")})
        for key, lista in cx.leer_json(carpeta / "plantillas_inicio.json", {}).get("equipos", {}).items():
            for j in lista:
                ev(j.get("yahoo_id"), j.get("nombre"), {"t": t, "tipo": "inicio", "fecha": inicio, "a": key})
        for m in cx.leer_json(carpeta / "movimientos.json", {}).get("movimientos", []):
            if m.get("estado") not in (None, "successful"):
                continue
            for j in m.get("jugadores", []):
                ev(pid(j.get("jugador")), j.get("nombre"),
                   {"t": t, "tipo": j.get("tipo") or m.get("tipo"), "fecha": (m.get("fecha") or "")[:10],
                    "de": j.get("de"), "a": j.get("a")})
    orden = {"draft": 0, "inicio": 1}
    for j in jugadores.values():
        j["eventos"].sort(key=lambda e: (e["fecha"] or "", orden.get(e["tipo"], 2)))
    escribir(SALIDA / "jugadores.json", {"temporadas": temporadas, "jugadores": jugadores,
                                          "actualizado": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    print(f"OK  Índice de jugadores: {len(jugadores)} jugadores en {len(temporadas)} temporadas.")


def importar(token, ligas):
    rango = rango_temporadas()
    for i, (clave, meta) in enumerate(ligas):
        t = int(meta.get("season") or 0)
        if rango and not (rango[0] <= t <= rango[1]):
            continue
        if not importar_temporada(token, clave, meta, actual=(i == 0)):
            construir_indice()
            print(f"⏸  Se acabó el tiempo ({MINUTOS_MAX:.0f} min) en la temporada {t}. "
                  "Lo hecho queda guardado: vuelve a lanzar el Action para seguir.")
            return
    escribir(SALIDA / "indice.json", {
        "temporadas": [{"temporada": m.get("season"), "league_key": k, "nombre": m.get("name")} for k, m in ligas],
        "actualizado": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    construir_indice()
    print("✅ Histórico completo.")


def main():
    if MODO == "indice":
        return construir_indice()
    token = cx.obtener_token()
    ligas = cadena_ligas(token)
    if MODO == "censo":
        censo(token, ligas)
    elif MODO == "importar":
        importar(token, ligas)
    else:
        cx.fallo(f"MODO desconocido: {MODO} (usa censo, importar o indice)")


if __name__ == "__main__":
    main()
