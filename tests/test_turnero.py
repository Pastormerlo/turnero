"""
Pruebas de punta a punta de Turnero sobre una base temporal (no toca turnero.db).
Uso:  python tests/test_turnero.py
"""
import os, re, sys, json, sqlite3, tempfile
from datetime import date, timedelta

PROY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
db_path = os.path.join(tempfile.gettempdir(), 'turnero_test.db')
if os.path.exists(db_path):
    os.remove(db_path)
os.environ['DATABASE_PATH'] = db_path
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, PROY)
import app as A
A.app.config['TESTING'] = True

fallas = 0
def check(cond, msg):
    global fallas
    print(('  OK  ' if cond else '  FALLA ') + msg)
    if not cond:
        fallas += 1

def token(c, url='/login'):
    html = c.get(url).get_data(as_text=True)
    m = re.search(r'name="csrf-token" content="([^"]+)"', html) or re.search(r'name="_csrf" value="([^"]+)"', html)
    return m.group(1)

def db():
    con = sqlite3.connect(db_path); con.row_factory = sqlite3.Row; return con

def uno(sql, args=()):
    return db().execute(sql, args).fetchone()[0]

def nuevo_cliente(c, t, nombre, tel='11 4408-1508'):
    c.post('/cliente/agregar', data={'_csrf': t, 'nombre': nombre, 'apellido': 'Test', 'telefono': tel})
    return uno("select max(id) from clientes")

def turno(c, t, **kw):
    datos = {'_csrf': t, 'tipo': 'puntual'}
    datos.update({k: str(v) for k, v in kw.items()})
    c.post('/agregar_turno', data=datos)

def flashes(c):
    with c.session_transaction() as s:
        return [m for _, m in s.get('_flashes', [])]

# ── registro y login ──
c = A.app.test_client()
t = token(c, '/registro')
c.post('/registro', data={'_csrf': t, 'email': 'dueno@x.com', 'password': '123456', 'nombre_negocio': "Bienestar O'Hara", 'tu_nombre': 'Laura'})
check(uno("select count(*) from servicios") == 1, 'registro crea un servicio inicial')
check(uno("select nombre from profesionales") == 'Laura', 'registro usa "tu nombre" para el profesional')
r = c.post('/login', data={'email': 'dueno@x.com', 'password': '123456'})
check('/login' in r.headers['Location'], 'login sin CSRF rechazado')
t = token(c)
r = c.post('/login', data={'_csrf': t, 'email': 'dueno@x.com', 'password': '123456'})
check(r.headers['Location'].endswith('/agenda'), 'login ok')
t = token(c, '/agenda')
check(c.get('/').status_code == 200, 'agenda vacía se muestra')

# ── configuración ──
r = c.post('/negocio', data={'_csrf': t, 'nombre': 'Bienestar', 'hora_apertura': '540', 'hora_cierre': '1200',
                             'intervalo': '15', 'dias': ['0', '1', '2', '3', '4', '5']})
check(db().execute("select hora_apertura, hora_cierre, dias from negocios").fetchone()[:] == (540, 1200, '0,1,2,3,4,5'), 'guardar horario 09:00–20:00, lun a sáb')
c.post('/negocio', data={'_csrf': t, 'nombre': 'X', 'hora_apertura': '600', 'hora_cierre': '540', 'intervalo': '15', 'dias': ['0']})
check(uno("select hora_apertura from negocios") == 540, 'cierre antes de apertura → rechazado')
c.post('/servicio/agregar', data={'_csrf': t, 'nombre': 'Masaje', 'duracion': '60', 'cupo': '1', 'color': 'verde'})
c.post('/servicio/agregar', data={'_csrf': t, 'nombre': 'Cejas', 'duracion': '15', 'cupo': '1', 'color': 'rosa'})
c.post('/servicio/agregar', data={'_csrf': t, 'nombre': 'Clase', 'duracion': '60', 'cupo': '3', 'color': 'violeta'})
c.post('/servicio/agregar', data={'_csrf': t, 'nombre': 'Malo', 'duracion': '999', 'cupo': '1'})
check(uno("select count(*) from servicios") == 4, 'servicios agregados (duración inválida rechazada)')
MASAJE = uno("select id from servicios where nombre='Masaje'")
CEJAS = uno("select id from servicios where nombre='Cejas'")
CLASE = uno("select id from servicios where nombre='Clase'")
c.post('/profesional/agregar', data={'_csrf': t, 'nombre': 'Martín', 'email': 'martin@x.com', 'password': '123456', 'rol': 'profesional'})
YO = uno("select id from profesionales where email='dueno@x.com'")
MARTIN = uno("select id from profesionales where email='martin@x.com'")

