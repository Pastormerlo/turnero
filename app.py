import os
import re
import secrets
import sqlite3
from flask import (
    Flask, render_template, request, redirect,
    url_for, session, jsonify, g, flash
)
from functools import wraps
from datetime import datetime, timedelta, date, timezone
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# ============================================================
#  CONFIGURACIÓN
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _cargar_secret_key():
    """SECRET_KEY del entorno; en desarrollo se genera una y se guarda en .secret_key."""
    key = os.environ.get('SECRET_KEY')
    if key:
        return key
    path = os.path.join(BASE_DIR, '.secret_key')
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return f.read().strip()
    key = secrets.token_hex(32)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(key)
    return key


app = Flask(__name__)
app.secret_key = _cargar_secret_key()

DATABASE = os.environ.get('DATABASE_PATH', os.path.join(BASE_DIR, 'turnero.db'))
SCHEMA   = os.path.join(BASE_DIR, 'schema.sql')

UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

app.config.update(
    UPLOAD_FOLDER=UPLOAD_FOLDER,
    MAX_CONTENT_LENGTH=2 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=os.environ.get('SESSION_COOKIE_SECURE') == '1',
)

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

VERSION    = '1.2'
# Cuenta de demostración: se entra con el botón "Probar la demo", sin contraseña
DEMO_EMAIL = os.environ.get('DEMO_EMAIL', 'demo@turnero.test')
DIAS       = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
DIAS_CORTO = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom']
DURACIONES = [15, 20, 30, 40, 45, 60, 75, 90, 120, 150, 180, 240]
# Color de cada servicio en la agenda: (fondo, borde/texto)
COLORES = {
    'verde':   ('#D8F3DC', '#2D6A4F'),
    'azul':    ('#DCEBFA', '#1F5F99'),
    'naranja': ('#FFEBD2', '#B85C00'),
    'violeta': ('#ECE3FA', '#6A3FA8'),
    'rosa':    ('#FCE4EC', '#AD2B5E'),
    'gris':    ('#ECEFF1', '#455A64'),
}


# El servidor puede estar en otro huso (PythonAnywhere usa UTC): "hoy" y "ahora" se
# calculan siempre en la hora local del negocio. Argentina = UTC-3, sin horario de verano.
HUSO = timezone(timedelta(hours=int(os.environ.get('UTC_OFFSET', '-3'))))


def ahora():
    return datetime.now(HUSO)


def hoy():
    return ahora().date()


def hhmm(minutos):
    minutos = int(minutos)
    return f"{minutos // 60:02d}:{minutos % 60:02d}"


app.jinja_env.filters['hhmm'] = hhmm


# ============================================================
#  BASE DE DATOS
# ============================================================
def preparar_db():
    if os.path.exists(DATABASE):
        return
    db = sqlite3.connect(DATABASE)
    try:
        with open(SCHEMA, 'r', encoding='utf-8') as f:
            db.executescript(f.read())
        db.commit()
        print(f"Base de datos creada: {DATABASE}")
    finally:
        db.close()


def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
    return db


