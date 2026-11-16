-- ============================================================
--  TURNERO — Schema v1.0
--  Agenda de turnos para cualquier negocio (pilates, masajes,
--  depilación, peluquería...).
--  ATENCIÓN: este script BORRA todas las tablas. Solo se usa para crear
--  una base nueva (app.py lo ejecuta si turnero.db no existe).
--  Horarios en minutos desde las 00:00 (ej. 9:30 = 570).
--  Días: 0 = lunes ... 6 = domingo.
-- ============================================================

DROP TABLE IF EXISTS faltas;
DROP TABLE IF EXISTS turnos_excepciones;
DROP TABLE IF EXISTS turnos;
DROP TABLE IF EXISTS clientes;
DROP TABLE IF EXISTS servicios;
DROP TABLE IF EXISTS profesionales;
DROP TABLE IF EXISTS negocios;
DROP TABLE IF EXISTS usuarios;

-- Dueños que se registran
CREATE TABLE usuarios (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    email       TEXT    NOT NULL UNIQUE,
    password    TEXT    NOT NULL,
    creado_en   TEXT    DEFAULT (datetime('now'))
);

-- Un negocio por dueño, con su horario de atención
CREATE TABLE negocios (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL UNIQUE,
    nombre        TEXT    NOT NULL DEFAULT 'Mi negocio',
    logo_url      TEXT,
    hora_apertura INTEGER NOT NULL DEFAULT 480,     -- 08:00
    hora_cierre   INTEGER NOT NULL DEFAULT 1260,    -- 21:00
    intervalo     INTEGER NOT NULL DEFAULT 15 CHECK (intervalo IN (15, 30, 60)),
    dias          TEXT    NOT NULL DEFAULT '0,1,2,3,4,5',
    FOREIGN KEY (user_id) REFERENCES usuarios(id) ON DELETE CASCADE
);

-- Profesionales: rol 'admin' (dueño, ve todo) o 'profesional' (solo lo suyo)
CREATE TABLE profesionales (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    negocio_id  INTEGER NOT NULL,
    nombre      TEXT    NOT NULL,
    email       TEXT    NOT NULL UNIQUE,
    password    TEXT    NOT NULL,
    rol         TEXT    NOT NULL DEFAULT 'profesional' CHECK (rol IN ('admin', 'profesional')),
    activo      INTEGER DEFAULT 1,
    creado_en   TEXT    DEFAULT (datetime('now')),
    FOREIGN KEY (negocio_id) REFERENCES negocios(id) ON DELETE CASCADE
);

-- Servicios que ofrece el negocio, cada uno con su duración y cupo
CREATE TABLE servicios (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    negocio_id  INTEGER NOT NULL,
    nombre      TEXT    NOT NULL,
    duracion    INTEGER NOT NULL CHECK (duracion BETWEEN 5 AND 480),
    cupo        INTEGER NOT NULL DEFAULT 1 CHECK (cupo BETWEEN 1 AND 50),
    color       TEXT    NOT NULL DEFAULT 'verde',
    activo      INTEGER DEFAULT 1,
    FOREIGN KEY (negocio_id) REFERENCES negocios(id) ON DELETE CASCADE
);

CREATE TABLE clientes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    negocio_id  INTEGER NOT NULL,
    nombre      TEXT    NOT NULL,
    apellido    TEXT    NOT NULL DEFAULT '',
    telefono    TEXT,
    email       TEXT,
    notas       TEXT,
    activo      INTEGER DEFAULT 1,
    creado_en   TEXT    DEFAULT (datetime('now')),
    FOREIGN KEY (negocio_id) REFERENCES negocios(id) ON DELETE CASCADE
);

-- Turnos: 'fijo' se repite cada semana (dia_semana); 'puntual' es de una fecha.
-- La duración se copia del servicio al agendar.
CREATE TABLE turnos (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    negocio_id        INTEGER NOT NULL,
    profesional_id    INTEGER NOT NULL,
    cliente_id        INTEGER NOT NULL,
    servicio_id       INTEGER NOT NULL,
    tipo              TEXT    NOT NULL DEFAULT 'puntual' CHECK (tipo IN ('fijo', 'puntual')),
    dia_semana        INTEGER CHECK (dia_semana BETWEEN 0 AND 6),
    fecha             TEXT,
    inicio            INTEGER NOT NULL CHECK (inicio BETWEEN 0 AND 1439),
    duracion          INTEGER NOT NULL,
    recupera_falta_id INTEGER,
    FOREIGN KEY (negocio_id)        REFERENCES negocios(id)      ON DELETE CASCADE,
    FOREIGN KEY (profesional_id)    REFERENCES profesionales(id) ON DELETE CASCADE,
    FOREIGN KEY (cliente_id)        REFERENCES clientes(id)      ON DELETE CASCADE,
    FOREIGN KEY (servicio_id)       REFERENCES servicios(id)     ON DELETE CASCADE,
    FOREIGN KEY (recupera_falta_id) REFERENCES faltas(id)        ON DELETE SET NULL
);

-- Fechas en que un turno fijo NO ocurre (falta avisada o movido solo esa semana)
CREATE TABLE turnos_excepciones (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    turno_id  INTEGER NOT NULL,
    fecha     TEXT    NOT NULL,
    UNIQUE (turno_id, fecha),
    FOREIGN KEY (turno_id) REFERENCES turnos(id) ON DELETE CASCADE
);

-- Turnos perdidos de un turno fijo. Pendiente de recuperar = no descartada
-- y sin turno que la recupere (turnos.recupera_falta_id).
CREATE TABLE faltas (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    negocio_id      INTEGER NOT NULL,
    cliente_id      INTEGER NOT NULL,
    profesional_id  INTEGER NOT NULL,
    servicio_id     INTEGER NOT NULL,
    turno_id        INTEGER,
    fecha           TEXT    NOT NULL,
    inicio          INTEGER NOT NULL,
    descartada      INTEGER DEFAULT 0,
    creado_en       TEXT    DEFAULT (datetime('now')),
    FOREIGN KEY (negocio_id)     REFERENCES negocios(id)      ON DELETE CASCADE,
    FOREIGN KEY (cliente_id)     REFERENCES clientes(id)      ON DELETE CASCADE,
    FOREIGN KEY (profesional_id) REFERENCES profesionales(id) ON DELETE CASCADE,
    FOREIGN KEY (servicio_id)    REFERENCES servicios(id)     ON DELETE CASCADE,
    FOREIGN KEY (turno_id)       REFERENCES turnos(id)        ON DELETE SET NULL
);

CREATE INDEX idx_profesionales_negocio ON profesionales (negocio_id);
CREATE INDEX idx_servicios_negocio     ON servicios     (negocio_id);
CREATE INDEX idx_clientes_negocio      ON clientes      (negocio_id);
CREATE INDEX idx_turnos_negocio        ON turnos        (negocio_id);
CREATE INDEX idx_turnos_profesional    ON turnos        (profesional_id);
CREATE INDEX idx_turnos_cliente        ON turnos        (cliente_id);
CREATE INDEX idx_turnos_fecha          ON turnos        (fecha);
CREATE INDEX idx_excepciones_fecha     ON turnos_excepciones (fecha);
CREATE INDEX idx_faltas_cliente        ON faltas        (cliente_id);