hoy = date.today()
lunes = hoy - timedelta(days=hoy.weekday()) + timedelta(days=7)   # semana próxima
martes, jueves, domingo = lunes + timedelta(days=1), lunes + timedelta(days=3), lunes + timedelta(days=6)

# ── agendar y superposiciones ──
ana = nuevo_cliente(c, t, 'Ana')
beto = nuevo_cliente(c, t, 'Beto')
turno(c, t, cliente_id=ana, servicio_id=MASAJE, profesional_id=YO, fecha=lunes.isoformat(), inicio=600)
check(uno("select count(*) from turnos") == 1, 'masaje lunes 10:00–11:00')
turno(c, t, cliente_id=beto, servicio_id=MASAJE, profesional_id=YO, fecha=lunes.isoformat(), inicio=630)
check(uno("select count(*) from turnos") == 1, 'masaje 10:30 con la misma profesional → rechazado (se superpone)')
check(any('ya tiene Masaje de 10:00 a 11:00' in m for m in flashes(c)), '  → el aviso explica el choque')
turno(c, t, cliente_id=beto, servicio_id=CEJAS, profesional_id=YO, fecha=lunes.isoformat(), inicio=660)
check(uno("select count(*) from turnos") == 2, 'cejas 11:00 justo al terminar → ok')
turno(c, t, cliente_id=beto, servicio_id=MASAJE, profesional_id=MARTIN, fecha=lunes.isoformat(), inicio=600)
check(uno("select count(*) from turnos") == 3, 'mismo horario con otro profesional → ok')
turno(c, t, cliente_id=ana, servicio_id=CEJAS, profesional_id=MARTIN, fecha=lunes.isoformat(), inicio=645)
check(uno("select count(*) from turnos") == 3, 'cliente con otro turno superpuesto → rechazado')
turno(c, t, cliente_id=ana, servicio_id=MASAJE, profesional_id=YO, fecha=lunes.isoformat(), inicio=1170)
check(uno("select count(*) from turnos") == 3, 'masaje 19:30 que termina 20:30 (fuera de horario) → rechazado')
turno(c, t, cliente_id=ana, servicio_id=CEJAS, profesional_id=YO, fecha=domingo.isoformat(), inicio=600)
check(uno("select count(*) from turnos") == 3, 'domingo (cerrado) → rechazado')
turno(c, t, cliente_id='nuevo', nuevo_nombre='Carla', nuevo_telefono='351 512 3456', servicio_id=CEJAS, profesional_id=YO, fecha=martes.isoformat(), inicio=540)
check(uno("select count(*) from clientes where nombre='Carla'") == 1 and uno("select count(*) from turnos") == 4, 'cliente nuevo creado al agendar')
turno(c, t, cliente_id='nuevo', nuevo_nombre='Dora', servicio_id=CEJAS, profesional_id=YO, fecha=martes.isoformat(), inicio=540)
check(uno("select count(*) from clientes where nombre='Dora'") == 0, '  → si el turno falla, no queda el cliente nuevo a medias')

# clase grupal: cupo 3
alumnos = [nuevo_cliente(c, t, f'Grupo{i}') for i in range(4)]
for a in alumnos:
    turno(c, t, cliente_id=a, servicio_id=CLASE, profesional_id=MARTIN, tipo='fijo', dia_semana=3, inicio=1080)
check(uno("select count(*) from turnos where servicio_id=?", (CLASE,)) == 3, 'clase grupal fija: entran 3, el 4º se rechaza')
check(any('Cupo completo' in m for m in flashes(c)), '  → aviso de cupo completo')
turno(c, t, cliente_id=alumnos[3], servicio_id=CLASE, profesional_id=MARTIN, tipo='fijo', dia_semana=3, inicio=1110)
check(uno("select count(*) from turnos where servicio_id=? and cliente_id=?", (CLASE, alumnos[3])) == 0, 'otra clase superpuesta (18:30) con el mismo profesional → rechazada')

