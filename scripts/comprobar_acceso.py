
"""
comprobar_acceso.py · NbaPontevedresa · ¿Ha aprobado ya Yahoo la app?

Lo ejecuta GitHub Actions una vez al día (workflow "Comprobar acceso Yahoo").
Renueva el token y hace UNA consulta pública (game/nba):
  - 403 "not authorized"  -> todavía sin aprobar (el Action sale en verde, sin más).
  - respuesta correcta    -> ¡aprobado! El workflow abre un aviso (issue) en el repo.
  - otro error            -> el Action sale en rojo para que se revise.

No guarda nada en el repositorio y nunca imprime tokens.
"""

import os
import sys

from conexion import ErrorAPI, api, descripcion_error, fusionar, obtener_token


def escribir_salida(acceso):
    ruta = os.environ.get("GITHUB_OUTPUT")
    if ruta:
        with open(ruta, "a", encoding="utf-8") as f:
            f.write(f"acceso={acceso}\n")


def resumen(texto):
    ruta = os.environ.get("GITHUB_STEP_SUMMARY")
    if ruta:
        with open(ruta, "a", encoding="utf-8") as f:
            f.write(texto + "\n")
    print(texto)


def main():
    token = obtener_token()  # si las claves fallan, sale en rojo él solo
    try:
        juego = fusionar(api(token, "game/nba")["game"])
    except ErrorAPI as e:
        desc = descripcion_error(e)
        if e.codigo == 403 and "not authorized" in desc.lower():
            escribir_salida("no")
            resumen("⏳ Yahoo todavía no ha aprobado la app (403: not authorized). Mañana se vuelve a probar.")
            return
        escribir_salida("error")
        resumen(f"❌ Error inesperado de Yahoo (HTTP {e.codigo}): {desc}")
        sys.exit(1)

    escribir_salida("si")
    resumen(f"✅ ¡Acceso concedido! Yahoo responde: temporada {juego.get('season')}, "
            f"game_key {juego.get('game_key')}. Ya se puede lanzar «Actualizar liga».")


if __name__ == "__main__":
    main()
