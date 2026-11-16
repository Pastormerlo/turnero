"""
Crea un negocio de demostración con servicios, clientes y turnos inventados.

Uso:
    python crear_demo.py                 → contraseña generada al azar
    python crear_demo.py MiClave123      → contraseña elegida

Solo funciona sobre una base vacía (no toca datos reales).
"""
import random
import secrets
import sqlite3
import sys
from datetime import date, timedelta

import app as A
from werkzeug.security import generate_password_hash

EMAIL = 'demo@turnero.test'

con = sqlite3.connect(A.DATABASE)
if con.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]:
    sys.exit("La base ya tiene datos: no se cargó la demo.")

password = sys.argv[1] if len(sys.argv) > 1 else secrets.token_urlsafe(8)
if len(password) < 6:
    sys.exit("La contraseña debe tener al menos 6 caracteres.")
pw = generate_password_hash(password)

con.execute("INSERT INTO usuarios (email, password) VALUES (?, ?)", (EMAIL, pw))
con.execute("INSERT INTO negocios (user_id, nombre, hora_apertura, hora_cierre, intervalo, dias) "
            "VALUES (1, 'Espacio Bienestar', 540, 1200, 15, '0,1,2,3,4,5')")
con.execute("INSERT INTO profesionales (negocio_id, nombre, email, password, rol) VALUES (1, 'Laura', ?, ?, 'admin')", (EMAIL, pw))
con.execute("INSERT INTO profesionales (negocio_id, nombre, email, password, rol) VALUES (1, 'Martín', 'martin@turnero.test', ?, 'profesional')", (pw,))

servicios = [  # nombre, duración, cupo, color
    ('Masaje descontracturante', 60, 1, 'verde'),
    ('Masaje express', 30, 1, 'azul'),
    ('Depilación de cejas', 15, 1, 'rosa'),
    ('Clase de stretching', 60, 6, 'violeta'),
]
for s in servicios:
    con.execute("INSERT INTO servicios (negocio_id, nombre, duracion, cupo, color) VALUES (1, ?, ?, ?, ?)", s)

nombres = ['Ana', 'Belén', 'Carla', 'Diego', 'Elena', 'Florencia', 'Gabriel', 'Hernán', 'Inés', 'Julieta',
           'Karina', 'Lucía', 'Mariana', 'Nicolás', 'Olga', 'Pablo', 'Romina', 'Sofía']
apellidos = ['Gómez', 'Pérez', 'Rodríguez', 'Fernández', 'López', 'Martínez', 'García', 'Sánchez', 'Romero',
             'Sosa', 'Torres', 'Álvarez', 'Ruiz', 'Ramírez', 'Flores', 'Acosta', 'Benítez', 'Medina']
random.seed(11)
for n, a in zip(nombres, apellidos):
    con.execute("INSERT INTO clientes (negocio_id, nombre, apellido, telefono) VALUES (1, ?, ?, ?)",
                (n, a, f'11 4{random.randint(100, 999)}-{random.randint(1000, 9999)}'))


def libre(prof, dia, fecha, inicio, dur, sid, cupo):
    """Chequeo simple para no superponer turnos al generar la demo."""
    filas = con.execute(
        "SELECT servicio_id, inicio, duracion FROM turnos WHERE profesional_id=? AND "
        "((tipo='fijo' AND dia_semana=?) OR (tipo='puntual' AND fecha=?))", (prof, dia, fecha)).fetchall()
    mismos = 0
    for s, i, d in filas:
        if i < inicio + dur and inicio < i + d:
            if s == sid and i == inicio:
                mismos += 1
            else:
                return False
    return mismos < cupo


# Clase grupal fija: lunes y jueves 18:00 con Martín (5 personas)
for cid in range(1, 6):
    for dia in (0, 3):
        con.execute("INSERT INTO turnos (negocio_id, profesional_id, cliente_id, servicio_id, tipo, dia_semana, inicio, duracion) "
                    "VALUES (1, 2, ?, 4, 'fijo', ?, 1080, 60)", (cid, dia))

# Masajes fijos semanales con Laura
for cid, dia, inicio in [(6, 1, 600), (7, 2, 660), (8, 4, 570)]:
    con.execute("INSERT INTO turnos (negocio_id, profesional_id, cliente_id, servicio_id, tipo, dia_semana, inicio, duracion) "
                "VALUES (1, 1, ?, 1, 'fijo', ?, ?, 60)", (cid, dia, inicio))

# Turnos sueltos esta semana y la próxima
lunes = date.today() - timedelta(days=date.today().weekday())
for _ in range(40):
    f = lunes + timedelta(days=random.randint(0, 12))
    if f.weekday() == 6:
        continue
    sid = random.choice([1, 2, 3, 3])
    dur = servicios[sid - 1][1]
    inicio = random.choice(range(540, 1200 - dur + 1, 15))
    prof = random.choice([1, 1, 2])
    cid = random.randint(6, len(nombres))
    if libre(prof, f.weekday(), f.isoformat(), inicio, dur, sid, 1):
        con.execute("INSERT INTO turnos (negocio_id, profesional_id, cliente_id, servicio_id, tipo, fecha, inicio, duracion) "
                    "VALUES (1, ?, ?, ?, 'puntual', ?, ?, ?)", (prof, cid, sid, f.isoformat(), inicio, dur))
con.commit()

print("Demo creada.")
print(f"  Email:      {EMAIL}")
print(f"  Contraseña: {password}")
