"""
valor.py · NbaPontevedresa · Valor de cada jugador en las 9 categorías (z-scores).

Método habitual en ligas H2H de 9 categorías:
  - Contables (3PM, PTS, REB, AST, STL, BLK): z = (valor - media) / desviación.
  - Porcentajes (FG%, FT%): se mide el IMPACTO = intentos × (su % - % medio del grupo),
    porque un 60 % en 3 tiros pesa menos que un 50 % en 20 tiros.
  - Pérdidas (TO): igual que una contable pero con el signo cambiado (menos es mejor).
  - Las medias se calculan sobre el "grupo de referencia": los 168 mejores jugadores
    (12 equipos × 14), en dos pasadas para que no lo distorsionen los suplentes.
"""

import math

CATEGORIAS = ["fg", "ft", "tpm", "pts", "reb", "ast", "stl", "blk", "to"]
TAM_GRUPO = 12 * 14
MIN_MINUTOS = 12.0


def _media_desv(valores):
    n = len(valores)
    if n == 0:
        return 0.0, 1.0
    m = sum(valores) / n
    d = math.sqrt(sum((v - m) ** 2 for v in valores) / n)
    return m, (d if d > 1e-9 else 1.0)


def _brutos(s):
    """Medias por partido -> valores de cada categoría (porcentajes como impacto aún sin centrar)."""
    fga, fta = s.get("fga") or 0, s.get("fta") or 0
    return {
        "fgm": (s.get("fg_pct") or 0) * fga, "fga": fga,
        "ftm": (s.get("ft_pct") or 0) * fta, "fta": fta,
        **{k: s.get(k) or 0 for k in ("tpm", "pts", "reb", "ast", "stl", "blk", "to")},
    }


def _parametros(grupo):
    sum_fga = sum(b["fga"] for b in grupo) or 1
    sum_fta = sum(b["fta"] for b in grupo) or 1
    p = {"fg_medio": sum(b["fgm"] for b in grupo) / sum_fga,
         "ft_medio": sum(b["ftm"] for b in grupo) / sum_fta}
    p["fg"] = _media_desv([_impacto(b, "fg", p) for b in grupo])
    p["ft"] = _media_desv([_impacto(b, "ft", p) for b in grupo])
    for k in ("tpm", "pts", "reb", "ast", "stl", "blk", "to"):
        p[k] = _media_desv([b[k] for b in grupo])
    return p


def _impacto(b, cat, p):
    if cat == "fg":
        return b["fgm"] - b["fga"] * p["fg_medio"]
    return b["ftm"] - b["fta"] * p["ft_medio"]


def _zetas(b, p):
    z = []
    for c in CATEGORIAS:
        x = _impacto(b, c, p) if c in ("fg", "ft") else b[c]
        m, d = p[c]
        v = (x - m) / d
        z.append(-v if c == "to" else v)
    return z


def calcular(jugadores, ventana, pj_min):
    """Añade a cada jugador[ventana] las claves 'z' (9 valores), 'valor' y 'elegible'.
    Devuelve el número de jugadores elegibles (0 si no hay datos suficientes)."""
    filas = [(j, _brutos(j[ventana])) for j in jugadores if j.get(ventana)]
    elegibles = [(j, b) for j, b in filas
                 if j[ventana]["pj"] >= pj_min and j[ventana]["min"] >= MIN_MINUTOS]
    if len(elegibles) < 20:
        return 0

    # 1.ª pasada con todos los elegibles; 2.ª con los 168 mejores
    p = _parametros([b for _, b in elegibles])
    elegibles.sort(key=lambda jb: -sum(_zetas(jb[1], p)))
    p = _parametros([b for _, b in elegibles[:TAM_GRUPO]])

    ids_elegibles = {id(j) for j, _ in elegibles}
    for j, b in filas:
        z = [round(v, 2) for v in _zetas(b, p)]
        j[ventana]["z"] = z
        j[ventana]["valor"] = round(sum(z), 2)
        j[ventana]["elegible"] = id(j) in ids_elegibles
    return len(elegibles)