html = c.get(f'/agenda?fecha={lunes.isoformat()}').get_data(as_text=True)
check('18:00 · 3/3 · MA · Clase' in html, 'agenda muestra la clase grupal como un bloque 3/3')
check('--carriles:2' in html, 'turnos simultáneos de dos profesionales van lado a lado')
check("Bienestar" in html, 'nombre del negocio en la agenda')

# ── mover ──
H = {'X-CSRFToken': t}
t_ana = uno("select id from turnos where cliente_id=? and servicio_id=?", (ana, MASAJE))
r = c.post('/mover_turno', json={'id': t_ana, 'fecha': martes.isoformat(), 'inicio': 600}, headers=H)
check(r.get_json()['ok'] and db().execute("select fecha, inicio, duracion from turnos where id=?", (t_ana,)).fetchone()[:] == (martes.isoformat(), 600, 60), 'mover masaje al martes 10:00 conserva 60 min')
r = c.post('/mover_turno', json={'id': t_ana, 'fecha': martes.isoformat(), 'inicio': 525}, headers=H)
check(r.status_code == 409, 'mover a 08:45 (antes de abrir) → rechazado')
r = c.post('/mover_turno', json={'id': t_ana, 'fecha': martes.isoformat(), 'inicio': 540}, headers=H)
check(r.status_code == 409, 'mover sobre las cejas de Carla 09:00 → rechazado')
fijo = uno("select id from turnos where cliente_id=? and servicio_id=?", (alumnos[0], CLASE))
r = c.post('/mover_turno', json={'id': fijo, 'fecha': (jueves + timedelta(days=1)).isoformat(), 'inicio': 1080, 'modo': 'semana', 'fecha_origen': jueves.isoformat()}, headers=H)
check(r.get_json()['ok'], 'mover clase fija solo esta semana al viernes')
check(uno("select count(*) from faltas where turno_id=?", (fijo,)) == 1 and uno("select count(*) from turnos where recupera_falta_id is not null") == 1, '  → falta registrada y ya recuperada')
html = c.get(f'/agenda?fecha={lunes.isoformat()}').get_data(as_text=True)
check('18:00 · 2/3 · MA · Clase' in html, '  → el jueves quedan 2 de 3')

# ── faltas y recuperaciones ──
otro = uno("select id from turnos where cliente_id=? and servicio_id=?", (alumnos[1], CLASE))
r = c.post('/quitar_turno', json={'id': otro, 'modo': 'semana', 'fecha': jueves.isoformat()}, headers=H)
pend = json.loads(re.search(r'const PENDIENTES = (\[.*?\]);', c.get('/agenda').get_data(as_text=True)).group(1))
check(r.get_json()['ok'] and len(pend) == 1 and pend[0]['duracion'] == 60, 'falta avisada queda pendiente (con su servicio y duración)')
r = c.post('/recuperar', json={'falta_id': pend[0]['id'], 'fecha': martes.isoformat(), 'inicio': 900}, headers=H)
check(r.get_json()['ok'], 'recuperar el martes 15:00')
check(uno("select count(*) from turnos where recupera_falta_id=?", (pend[0]['id'],)) == 1, '  → turno de recuperación creado')
r = c.post('/recuperar', json={'falta_id': pend[0]['id'], 'fecha': martes.isoformat(), 'inicio': 960}, headers=H)
check(r.status_code == 404, 'no se recupera dos veces')
rec = uno("select id from turnos where recupera_falta_id=?", (pend[0]['id'],))
c.post('/quitar_turno', json={'id': rec}, headers=H)
check(uno("select count(*) from faltas f where not exists (select 1 from turnos t where t.recupera_falta_id=f.id) and descartada=0") == 1, 'quitar la recuperación la vuelve a dejar pendiente')
c.post('/anular_falta', json={'falta_id': pend[0]['id']}, headers=H)
check(uno("select count(*) from turnos_excepciones where turno_id=? and fecha=?", (otro, jueves.isoformat())) == 0, 'anular falta devuelve el turno original')

# ── servicios ──
c.post(f'/servicio/{MASAJE}/editar', data={'_csrf': t, 'nombre': 'Masaje', 'duracion': '90', 'cupo': '1', 'color': 'verde'})
check(uno("select duracion from turnos where id=?", (t_ana,)) == 60, 'cambiar la duración no altera turnos ya agendados')
for sid in (MASAJE, CEJAS, CLASE):
    c.post(f'/servicio/{sid}/activo', data={'_csrf': t, 'activo': '0'})