@app.teardown_appcontext
def close_db(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


def query(sql, args=(), one=False):
    cur = get_db().execute(sql, args)
    rv = cur.fetchall()
    return (rv[0] if rv else None) if one else rv


def execute(sql, args=()):
    db = get_db()
    cur = db.execute(sql, args)
    db.commit()
    return cur.lastrowid


# ============================================================
#  CSRF
# ============================================================
def csrf_token():
    if '_csrf' not in session:
        session['_csrf'] = secrets.token_urlsafe(32)
    return session['_csrf']


app.jinja_env.globals['csrf_token'] = csrf_token


@app.before_request
def verificar_csrf():
    if request.method != 'POST':
        return None
    enviado  = request.form.get('_csrf') or request.headers.get('X-CSRFToken') or ''
    esperado = session.get('_csrf', '')
    if esperado and secrets.compare_digest(enviado, esperado):
        return None
    if request.is_json:
        return jsonify({'ok': False, 'error': 'La sesión expiró. Recargá la página.'}), 400
    flash('La sesión expiró. Volvé a intentarlo.', 'warning')
    return redirect(request.referrer or url_for('login'))


@app.errorhandler(413)
def archivo_grande(e):
    flash('El archivo es demasiado grande (máximo 2 MB).', 'danger')
    return redirect(request.referrer or url_for('agenda'))


# ============================================================
#  HELPERS
# ============================================================
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        pid = session.get('profesional_id')
        if not pid:
            return redirect(url_for('login'))
        # Se revalida en cada request: un profesional desactivado pierde el acceso al instante
        prof = query("SELECT rol, activo, negocio_id FROM profesionales WHERE id=?", (pid,), one=True)
        if not prof or not prof['activo'] or prof['negocio_id'] != session.get('negocio_id'):
            session.clear()
            if request.is_json:
                return jsonify({'ok': False, 'error': 'Sesión cerrada'}), 401
            return redirect(url_for('login'))
        session['rol'] = prof['rol']
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('rol') != 'admin':
            return redirect(url_for('agenda'))
        return f(*args, **kwargs)
    return decorated


def negocio_id():
    return session.get('negocio_id')


def profesional_id():
    return session.get('profesional_id')


def es_admin():
    return session.get('rol') == 'admin'


def get_negocio():
    """Negocio de la sesión, con los días de atención ya convertidos a lista."""
    if '_negocio' not in g:
        n = query("SELECT * FROM negocios WHERE id=?", (negocio_id(),), one=True)
        g._negocio = dict(n) if n else None
        if g._negocio:
            g._negocio['dias_lista'] = [int(d) for d in g._negocio['dias'].split(',') if d.strip() != '']
    return g._negocio


def parse_int(valor, default=None):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return default


def parse_fecha(valor):
    try:
        return datetime.strptime(valor or '', '%Y-%m-%d').date()
    except ValueError:
        return None


def parse_hora(valor):
    """'09:30' o '570' → minutos desde las 00:00."""
    if valor is None:
        return None
    valor = str(valor).strip()
    m = re.fullmatch(r'(\d{1,2}):(\d{2})', valor)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        return h * 60 + mi if h <= 24 and mi < 60 else None
    n = parse_int(valor)
    return n if n is not None and 0 <= n <= 1440 else None


def cliente_del_negocio(cid):
    return query("SELECT * FROM clientes WHERE id=? AND negocio_id=? AND activo=1",
                 (parse_int(cid, -1), negocio_id()), one=True)


def profesional_del_negocio(pid):
    return query("SELECT * FROM profesionales WHERE id=? AND negocio_id=? AND activo=1",
                 (parse_int(pid, -1), negocio_id()), one=True)


def servicio_del_negocio(sid, solo_activos=True):
    return query("SELECT * FROM servicios WHERE id=? AND negocio_id=?" + (" AND activo=1" if solo_activos else ""),
                 (parse_int(sid, -1), negocio_id()), one=True)


def turno_editable(tid):
    """Turno del negocio; si no es admin, solo los propios."""
    if es_admin():
        return query("SELECT * FROM turnos WHERE id=? AND negocio_id=?",
                     (parse_int(tid, -1), negocio_id()), one=True)
    return query("SELECT * FROM turnos WHERE id=? AND negocio_id=? AND profesional_id=?",
                 (parse_int(tid, -1), negocio_id(), profesional_id()), one=True)


def ocurrencias(fecha=None, dia=None, profesional=None, cliente=None, excluir=-1):
    """
    Turnos que ocurren en una fecha concreta (fijos sin excepción + puntuales),
    o, con `dia`, los fijos de ese día de la semana.
    """
    filtros, args = "", []
    if profesional is not None:
        filtros += " AND t.profesional_id=?"
        args.append(profesional)
    if cliente is not None:
        filtros += " AND t.cliente_id=?"
        args.append(cliente)
    if fecha is not None:
        cuando = """((t.tipo='puntual' AND t.fecha=?)
                     OR (t.tipo='fijo' AND t.dia_semana=? AND NOT EXISTS (
                            SELECT 1 FROM turnos_excepciones e WHERE e.turno_id=t.id AND e.fecha=?)))"""
        cargs = [fecha.isoformat(), fecha.weekday(), fecha.isoformat()]
    else:
        cuando = "(t.tipo='fijo' AND t.dia_semana=?)"
        cargs = [dia]
    return query(
        f"""SELECT t.*, s.nombre AS servicio_nombre FROM turnos t
            JOIN clientes c ON c.id = t.cliente_id
            JOIN servicios s ON s.id = t.servicio_id
            WHERE t.negocio_id=? AND t.id!=? AND c.activo=1 AND {cuando} {filtros}""",
        [negocio_id(), excluir] + cargs + args
    )


def validar_horario(prof, cliente_id, servicio, inicio, duracion, fecha=None, dia=None, excluir=-1):
    """
    Devuelve un mensaje de error si el turno no se puede dar, o None si está libre.
    Turnos superpuestos del mismo profesional solo se permiten si son del mismo
    servicio y empiezan a la misma hora (clase grupal), hasta el cupo del servicio.
    """
    neg = get_negocio()
    dia_sem = fecha.weekday() if fecha else dia
    if dia_sem not in neg['dias_lista']:
        return f"El negocio no atiende los {DIAS[dia_sem].lower()}"
    if inicio < neg['hora_apertura'] or inicio + duracion > neg['hora_cierre']:
        return f"Fuera del horario de atención ({hhmm(neg['hora_apertura'])} a {hhmm(neg['hora_cierre'])})"

    fin = inicio + duracion
    en_grupo = 0
    for e in ocurrencias(fecha, dia, profesional=prof['id'], excluir=excluir):
        if e['inicio'] < fin and inicio < e['inicio'] + e['duracion']:
            if e['servicio_id'] == servicio['id'] and e['inicio'] == inicio and e['duracion'] == duracion:
                en_grupo += 1
            else:
                return (f"{prof['nombre']} ya tiene {e['servicio_nombre']} de "
                        f"{hhmm(e['inicio'])} a {hhmm(e['inicio'] + e['duracion'])}")
    if en_grupo >= servicio['cupo']:
        return 'Ese horario ya está ocupado' if servicio['cupo'] == 1 else f"Cupo completo ({servicio['cupo']} personas)"

    for e in ocurrencias(fecha, dia, cliente=cliente_id, excluir=excluir):
        if e['inicio'] < fin and inicio < e['inicio'] + e['duracion']:
            return f"El cliente ya tiene {e['servicio_nombre']} a las {hhmm(e['inicio'])}"
    return None


def faltas_pendientes():
    """Turnos perdidos que todavía no se recuperaron. Admin ve todos; profesional, los suyos."""
    return query(
        f"""SELECT f.id, f.cliente_id, f.profesional_id, f.servicio_id, f.fecha, f.inicio,
                   c.nombre, c.apellido, c.telefono, p.nombre AS profesional_nombre,
                   s.nombre AS servicio_nombre, s.duracion
            FROM faltas f
            JOIN clientes c ON c.id = f.cliente_id
            JOIN profesionales p ON p.id = f.profesional_id
            JOIN servicios s ON s.id = f.servicio_id
            WHERE f.negocio_id=? AND c.activo=1 AND f.descartada=0
              AND NOT EXISTS (SELECT 1 FROM turnos t WHERE t.recupera_falta_id = f.id)
              {'' if es_admin() else 'AND f.profesional_id=?'}
            ORDER BY f.fecha, f.inicio""",
        (negocio_id(),) + (() if es_admin() else (profesional_id(),))
    )


def falta_editable(fid):
    return {f['id']: f for f in faltas_pendientes()}.get(parse_int(fid, -1))


def registrar_falta(db, turno, fecha):
    return db.execute(
        """INSERT INTO faltas (negocio_id, cliente_id, profesional_id, servicio_id, turno_id, fecha, inicio)
           VALUES (?,?,?,?,?,?,?)""",
        (turno['negocio_id'], turno['cliente_id'], turno['profesional_id'], turno['servicio_id'],
         turno['id'], fecha.isoformat(), turno['inicio'])
    ).lastrowid


def opciones_horario(neg):
    """Horarios ofrecidos en los formularios, cada `intervalo` minutos."""
    return list(range(neg['hora_apertura'], neg['hora_cierre'], neg['intervalo']))


# ============================================================
#  AUTH — REGISTRO / LOGIN / LOGOUT
# ============================================================
@app.route('/registro', methods=['GET', 'POST'])
def registro():
    error = None
    if request.method == 'POST':
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        nombre   = request.form.get('nombre_negocio', '').strip()
        tu_nombre = request.form.get('tu_nombre', '').strip() or nombre

        if not email or not password or not nombre:
            error = 'Todos los campos son obligatorios.'
        elif len(password) < 6:
            error = 'La contraseña debe tener al menos 6 caracteres.'
        elif (query("SELECT id FROM usuarios WHERE email=?", (email,), one=True)
              or query("SELECT id FROM profesionales WHERE email=?", (email,), one=True)):
            error = 'Ese email ya está registrado.'
        else:
            # Usuario + negocio + profesional admin + un servicio inicial, todo o nada
            db = get_db()
            with db:
                pw  = generate_password_hash(password)
                uid = db.execute("INSERT INTO usuarios (email, password) VALUES (?,?)", (email, pw)).lastrowid
                nid = db.execute("INSERT INTO negocios (user_id, nombre) VALUES (?,?)", (uid, nombre)).lastrowid
                db.execute(
                    "INSERT INTO profesionales (negocio_id, nombre, email, password, rol) VALUES (?,?,?,?,?)",
                    (nid, tu_nombre, email, pw, 'admin')
                )
                db.execute("INSERT INTO servicios (negocio_id, nombre, duracion, cupo, color) VALUES (?,?,?,?,?)",
                           (nid, 'Turno', 60, 1, 'verde'))
            flash('Cuenta creada. Ya podés ingresar.', 'success')
            return redirect(url_for('login'))

    return render_template('registro.html', error=error)


def iniciar_sesion(prof, demo=False):
    neg = query("SELECT * FROM negocios WHERE id=?", (prof['negocio_id'],), one=True)
    session.clear()
    session['profesional_id'] = prof['id']
    session['negocio_id']     = prof['negocio_id']
    session['nombre']         = prof['nombre']
    session['rol']            = prof['rol']
    session['logo']           = neg['logo_url'] if neg else None
    session['negocio_nombre'] = neg['nombre'] if neg else 'Mi negocio'
    session['demo']           = demo
    return redirect(url_for('agenda'))


def profesional_demo():
    return query("SELECT * FROM profesionales WHERE email=? AND activo=1", (DEMO_EMAIL,), one=True)


@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        prof = query("SELECT * FROM profesionales WHERE email=? AND activo=1", (email,), one=True)

        if prof and check_password_hash(prof['password'], password):
            return iniciar_sesion(prof, demo=email == DEMO_EMAIL)
        error = 'Email o contraseña incorrectos.'

    return render_template('login.html', error=error, hay_demo=profesional_demo() is not None)


@app.route('/demo', methods=['POST'])
def entrar_demo():
    """Entra directo al negocio de demostración, sin contraseña."""
    prof = profesional_demo()
    if not prof:
        flash('La demo no está disponible en este momento.', 'warning')
        return redirect(url_for('login'))
    return iniciar_sesion(prof, demo=True)


@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for('login'))


