"""
Negocio de demostración: servicios, clientes y turnos inventados.

Lo usan crear_demo.py (desde la consola) y la app (reinicia la demo sola cuando
alguien entra y la demo es de un día anterior). Solo toca el negocio de la demo:
los demás negocios de la base no se modifican. Los celulares son números que no
existen (11 0000-…), para que nadie le mande un WhatsApp a un desconocido.
"""
import random
import secrets
from datetime import timedelta

from werkzeug.security import generate_password_hash

MARTIN = 'martin@turnero.test'

SERVICIOS = [  # nombre, duración, cupo, color
    ('Masaje descontracturante', 60, 1, 'verde'),
    ('Masaje express', 30, 1, 'azul'),
    ('Depilación de cejas', 15, 1, 'rosa'),
    ('Clase de stretching', 60, 6, 'violeta'),
]
NOMBRES = ['Ana', 'Belén', 'Carla', 'Diego', 'Elena', 'Florencia', 'Gabriel', 'Hernán', 'Inés', 'Julieta',
           'Karina', 'Lucía', 'Mariana', 'Nicolás', 'Olga', 'Pablo', 'Romina', 'Sofía']
APELLIDOS = ['Gómez', 'Pérez', 'Rodríguez', 'Fernández', 'López', 'Martínez', 'García', 'Sánchez', 'Romero',
             'Sosa', 'Torres', 'Álvarez', 'Ruiz', 'Ramírez', 'Flores', 'Acosta', 'Benítez', 'Medina']


def existe(con, email):
    return con.execute("SELECT id FROM usuarios WHERE email=?", (email,)).fetchone() is not None


def creada_antes_de(con, email, momento_utc):
    """True si la demo existe y se creó antes de ese momento ('YYYY-MM-DD HH:MM:SS' en UTC)."""
    fila = con.execute("SELECT creado_en FROM usuarios WHERE email=?", (email,)).fetchone()
    return fila is not None and fila[0] < momento_utc


def crear(con, email, hoy):
    """Borra la demo (si existe) y la vuelve a crear con turnos de la semana de `hoy`.
    `con` necesita PRAGMA foreign_keys = ON para que el borrado sea en cascada."""
    anterior = con.execute("SELECT id FROM usuarios WHERE email=?", (email,)).fetchone()
    if anterior:
        con.execute("DELETE FROM usuarios WHERE id=?", (anterior[0],))
    con.execute("DELETE FROM profesionales WHERE email IN (?, ?)", (email, MARTIN))

    pw = generate_password_hash(secrets.token_urlsafe(16))   # se entra sin contraseña, con el botón
    uid = con.execute("INSERT INTO usuarios (email, password) VALUES (?, ?)", (email, pw)).lastrowid
    nid = con.execute("INSERT INTO negocios (user_id, nombre, hora_apertura, hora_cierre, intervalo, dias) "
                      "VALUES (?, 'Espacio Bienestar', 540, 1200, 15, '0,1,2,3,4,5')", (uid,)).lastrowid
    laura = con.execute("INSERT INTO profesionales (negocio_id, nombre, email, password, rol) VALUES (?, 'Laura', ?, ?, 'admin')",
                        (nid, email, pw)).lastrowid
    martin = con.execute("INSERT INTO profesionales (negocio_id, nombre, email, password, rol) "
                         "VALUES (?, 'Martín', ?, ?, 'profesional')", (nid, MARTIN, pw)).lastrowid
    sid = [con.execute("INSERT INTO servicios (negocio_id, nombre, duracion, cupo, color) VALUES (?, ?, ?, ?, ?)",
                       (nid,) + s).lastrowid for s in SERVICIOS]
    cid = []
    for i, (n, a) in enumerate(zip(NOMBRES, APELLIDOS), start=1):
        # Casi todos son clientes de hace tiempo; los dos últimos, nuevos
        antiguedad = "datetime('now')" if i > len(NOMBRES) - 2 else "datetime('now', '-90 days')"
        cid.append(con.execute(
            f"INSERT INTO clientes (negocio_id, nombre, apellido, telefono, creado_en) VALUES (?, ?, ?, ?, {antiguedad})",
            (nid, n, a, f'11 0000-{i:04d}')).lastrowid)

    def libre(prof, dia, fecha, inicio, dur, servicio):
        for s, i, d in con.execute(
                "SELECT servicio_id, inicio, duracion FROM turnos WHERE profesional_id=? AND "
                "((tipo='fijo' AND dia_semana=?) OR (tipo='puntual' AND fecha=?))", (prof, dia, fecha)):
            if i < inicio + dur and inicio < i + d:
                return False
        return True

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
    azar = random.Random(11)
    lunes = hoy - timedelta(days=hoy.weekday())
    for _ in range(40):
        f = lunes + timedelta(days=azar.randint(0, 12))
        k = azar.choice([0, 1, 2, 2])
        dur = SERVICIOS[k][1]
        inicio = azar.choice(range(540, 1200 - dur + 1, 15))
        prof = azar.choice([laura, laura, martin])
        c = azar.choice(cid[5:])
        if f.weekday() != 6 and libre(prof, f.weekday(), f.isoformat(), inicio, dur, sid[k]):
            turno(prof, c, sid[k], inicio, dur, fecha=f.isoformat())
    con.commit()
    return bool(anterior)