ultimo = uno("select id from servicios where activo=1")
c.post(f'/servicio/{ultimo}/activo', data={'_csrf': t, 'activo': '0'})
check(uno("select count(*) from servicios where activo=1") == 1, 'no se puede desactivar el último servicio')
for sid in (MASAJE, CEJAS, CLASE):
    c.post(f'/servicio/{sid}/activo', data={'_csrf': t, 'activo': '1'})

# ── otro negocio y permisos ──
c2 = A.app.test_client()
t2 = token(c2, '/registro')
c2.post('/registro', data={'_csrf': t2, 'email': 'otro@x.com', 'password': '123456', 'nombre_negocio': 'Otro'})
t2 = token(c2)
c2.post('/login', data={'_csrf': t2, 'email': 'otro@x.com', 'password': '123456'})
t2 = token(c2, '/agenda')
r = c2.post('/mover_turno', json={'id': t_ana, 'fecha': martes.isoformat(), 'inicio': 720}, headers={'X-CSRFToken': t2})
check(r.status_code == 403, 'otro negocio no mueve turnos ajenos')
antes = uno("select count(*) from turnos")
turno(c2, t2, cliente_id=ana, servicio_id=MASAJE, profesional_id=YO, fecha=martes.isoformat(), inicio=720)
check(uno("select count(*) from turnos") == antes, 'otro negocio no usa clientes/servicios/profesionales ajenos')
h2 = c2.get('/clientes').get_data(as_text=True)
check('Test, Ana' not in h2 and 'Grupo0' not in h2, 'otro negocio no ve clientes ajenos')
if f'id="cliente-{ana}"' in h2:
    print('    DEBUG:', h2[h2.find(f'id="cliente-{ana}"') - 300:h2.find(f'id="cliente-{ana}"') + 100])

c3 = A.app.test_client()
t3 = token(c3)
c3.post('/login', data={'_csrf': t3, 'email': 'martin@x.com', 'password': '123456'})
check(c3.get('/agenda').status_code == 200 and c3.get('/negocio').status_code == 302, 'profesional entra a la agenda pero no a Negocio')
t3 = token(c3, '/agenda')
r = c3.post('/mover_turno', json={'id': t_ana, 'fecha': martes.isoformat(), 'inicio': 720}, headers={'X-CSRFToken': t3})
check(r.status_code == 403, 'profesional no mueve turnos de otra persona')
c.post(f'/profesional/{MARTIN}/activo', data={'_csrf': t, 'activo': '0'})
check('/login' in c3.get('/agenda').headers.get('Location', ''), 'profesional desactivado pierde la sesión')
c.post(f'/profesional/{YO}/editar', data={'_csrf': t, 'nombre': 'Laura', 'password': ''})
check(uno("select rol from profesionales where id=?", (YO,)) == 'admin', 'admin no se quita su propio rol')

# ── clientes ──
c.post(f'/cliente/{ana}/baja', data={'_csrf': t})
check(uno("select count(*) from turnos where cliente_id=?", (ana,)) == 0, 'baja de cliente libera sus turnos')
# ── resumen del día ──
dia_hoy = A.hoy()
check('id="resumen"' in c.get('/agenda').get_data(as_text=True), 'resumen del día en la semana actual')
check('id="resumen"' not in c.get(f'/agenda?fecha={(dia_hoy + timedelta(days=14)).isoformat()}').get_data(as_text=True), 'sin resumen en otras semanas')
# Abrir todos los días de 0 a 24 para poder agendar hoy y mañana a cualquier hora que corra el test
c.post('/negocio', data={'_csrf': t, 'nombre': 'Bienestar', 'hora_apertura': '0', 'hora_cierre': '1440',
                         'intervalo': '15', 'dias': [str(d) for d in range(7)]})