# ============================================================
#  NEGOCIO: datos, horario y servicios  (solo admin)
# ============================================================
@app.route('/negocio', methods=['GET', 'POST'])
@login_required
@admin_required
def negocio():
    neg = get_negocio()
    if request.method == 'POST':
        f = request.form
        nombre    = f.get('nombre', '').strip()
        apertura  = parse_hora(f.get('hora_apertura'))
        cierre    = parse_hora(f.get('hora_cierre'))
        intervalo = parse_int(f.get('intervalo'))
        dias      = sorted({d for d in (parse_int(x) for x in f.getlist('dias')) if d is not None and 0 <= d <= 6})
        logo_url  = neg['logo_url']

        if not nombre:
            flash('El nombre del negocio es obligatorio.', 'danger')
        elif apertura is None or cierre is None or apertura >= cierre:
            flash('El horario de cierre tiene que ser posterior al de apertura.', 'danger')
        elif intervalo not in (15, 30, 60):
            flash('Intervalo inválido.', 'danger')
        elif not dias:
            flash('Elegí al menos un día de atención.', 'danger')
        else:
            file = request.files.get('logo')
            if file and file.filename and session.get('demo'):
                flash('En la demo no se pueden subir imágenes; el resto se guardó.', 'warning')
                file = None
            if file and file.filename:
                if not allowed_file(file.filename):
                    flash('El logo tiene que ser una imagen (png, jpg, gif o webp).', 'danger')
                    return redirect(url_for('negocio'))
                ext = file.filename.rsplit('.', 1)[1].lower()
                filename = secure_filename(f"logo_{negocio_id()}_{secrets.token_hex(4)}.{ext}")
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                if logo_url and logo_url != filename:
                    anterior = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(logo_url))
                    if os.path.isfile(anterior):
                        os.remove(anterior)
                logo_url = filename
            execute(
                """UPDATE negocios SET nombre=?, logo_url=?, hora_apertura=?, hora_cierre=?, intervalo=?, dias=?
                   WHERE id=?""",
                (nombre, logo_url, apertura, cierre, intervalo, ','.join(map(str, dias)), negocio_id())
            )
            session['negocio_nombre'] = nombre
            session['logo'] = logo_url
            flash('Datos del negocio guardados.', 'success')
        return redirect(url_for('negocio'))

    servicios = query("SELECT * FROM servicios WHERE negocio_id=? ORDER BY activo DESC, nombre", (negocio_id(),))
    horas = list(range(0, 24 * 60 + 1, 30))
    return render_template('negocio.html', negocio=neg, servicios=servicios, horas=horas,
                           dias=DIAS, duraciones=DURACIONES, colores=COLORES)


