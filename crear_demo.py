"""
Crea o reinicia el negocio de demostración, con servicios, clientes y turnos inventados.

Uso:
    python crear_demo.py               → crea la demo, si todavía no existe
    python crear_demo.py --reiniciar   → la borra y la vuelve a crear con turnos de esta semana

A la demo se entra con el botón "Probar la demo" de la pantalla de ingreso, sin
contraseña. Solo se toca el negocio de la demo: los demás negocios de la base
(por ejemplo, gente que se registró para probar) no se modifican.
Los celulares de la demo son números que no existen (11 0000-…), para que nadie
le mande un WhatsApp a un desconocido por accidente.
"""
import random
import secrets
import sqlite3
import sys
from datetime import timedelta

import app as A
from werkzeug.security import generate_password_hash

EMAIL = A.DEMO_EMAIL

con = sqlite3.connect(A.DATABASE)
con.execute("PRAGMA foreign_keys = ON")

anterior = con.execute("SELECT id FROM usuarios WHERE email=?", (EMAIL,)).fetchone()
if anterior:
    if '--reiniciar' not in sys.argv:
        sys.exit("La demo ya existe. Usá --reiniciar para volver a crearla.")
    # Borra el negocio de la demo con todos sus datos (en cascada)
    con.execute("DELETE FROM usuarios WHERE id=?", (anterior[0],))
    con.execute("DELETE FROM profesionales WHERE email='martin@turnero.test'")

pw = generate_password_hash(secrets.token_urlsafe(16))   # se entra sin contraseña, con el botón

uid = con.execute("INSERT INTO usuarios (email, password) VALUES (?, ?)", (EMAIL, pw)).lastrowid
nid = con.execute("INSERT INTO negocios (user_id, nombre, hora_apertura, hora_cierre, intervalo, dias) "
                  "VALUES (?, 'Espacio Bienestar', 540, 1200, 15, '0,1,2,3,4,5')", (uid,)).lastrowid
laura = con.execute("INSERT INTO profesionales (negocio_id, nombre, email, password, rol) VALUES (?, 'Laura', ?, ?, 'admin')",
                    (nid, EMAIL, pw)).lastrowid
martin = con.execute("INSERT INTO profesionales (negocio_id, nombre, email, password, rol) "
                     "VALUES (?, 'Martín', 'martin@turnero.test', ?, 'profesional')", (nid, pw)).lastrowid

servicios = [  # nombre, duración, cupo, color
    ('Masaje descontracturante', 60, 1, 'verde'),
    ('Masaje express', 30, 1, 'azul'),
    ('Depilación de cejas', 15, 1, 'rosa'),
    ('Clase de stretching', 60, 6, 'violeta'),
]
sid = [con.execute("INSERT INTO servicios (negocio_id, nombre, duracion, cupo, color) VALUES (?, ?, ?, ?, ?)",
                   (nid,) + s).lastrowid for s in servicios]

nombres = ['Ana', 'Belén', 'Carla', 'Diego', 'Elena', 'Florencia', 'Gabriel', 'Hernán', 'Inés', 'Julieta',
           'Karina', 'Lucía', 'Mariana', 'Nicolás', 'Olga', 'Pablo', 'Romina', 'Sofía']
apellidos = ['Gómez', 'Pérez', 'Rodríguez', 'Fernández', 'López', 'Martínez', 'García', 'Sánchez', 'Romero',
             'Sosa', 'Torres', 'Álvarez', 'Ruiz', 'Ramírez', 'Flores', 'Acosta', 'Benítez', 'Medina']
cid = []
for i, (n, a) in enumerate(zip(nombres, apellidos), start=1):
    # Casi todos son clientes de hace tiempo; los dos últimos, nuevos
    antiguedad = "datetime('now')" if i > len(nombres) - 2 else "datetime('now', '-90 days')"
    cid.append(con.execute(
        f"INSERT INTO clientes (negocio_id, nombre, apellido, telefono, creado_en) VALUES (?, ?, ?, ?, {antiguedad})",
        (nid, n, a, f'11 0000-{i:04d}')).lastrowid)

random.seed(11)


def libre(prof, dia, fecha, inicio, dur, servicio, cupo):
    """Chequeo simple para no superponer turnos al generar la demo."""
    filas = con.execute(
        "SELECT servicio_id, inicio, duracion FROM turnos WHERE profesional_id=? AND "
        "((tipo='fijo' AND dia_semana=?) OR (tipo='puntual' AND fecha=?))", (prof, dia, fecha)).fetchall()
    mismos = 0
    for s, i, d in filas:
        if i < inicio + dur and inicio < i + d:
            if s == servicio and i == inicio:
                mismos += 1
            else:
                return False
    return mismos < cupo


def turno(prof, cliente, servicio, inicio, dur, dia=None, fecha=None):
    con.execute(
        "INSERT INTO turnos (negocio_id, profesional_id, cliente_id, servicio_id, tipo, dia_semana, fecha, inicio, duracion) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (nid, prof, cliente, servicio, 'fijo' if fecha is None else 'puntual', dia, fecha, inicio, dur))


# Clase grupal fija: lunes y jueves 18:00 con Martín (5 personas)
for c in cid[:5]:
    for dia in (0, 3):
        turno(martin, c, sid[3], 1080, 60, dia=dia)

# Masajes fijos semanales con Laura
for c, dia, inicio in [(cid[5], 1, 600), (cid[6], 2, 660), (cid[7], 4, 570)]:
    turno(laura, c, sid[0], inicio, 60, dia=dia)

# Turnos sueltos esta semana y la próxima
lunes = A.hoy() - timedelta(days=A.hoy().weekday())
for _ in range(40):
    f = lunes + timedelta(days=random.randint(0, 12))
    if f.weekday() == 6:
        continue
    k = random.choice([0, 1, 2, 2])
    dur = servicios[k][1]
    inicio = random.choice(range(540, 1200 - dur + 1, 15))
    prof = random.choice([laura, laura, martin])
    c = random.choice(cid[5:])
    if libre(prof, f.weekday(), f.isoformat(), inicio, dur, sid[k], 1):
        turno(prof, c, sid[k], inicio, dur, fecha=f.isoformat())
con.commit()

print("Demo " + ("reiniciada." if anterior else "creada.") + " Se entra con el botón \"Probar la demo\".")
