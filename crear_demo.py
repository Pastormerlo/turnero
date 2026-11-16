"""
Crea o reinicia el negocio de demostración (ver demo.py).

Uso:
    python crear_demo.py               → crea la demo, si todavía no existe
    python crear_demo.py --reiniciar   → la borra y la vuelve a crear con turnos de esta semana

No hace falta reiniciarla a mano: la app la reinicia sola cuando alguien toca
"Probar la demo" y la demo es de un día anterior.
"""
import sqlite3
import sys

import app as A
import demo

con = sqlite3.connect(A.DATABASE)
con.execute("PRAGMA foreign_keys = ON")
if demo.existe(con, A.DEMO_EMAIL) and '--reiniciar' not in sys.argv:
    sys.exit("La demo ya existe. Usá --reiniciar para volver a crearla.")
reiniciada = demo.crear(con, A.DEMO_EMAIL, A.hoy())
print("Demo " + ("reiniciada." if reiniciada else "creada.") + " Se entra con el botón \"Probar la demo\".")