def datos_servicio_form(f):
    nombre   = f.get('nombre', '').strip()[:60]
    duracion = parse_int(f.get('duracion'))
    cupo     = parse_int(f.get('cupo'), 1)
    color    = f.get('color') if f.get('color') in COLORES else 'verde'
    if not nombre:
        return None, 'El nombre del servicio es obligatorio.'
    if duracion is None or not 5 <= duracion <= 480:
        return None, 'Duración inválida.'
    if cupo is None or not 1 <= cupo <= 50:
        return None, 'El cupo tiene que ser entre 1 y 50.'
    return (nombre, duracion, cupo, color), None


@app.route('/servicio/agregar', methods=['POST'])
@login_required
@admin_required
def agregar_servicio():
    datos, error = datos_servicio_form(request.form)
    if error:
        flash(error, 'danger')
    else:
        execute("INSERT INTO servicios (negocio_id, nombre, duracion, cupo, color) VALUES (?,?,?,?,?)",
                (negocio_id(),) + datos)
        flash(f'Servicio "{datos[0]}" agregado.', 'success')
    return redirect(url_for('negocio') + '#servicios')


@app.route('/servicio/<int:sid>/editar', methods=['POST'])
@login_required
@admin_required
def editar_servicio(sid):
    datos, error = datos_servicio_form(request.form)
    if error:
        flash(error, 'danger')
    else:
        # Los turnos ya agendados conservan su duración; el cambio aplica a los nuevos
        execute("UPDATE servicios SET nombre=?, duracion=?, cupo=?, color=? WHERE id=? AND negocio_id=?",
                datos + (sid, negocio_id()))
        flash('Servicio actualizado. Los turnos ya agendados mantienen su duración.', 'success')
    return redirect(url_for('negocio') + '#servicios')


@app.route('/servicio/<int:sid>/activo', methods=['POST'])
@login_required
@admin_required
def activar_servicio(sid):
    activo = 1 if request.form.get('activo') == '1' else 0
    if not activo and query("SELECT COUNT(*) AS c FROM servicios WHERE negocio_id=? AND activo=1 AND id!=?",
                            (negocio_id(), sid), one=True)['c'] == 0:
        flash('Tiene que quedar al menos un servicio activo.', 'warning')
    else:
        execute("UPDATE servicios SET activo=? WHERE id=? AND negocio_id=?", (activo, sid, negocio_id()))
        flash('Servicio ' + ('reactivado.' if activo else 'desactivado: ya no se ofrece para turnos nuevos.'), 'success')
    return redirect(url_for('negocio') + '#servicios')


# ============================================================
#  EQUIPO  (solo admin)
# ============================================================
@app.route('/equipo')
@login_required
@admin_required
def equipo():
    lista = query("SELECT * FROM profesionales WHERE negocio_id=? ORDER BY activo DESC, nombre", (negocio_id(),))
    return render_template('equipo.html', profesionales=lista)


@app.route('/profesional/agregar', methods=['POST'])
@login_required
@admin_required
def agregar_profesional():
    nombre   = request.form.get('nombre', '').strip()
    email    = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '')
    rol      = request.form.get('rol', 'profesional')

    if not nombre or not email:
        flash('Nombre y email son obligatorios.', 'danger')
    elif len(password) < 6:
        flash('La contraseña debe tener al menos 6 caracteres.', 'danger')
    elif rol not in ('admin', 'profesional'):
        flash('Rol inválido.', 'danger')
    elif query("SELECT id FROM profesionales WHERE email=?", (email,), one=True):
        flash('Ya existe alguien con ese email.', 'danger')
    else:
        execute("INSERT INTO profesionales (negocio_id, nombre, email, password, rol) VALUES (?,?,?,?,?)",
                (negocio_id(), nombre, email, generate_password_hash(password), rol))
        flash(f'{nombre} fue agregado al equipo.', 'success')
    return redirect(url_for('equipo'))


@app.route('/profesional/<int:pid>/editar', methods=['POST'])
@login_required
@admin_required
def editar_profesional(pid):
    nombre   = request.form.get('nombre', '').strip()
    rol      = request.form.get('rol', 'profesional')
    password = request.form.get('password', '').strip()

    actual = query("SELECT * FROM profesionales WHERE id=? AND negocio_id=?", (pid, negocio_id()), one=True)
    if not actual:
        return redirect(url_for('equipo'))
    if pid == profesional_id():
        rol = actual['rol']   # nadie puede cambiarse su propio rol
    if not nombre or rol not in ('admin', 'profesional'):
        flash('Datos inválidos.', 'danger')
    elif password and len(password) < 6:
        flash('La contraseña debe tener al menos 6 caracteres.', 'danger')
    else:
        if password:
            execute("UPDATE profesionales SET nombre=?, rol=?, password=? WHERE id=? AND negocio_id=?",
                    (nombre, rol, generate_password_hash(password), pid, negocio_id()))
        else:
            execute("UPDATE profesionales SET nombre=?, rol=? WHERE id=? AND negocio_id=?",
                    (nombre, rol, pid, negocio_id()))
        if pid == profesional_id():
            session['nombre'] = nombre
        flash('Datos actualizados.', 'success')
    return redirect(url_for('equipo'))


@app.route('/profesional/<int:pid>/activo', methods=['POST'])
@login_required
@admin_required
def activar_profesional(pid):
    activo = 1 if request.form.get('activo') == '1' else 0
    if pid != profesional_id():   # nadie se desactiva a sí mismo
        execute("UPDATE profesionales SET activo=? WHERE id=? AND negocio_id=?", (activo, pid, negocio_id()))
        flash('Reactivado.' if activo else 'Desactivado: ya no puede ingresar.', 'success')
    return redirect(url_for('equipo'))