manana = dia_hoy + timedelta(days=1)
eva = nuevo_cliente(c, t, 'Eva', '11 4000-1111')
ahora_min = A.ahora().hour * 60 + A.ahora().minute
hora_hoy = min(1425, (ahora_min // 15 + 1) * 15)
turno(c, t, cliente_id=eva, servicio_id=CEJAS, profesional_id=YO, fecha=dia_hoy.isoformat(), inicio=hora_hoy)
turno(c, t, cliente_id=eva, servicio_id=CEJAS, profesional_id=YO, fecha=manana.isoformat(), inicio=600)
html = c.get('/agenda').get_data(as_text=True)
check('Test, Eva' in html.split('id="resumen"')[1].split('PESTAÑAS')[0], 'el próximo turno de hoy aparece en el resumen')
check('cliente nuevo' in html or 'clientes nuevos' in html, 'el resumen marca clientes nuevos')
check('id="modalRecordar"' in html and 'Recordar turnos de mañana' in html, 'botón para recordar los turnos de mañana')
check(html.count('class="recordar-row"') == uno("select count(*) from turnos where fecha=?", (manana.isoformat(),)) + uno(
    "select count(*) from turnos where tipo='fijo' and dia_semana=?", (manana.weekday(),)), '  → lista todos los turnos de mañana')

# ── demo sin contraseña ──
import runpy
c4 = A.app.test_client()
check('Probar la demo' not in c4.get('/login').get_data(as_text=True), 'sin demo cargada no aparece el botón')
runpy.run_path(os.path.join(PROY, 'crear_demo.py'), run_name='__main__')
html = c4.get('/login').get_data(as_text=True)
check('Probar la demo' in html, 'con la demo cargada aparece "Probar la demo"')
t4 = re.search(r'name="_csrf" value="([^"]+)"', html).group(1)
r = c4.post('/demo', data={'_csrf': t4})
check(r.status_code == 302 and r.headers['Location'].endswith('/agenda'), 'entrar a la demo sin contraseña')
html = c4.get('/agenda').get_data(as_text=True)
check('Estás en la demo' in html and 'Espacio Bienestar' in html, '  → muestra el cartel de demo y su negocio')
check(uno("select count(*) from clientes c join negocios n on n.id=c.negocio_id join usuarios u on u.id=n.user_id "
          "where u.email=? and c.telefono not like '11 0000-%'", (A.DEMO_EMAIL,)) == 0, 'celulares de la demo son números que no existen')
mis_turnos = uno("select count(*) from turnos t join negocios n on n.id=t.negocio_id where n.nombre='Bienestar'")
demo_antes = uno("select id from negocios where nombre='Espacio Bienestar'")
sys.argv = ['crear_demo.py', '--reiniciar']
runpy.run_path(os.path.join(PROY, 'crear_demo.py'), run_name='__main__')
check(uno("select count(*) from negocios where nombre='Espacio Bienestar'") == 1 and
      uno("select id from negocios where nombre='Espacio Bienestar'") != demo_antes, 'reiniciar recrea la demo')
check(uno("select count(*) from turnos t join negocios n on n.id=t.negocio_id where n.nombre='Bienestar'") == mis_turnos,
      '  → sin tocar los otros negocios')
check('/login' in c4.get('/agenda').headers.get('Location', ''), '  → quien estaba en la demo vieja vuelve al ingreso')

# Reinicio automático: si la demo es de un día anterior, se rearma al entrar
con_v = db(); con_v.execute("update usuarios set creado_en='2000-01-01 00:00:00' where email=?", (A.DEMO_EMAIL,)); con_v.commit()
demo_vieja = uno("select id from negocios where nombre='Espacio Bienestar'")
c5 = A.app.test_client()
t5 = token(c5)
c5.post('/demo', data={'_csrf': t5})
check(uno("select id from negocios where nombre='Espacio Bienestar'") != demo_vieja and
      uno("select count(*) from negocios where nombre='Espacio Bienestar'") == 1, 'demo de un día anterior se rearma sola al entrar')
check(c5.get('/agenda').status_code == 200, '  → y se entra normalmente')
demo_nueva = uno("select id from negocios where nombre='Espacio Bienestar'")
c5.post('/logout', data={'_csrf': token(c5, '/agenda')})
c5.post('/demo', data={'_csrf': token(c5)})
check(uno("select id from negocios where nombre='Espacio Bienestar'") == demo_nueva, 'demo del mismo día no se reinicia')

for url in ['/clientes', '/clientes?q=gru', '/equipo', '/negocio', '/ayuda', f'/agenda?fecha={lunes.isoformat()}', '/agenda?fecha=basura']:
    check(c.get(url).status_code == 200, f'GET {url}')

print('FALLAS:', fallas)
sys.exit(1 if fallas else 0)