# ============================================================
#  AGENDA  (pantalla principal)
# ============================================================
def ubicar_en_carriles(bloques):
    """Asigna carril a cada bloque para mostrar lado a lado los que se superponen."""
    bloques.sort(key=lambda b: (b['inicio'], -b['duracion']))
    grupo, fin_grupo, carriles = [], -1, []
    for b in bloques + [None]:
        if b is None or b['inicio'] >= fin_grupo:
            for x in grupo:
                x['carriles'] = len(carriles)
            if b is None:
                break
            grupo, carriles = [], []
        libre = next((i for i, fin in enumerate(carriles) if fin <= b['inicio']), None)
        if libre is None:
            carriles.append(0)
            libre = len(carriles) - 1
        carriles[libre] = b['inicio'] + b['duracion']
        b['carril'] = libre
        grupo.append(b)
        fin_grupo = max(fin_grupo, b['inicio'] + b['duracion'])
    return bloques


def turnos_del_dia(fecha):
    """Turnos que ocurren en una fecha, con cliente, servicio y profesional, ordenados por hora."""
    return query(
        f"""SELECT t.id, t.tipo, t.inicio, t.duracion, t.recupera_falta_id, t.cliente_id, t.profesional_id,
                   c.nombre, c.apellido, c.telefono, c.creado_en,
                   s.nombre AS servicio_nombre, p.nombre AS profesional_nombre
            FROM turnos t
            JOIN clientes c ON c.id = t.cliente_id
            JOIN servicios s ON s.id = t.servicio_id
            JOIN profesionales p ON p.id = t.profesional_id
            WHERE t.negocio_id=? AND c.activo=1
              AND ((t.tipo='puntual' AND t.fecha=?)
                   OR (t.tipo='fijo' AND t.dia_semana=? AND NOT EXISTS (
                          SELECT 1 FROM turnos_excepciones e WHERE e.turno_id=t.id AND e.fecha=?)))
              {'' if es_admin() else 'AND t.profesional_id=?'}
            ORDER BY t.inicio, c.apellido, c.nombre""",
        (negocio_id(), fecha.isoformat(), fecha.weekday(), fecha.isoformat())
        + (() if es_admin() else (profesional_id(),))
    )


def armar_resumen(momento):
    """Resumen de hoy y lista del próximo día de atención (para mandar recordatorios)."""
    neg = get_negocio()
    hoy_f = momento.date()
    min_ahora = momento.hour * 60 + momento.minute
    lista = [dict(t) for t in turnos_del_dia(hoy_f)]

    nuevos_desde = (hoy_f - timedelta(days=14)).isoformat()
    por_prof = {}
    for t in lista:
        por_prof[t['profesional_nombre']] = por_prof.get(t['profesional_nombre'], 0) + 1
    proximo = next((t for t in lista if t['inicio'] + t['duracion'] > min_ahora), None)
    faltas = query(
        f"""SELECT c.nombre, c.apellido FROM faltas f JOIN clientes c ON c.id = f.cliente_id
            WHERE f.negocio_id=? AND f.fecha=? {'' if es_admin() else 'AND f.profesional_id=?'}
            ORDER BY f.inicio""",
        (negocio_id(), hoy_f.isoformat()) + (() if es_admin() else (profesional_id(),))
    )

    # Próximo día que el negocio atiende (para los recordatorios)
    siguiente = next((hoy_f + timedelta(days=i) for i in range(1, 8)
                      if (hoy_f + timedelta(days=i)).weekday() in neg['dias_lista']), None)

    return {
        'fecha': hoy_f,
        'abierto': hoy_f.weekday() in neg['dias_lista'],
        'total': len(lista),
        'por_prof': sorted(por_prof.items()) if len(por_prof) > 1 else [],
        'quedan': sum(1 for t in lista if t['inicio'] >= min_ahora),
        'proximo': proximo,
        'en_curso': bool(proximo and proximo['inicio'] <= min_ahora),
        'nuevos': [t for t in lista if (t['creado_en'] or '')[:10] >= nuevos_desde],
        'recuperaciones': sum(1 for t in lista if t['recupera_falta_id']),
        'faltas': faltas,
        'siguiente': siguiente,
        'siguiente_es_manana': siguiente == hoy_f + timedelta(days=1) if siguiente else False,
        'siguiente_turnos': [dict(t) for t in turnos_del_dia(siguiente)] if siguiente else [],
    }


@app.route('/')
@app.route('/agenda')
@login_required
def agenda():
    nid = negocio_id()
    pid = profesional_id()
    neg = get_negocio()
    momento = ahora()
    dia_hoy = momento.date()

    fecha_ref = parse_fecha(request.args.get('fecha')) or dia_hoy
    inicio_sem = fecha_ref - timedelta(days=fecha_ref.weekday())
    fechas = [inicio_sem + timedelta(days=i) for i in range(7)]
    dias_vis = [d for d in range(7) if d in neg['dias_lista']]

    cond_prof = "" if es_admin() else "AND t.profesional_id=?"
    args_prof = () if es_admin() else (pid,)
    columnas = """t.*, c.nombre, c.apellido, c.telefono, p.nombre AS profesional_nombre,
                  s.nombre AS servicio_nombre, s.cupo, s.color"""
    joins = """JOIN clientes c ON c.id = t.cliente_id
               JOIN profesionales p ON p.id = t.profesional_id
               JOIN servicios s ON s.id = t.servicio_id"""

    fijos = query(f"SELECT {columnas} FROM turnos t {joins} WHERE t.negocio_id=? AND t.tipo='fijo' AND c.activo=1 {cond_prof}",
                  (nid,) + args_prof)
    puntuales = query(
        f"""SELECT {columnas} FROM turnos t {joins}
            WHERE t.negocio_id=? AND t.tipo='puntual' AND c.activo=1 AND t.fecha BETWEEN ? AND ? {cond_prof}""",
        (nid, fechas[0].isoformat(), fechas[-1].isoformat()) + args_prof
    )
    excepciones = {(e['turno_id'], e['fecha']) for e in query(
        """SELECT e.turno_id, e.fecha FROM turnos_excepciones e JOIN turnos t ON t.id = e.turno_id
           WHERE t.negocio_id=? AND e.fecha BETWEEN ? AND ?""",
        (nid, fechas[0].isoformat(), fechas[-1].isoformat())
    )}

    pendientes = [dict(f) for f in faltas_pendientes()]
    pend_por_cliente = {}
    for f in pendientes:
        pend_por_cliente[f['cliente_id']] = pend_por_cliente.get(f['cliente_id'], 0) + 1

    # Ocurrencias de la semana agrupadas en bloques: mismo profesional, servicio y horario
    # (un bloque con varias personas = clase grupal)
    bloques = {d: {} for d in range(7)}

    def agregar(t, d):
        fecha = fechas[d]
        clave = (t['profesional_id'], t['servicio_id'], t['inicio'], t['duracion'])
        b = bloques[d].setdefault(clave, {
            'inicio': t['inicio'], 'duracion': t['duracion'],
            'profesional_id': t['profesional_id'], 'profesional_nombre': t['profesional_nombre'],
            'servicio_nombre': t['servicio_nombre'], 'cupo': t['cupo'],
            'fondo': COLORES.get(t['color'], COLORES['verde'])[0],
            'borde': COLORES.get(t['color'], COLORES['verde'])[1],
            'turnos': [],
        })
        item = dict(t)
        item['fecha_turno'] = fecha.isoformat()
        item['pend'] = pend_por_cliente.get(t['cliente_id'], 0)
        b['turnos'].append(item)

    for t in fijos:
        d = t['dia_semana']
        if d in dias_vis and (t['id'], fechas[d].isoformat()) not in excepciones:
            agregar(t, d)
    for t in puntuales:
        f = parse_fecha(t['fecha'])
        if f and f.weekday() in dias_vis:
            agregar(t, f.weekday())

    apertura, cierre = neg['hora_apertura'], neg['hora_cierre']
    por_dia, cantidad = {}, {}
    for d in dias_vis:
        visibles = [b for b in bloques[d].values()
                    if b['inicio'] < cierre and b['inicio'] + b['duracion'] > apertura]
        for b in visibles:
            b['turnos'].sort(key=lambda t: (t['apellido'].lower(), t['nombre'].lower()))
        por_dia[d] = ubicar_en_carriles(visibles)
        cantidad[d] = sum(len(b['turnos']) for b in visibles)

    clientes = query("SELECT id, nombre, apellido, telefono FROM clientes WHERE negocio_id=? AND activo=1 ORDER BY apellido, nombre", (nid,))
    servicios = query("SELECT * FROM servicios WHERE negocio_id=? AND activo=1 ORDER BY nombre", (nid,))
    profesionales = query("SELECT id, nombre FROM profesionales WHERE negocio_id=? AND activo=1 ORDER BY nombre", (nid,)) \
        if es_admin() else []

    return render_template('agenda.html',
        por_dia=por_dia, cantidad=cantidad,
        dias_vis=dias_vis, fechas=fechas, hoy=dia_hoy,
        resumen=armar_resumen(momento) if fechas[0] <= dia_hoy <= fechas[6] else None,
        inicio=fechas[0], fin=fechas[dias_vis[-1]] if dias_vis else fechas[-1],
        dias=DIAS, dias_corto=DIAS_CORTO,
        apertura=apertura, cierre=cierre, intervalo=neg['intervalo'],
        clientes=clientes, servicios=servicios, profesionales=profesionales,
        pendientes=pendientes,
        semana_anterior=(fechas[0] - timedelta(days=7)).isoformat(),
        semana_siguiente=(fechas[0] + timedelta(days=7)).isoformat(),
        es_admin=es_admin(),
        multi=es_admin() and len(profesionales) > 1,
        mi_profesional_id=pid,
    )


@app.route('/agregar_turno', methods=['POST'])
@login_required
def agregar_turno():
    f         = request.form
    fecha_ref = f.get('fecha_ref', '')

    def volver(fecha=None):
        destino = fecha or (fecha_ref if parse_fecha(fecha_ref) else None)
        return redirect(url_for('agenda', fecha=destino) if destino else url_for('agenda'))

    servicio = servicio_del_negocio(f.get('servicio_id'))
    prof     = profesional_del_negocio(f.get('profesional_id') if es_admin() else profesional_id())
    tipo     = f.get('tipo', 'puntual')
    inicio   = parse_hora(f.get('inicio'))

    # Cliente existente o nuevo (se crea en el momento con nombre y teléfono)
    cliente = None
    nuevo_nombre = f.get('nuevo_nombre', '').strip()
    if f.get('cliente_id') == 'nuevo':
        if not nuevo_nombre:
            flash('Escribí el nombre del cliente nuevo.', 'danger')
            return volver()
    else:
        cliente = cliente_del_negocio(f.get('cliente_id'))
        if not cliente:
            flash('Elegí un cliente.', 'danger')
            return volver()

    if not servicio:
        flash('Elegí un servicio.', 'danger')
        return volver()
    if not prof:
        flash('Elegí un profesional.', 'danger')
        return volver()
    if inicio is None or tipo not in ('fijo', 'puntual'):
        flash('Horario inválido.', 'danger')
        return volver()

    fecha, dia = None, None
    if tipo == 'fijo':
        dia = parse_int(f.get('dia_semana'))
        if dia is None or not 0 <= dia <= 6:
            flash('Día inválido.', 'danger')
            return volver()
    else:
        fecha = parse_fecha(f.get('fecha'))
        if not fecha:
            flash('Fecha inválida.', 'danger')
            return volver()

    error = validar_horario(prof, cliente['id'] if cliente else -1, servicio, inicio,
                            servicio['duracion'], fecha=fecha, dia=dia)
    if error:
        flash(error, 'warning')
        return volver()

    db = get_db()
    with db:
        if cliente is None:
            cid = db.execute(
                "INSERT INTO clientes (negocio_id, nombre, apellido, telefono) VALUES (?,?,?,?)",
                (negocio_id(), nuevo_nombre[:60], f.get('nuevo_apellido', '').strip()[:60],
                 f.get('nuevo_telefono', '').strip()[:30] or None)
            ).lastrowid
        else:
            cid = cliente['id']
        db.execute(
            """INSERT INTO turnos (negocio_id, profesional_id, cliente_id, servicio_id, tipo, dia_semana, fecha, inicio, duracion)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (negocio_id(), prof['id'], cid, servicio['id'], tipo, dia,
             fecha.isoformat() if fecha else None, inicio, servicio['duracion'])
        )
    return volver(fecha.isoformat() if fecha else None)


@app.route('/mover_turno', methods=['POST'])
@login_required
def mover_turno():
    """
    Mueve un turno a otra fecha/hora conservando su duración.
    Fijo + 'siempre' → cambia día y hora de todas las semanas.
    Fijo + 'semana'  → solo esa semana: se saltea la fecha original (queda como falta
                       ya recuperada) y se crea un turno puntual en el destino.
    """
    data   = request.get_json(silent=True) or {}
    turno  = turno_editable(data.get('id'))
    inicio = parse_hora(data.get('inicio'))
    fecha  = parse_fecha(data.get('fecha'))
    modo   = data.get('modo', 'siempre')

    if not turno:
        return jsonify({'ok': False, 'error': 'No autorizado'}), 403
    if inicio is None or not fecha:
        return jsonify({'ok': False, 'error': 'Horario inválido'}), 400

    prof     = query("SELECT * FROM profesionales WHERE id=?", (turno['profesional_id'],), one=True)
    servicio = query("SELECT * FROM servicios WHERE id=?", (turno['servicio_id'],), one=True)
    tid, dur = turno['id'], turno['duracion']

    if turno['tipo'] == 'fijo' and modo == 'semana':
        origen = parse_fecha(data.get('fecha_origen'))
        if not origen or origen.weekday() != turno['dia_semana']:
            return jsonify({'ok': False, 'error': 'Fecha de origen inválida'}), 400
        if origen == fecha and inicio == turno['inicio']:
            return jsonify({'ok': True})
        error = validar_horario(prof, turno['cliente_id'], servicio, inicio, dur, fecha=fecha, excluir=tid)
        if error:
            return jsonify({'ok': False, 'error': error}), 409
        db = get_db()
        with db:
            db.execute("INSERT OR IGNORE INTO turnos_excepciones (turno_id, fecha) VALUES (?,?)", (tid, origen.isoformat()))
            fid = registrar_falta(db, turno, origen)
            db.execute(
                """INSERT INTO turnos (negocio_id, profesional_id, cliente_id, servicio_id, tipo, fecha, inicio, duracion, recupera_falta_id)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (turno['negocio_id'], turno['profesional_id'], turno['cliente_id'], turno['servicio_id'],
                 'puntual', fecha.isoformat(), inicio, dur, fid)
            )
    elif turno['tipo'] == 'fijo':
        dia = fecha.weekday()
        if dia == turno['dia_semana'] and inicio == turno['inicio']:
            return jsonify({'ok': True})
        error = validar_horario(prof, turno['cliente_id'], servicio, inicio, dur, dia=dia, excluir=tid)
        if error:
            return jsonify({'ok': False, 'error': error}), 409
        execute("UPDATE turnos SET dia_semana=?, inicio=? WHERE id=?", (dia, inicio, tid))
    else:
        error = validar_horario(prof, turno['cliente_id'], servicio, inicio, dur, fecha=fecha, excluir=tid)
        if error:
            return jsonify({'ok': False, 'error': error}), 409
        execute("UPDATE turnos SET fecha=?, inicio=? WHERE id=?", (fecha.isoformat(), inicio, tid))

    return jsonify({'ok': True})


@app.route('/quitar_turno', methods=['POST'])
@login_required
def quitar_turno():
    """Fijo + 'semana' → solo se saltea esa fecha y queda para recuperar. Si no, se borra el turno."""
    data  = request.get_json(silent=True) or {}
    turno = turno_editable(data.get('id'))
    if not turno:
        return jsonify({'ok': False, 'error': 'No autorizado'}), 403

    if turno['tipo'] == 'fijo' and data.get('modo') == 'semana':
        fecha = parse_fecha(data.get('fecha'))
        if not fecha or fecha.weekday() != turno['dia_semana']:
            return jsonify({'ok': False, 'error': 'Fecha inválida'}), 400
        db = get_db()
        with db:
            nueva = db.execute("INSERT OR IGNORE INTO turnos_excepciones (turno_id, fecha) VALUES (?,?)",
                               (turno['id'], fecha.isoformat())).rowcount
            if nueva:
                registrar_falta(db, turno, fecha)
    else:
        execute("DELETE FROM turnos WHERE id=?", (turno['id'],))
    return jsonify({'ok': True})


# ============================================================
#  RECUPERACIONES
# ============================================================
@app.route('/recuperar', methods=['POST'])
@login_required
def recuperar():
    data   = request.get_json(silent=True) or {}
    falta  = falta_editable(data.get('falta_id'))
    inicio = parse_hora(data.get('inicio'))
    fecha  = parse_fecha(data.get('fecha'))

    if not falta:
        return jsonify({'ok': False, 'error': 'Ese turno ya no está pendiente de recuperar'}), 404
    if inicio is None or not fecha:
        return jsonify({'ok': False, 'error': 'Horario inválido'}), 400
    prof = profesional_del_negocio(falta['profesional_id'])
    if not prof:
        return jsonify({'ok': False, 'error': 'El profesional de ese turno está inactivo'}), 409
    servicio = query("SELECT * FROM servicios WHERE id=?", (falta['servicio_id'],), one=True)
    error = validar_horario(prof, falta['cliente_id'], servicio, inicio, servicio['duracion'], fecha=fecha)
    if error:
        return jsonify({'ok': False, 'error': error}), 409

    execute(
        """INSERT INTO turnos (negocio_id, profesional_id, cliente_id, servicio_id, tipo, fecha, inicio, duracion, recupera_falta_id)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (negocio_id(), prof['id'], falta['cliente_id'], servicio['id'], 'puntual',
         fecha.isoformat(), inicio, servicio['duracion'], falta['id'])
    )
    return jsonify({'ok': True})


@app.route('/descartar_falta', methods=['POST'])
@login_required
def descartar_falta():
    falta = falta_editable((request.get_json(silent=True) or {}).get('falta_id'))
    if not falta:
        return jsonify({'ok': False, 'error': 'Ese turno ya no está pendiente'}), 404
    execute("UPDATE faltas SET descartada=1 WHERE id=?", (falta['id'],))
    return jsonify({'ok': True})


@app.route('/anular_falta', methods=['POST'])
@login_required
def anular_falta():
    """La falta se marcó por error: se borra y el cliente vuelve a tener ese turno."""
    falta = falta_editable((request.get_json(silent=True) or {}).get('falta_id'))
    if not falta:
        return jsonify({'ok': False, 'error': 'Ese turno ya no está pendiente'}), 404
    origen = query("SELECT turno_id FROM faltas WHERE id=?", (falta['id'],), one=True)['turno_id']
    db = get_db()
    with db:
        if origen:
            db.execute("DELETE FROM turnos_excepciones WHERE turno_id=? AND fecha=?", (origen, falta['fecha']))
        db.execute("DELETE FROM faltas WHERE id=?", (falta['id'],))
    return jsonify({'ok': True})


# ============================================================
#  CLIENTES
# ============================================================
@app.route('/clientes')
@login_required
def clientes():
    nid    = negocio_id()
    buscar = request.args.get('q', '').strip()
    if buscar:
        patron = f'%{buscar}%'
        lista = query(
            """SELECT * FROM clientes WHERE negocio_id=? AND activo=1
               AND (nombre LIKE ? OR apellido LIKE ? OR telefono LIKE ?)
               ORDER BY apellido, nombre""",
            (nid, patron, patron, patron)
        )
    else:
        lista = query("SELECT * FROM clientes WHERE negocio_id=? AND activo=1 ORDER BY apellido, nombre", (nid,))

    # Turnos fijos y próximo turno suelto de cada cliente
    fijos = {}
    for t in query("""SELECT t.cliente_id, t.dia_semana, t.inicio, s.nombre AS servicio FROM turnos t
                      JOIN servicios s ON s.id = t.servicio_id
                      WHERE t.negocio_id=? AND t.tipo='fijo' ORDER BY t.dia_semana, t.inicio""", (nid,)):
        fijos.setdefault(t['cliente_id'], []).append(f"{DIAS_CORTO[t['dia_semana']]} {hhmm(t['inicio'])} · {t['servicio']}")
    proximos = {}
    for t in query("""SELECT t.cliente_id, t.fecha, t.inicio, s.nombre AS servicio FROM turnos t
                      JOIN servicios s ON s.id = t.servicio_id
                      WHERE t.negocio_id=? AND t.tipo='puntual' AND t.fecha >= ?
                      ORDER BY t.fecha, t.inicio""", (nid, hoy().isoformat())):
        if t['cliente_id'] not in proximos:
            f = parse_fecha(t['fecha'])
            proximos[t['cliente_id']] = f"{DIAS_CORTO[f.weekday()]} {f.strftime('%d/%m')} {hhmm(t['inicio'])} · {t['servicio']}"
    por_recuperar = {}
    for f in faltas_pendientes():
        por_recuperar[f['cliente_id']] = por_recuperar.get(f['cliente_id'], 0) + 1

    return render_template('clientes.html', clientes=lista, buscar=buscar,
                           fijos=fijos, proximos=proximos, por_recuperar=por_recuperar)


def datos_cliente_form(f):
    def txt(campo, largo):
        return (f.get(campo, '').strip()[:largo]) or None
    return (f.get('nombre', '').strip()[:60], f.get('apellido', '').strip()[:60],
            txt('telefono', 30), txt('email', 120), txt('notas', 2000))


@app.route('/cliente/agregar', methods=['POST'])
@login_required
def agregar_cliente():
    datos = datos_cliente_form(request.form)
    if not datos[0]:
        flash('El nombre es obligatorio.', 'danger')
    else:
        execute("INSERT INTO clientes (negocio_id, nombre, apellido, telefono, email, notas) VALUES (?,?,?,?,?,?)",
                (negocio_id(),) + datos)
        flash(f'{datos[0]} {datos[1]} fue registrado.', 'success')
    return redirect(url_for('clientes'))


@app.route('/cliente/<int:cid>/editar', methods=['POST'])
@login_required
def editar_cliente(cid):
    datos = datos_cliente_form(request.form)
    if not datos[0]:
        flash('El nombre es obligatorio.', 'danger')
    else:
        execute("UPDATE clientes SET nombre=?, apellido=?, telefono=?, email=?, notas=? WHERE id=? AND negocio_id=?",
                datos + (cid, negocio_id()))
        flash('Datos del cliente guardados.', 'success')
    return redirect(url_for('clientes'))


@app.route('/cliente/<int:cid>/baja', methods=['POST'])
@login_required
def baja_cliente(cid):
    cliente = cliente_del_negocio(cid)
    if cliente:
        db = get_db()
        with db:
            db.execute("UPDATE clientes SET activo=0 WHERE id=?", (cid,))
            db.execute("DELETE FROM turnos WHERE cliente_id=? AND negocio_id=?", (cid, negocio_id()))
        flash(f"{cliente['nombre']} {cliente['apellido']} fue dado de baja y se liberaron sus turnos.", 'success')
    return redirect(url_for('clientes'))


# ============================================================
#  AYUDA
# ============================================================
@app.route('/ayuda')
@login_required
def ayuda():
    return render_template('ayuda.html', es_admin=es_admin(), version=VERSION)


# ============================================================
#  INICIO
# ============================================================
preparar_db()

if __name__ == '__main__':
    port  = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG') == '1'   # el debugger solo si se pide explícitamente
    app.run(host=os.environ.get('HOST', '0.0.0.0'), port=port, debug=debug)
