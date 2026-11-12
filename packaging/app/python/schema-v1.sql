PRAGMA foreign_keys = ON;
BEGIN;

CREATE TABLE draft (
    id TEXT NOT NULL PRIMARY KEY CHECK (id = 'current'),
    schema_version INTEGER NOT NULL CHECK (typeof(schema_version) = 'integer' AND schema_version = 1),
    revision INTEGER NOT NULL CHECK (typeof(revision) = 'integer' AND revision BETWEEN 1 AND 9007199254740991),
    points_revision INTEGER NOT NULL CHECK (typeof(points_revision) = 'integer' AND points_revision BETWEEN 1 AND 9007199254740991),
    consumption_text TEXT NOT NULL CHECK (
        typeof(consumption_text) = 'text'
        AND length(consumption_text) > 0
        AND consumption_text NOT GLOB '*[^0-9.]*'
        AND consumption_text NOT LIKE '.%' AND consumption_text NOT LIKE '%.'
        AND consumption_text NOT GLOB '*.*.*'
        AND ((CASE WHEN instr(consumption_text, '.') = 0 THEN consumption_text ELSE substr(consumption_text, 1, instr(consumption_text, '.') - 1) END) = '0' OR substr((CASE WHEN instr(consumption_text, '.') = 0 THEN consumption_text ELSE substr(consumption_text, 1, instr(consumption_text, '.') - 1) END), 1, 1) BETWEEN '1' AND '9')
        AND ((CASE WHEN instr(consumption_text, '.') = 0 THEN consumption_text ELSE substr(consumption_text, 1, instr(consumption_text, '.') - 1) END) <> '0' OR (CASE WHEN instr(consumption_text, '.') = 0 THEN '' ELSE substr(consumption_text, instr(consumption_text, '.') + 1) END) >= '1' COLLATE BINARY)
        AND (length((CASE WHEN instr(consumption_text, '.') = 0 THEN consumption_text ELSE substr(consumption_text, 1, instr(consumption_text, '.') - 1) END)) < 3
             OR ((CASE WHEN instr(consumption_text, '.') = 0 THEN consumption_text ELSE substr(consumption_text, 1, instr(consumption_text, '.') - 1) END) = '100' AND (CASE WHEN instr(consumption_text, '.') = 0 THEN '' ELSE substr(consumption_text, instr(consumption_text, '.') + 1) END) NOT GLOB '*[1-9]*'))
    ),
    price_text TEXT NOT NULL CHECK (
        typeof(price_text) = 'text'
        AND length(price_text) > 0
        AND price_text NOT GLOB '*[^0-9.]*'
        AND price_text NOT LIKE '.%' AND price_text NOT LIKE '%.'
        AND price_text NOT GLOB '*.*.*'
        AND ((CASE WHEN instr(price_text, '.') = 0 THEN price_text ELSE substr(price_text, 1, instr(price_text, '.') - 1) END) = '0' OR substr((CASE WHEN instr(price_text, '.') = 0 THEN price_text ELSE substr(price_text, 1, instr(price_text, '.') - 1) END), 1, 1) BETWEEN '1' AND '9')
        AND ((CASE WHEN instr(price_text, '.') = 0 THEN price_text ELSE substr(price_text, 1, instr(price_text, '.') - 1) END) <> '0' OR (CASE WHEN instr(price_text, '.') = 0 THEN '' ELSE substr(price_text, instr(price_text, '.') + 1) END) >= '01' COLLATE BINARY)
        AND (length((CASE WHEN instr(price_text, '.') = 0 THEN price_text ELSE substr(price_text, 1, instr(price_text, '.') - 1) END)) < 4
             OR ((CASE WHEN instr(price_text, '.') = 0 THEN price_text ELSE substr(price_text, 1, instr(price_text, '.') - 1) END) = '1000' AND (CASE WHEN instr(price_text, '.') = 0 THEN '' ELSE substr(price_text, instr(price_text, '.') + 1) END) NOT GLOB '*[1-9]*'))
    ),
    participants INTEGER NOT NULL CHECK (typeof(participants) = 'integer' AND participants BETWEEN 1 AND 9),
    start_position INTEGER NOT NULL DEFAULT 0 CHECK (typeof(start_position) = 'integer' AND start_position = 0),
    end_position INTEGER NOT NULL DEFAULT 1 CHECK (typeof(end_position) = 'integer' AND end_position = 1),
    UNIQUE (id, points_revision),
    FOREIGN KEY (id, start_position) REFERENCES point(draft_id, position)
        DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (id, end_position) REFERENCES point(draft_id, position)
        DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (id) REFERENCES route(draft_id)
        DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE point (
    draft_id TEXT NOT NULL,
    position INTEGER NOT NULL CHECK (typeof(position) = 'integer' AND position IN (0, 1)),
    label TEXT NOT NULL CHECK (typeof(label) = 'text' AND length(trim(label)) > 0),
    lat REAL NOT NULL CHECK (typeof(lat) IN ('real', 'integer') AND lat BETWEEN -90 AND 90),
    lon REAL NOT NULL CHECK (typeof(lon) IN ('real', 'integer') AND lon BETWEEN -180 AND 180),
    PRIMARY KEY (draft_id, position),
    UNIQUE (draft_id, lat, lon),
    FOREIGN KEY (draft_id) REFERENCES draft(id) ON DELETE CASCADE
);

CREATE TABLE route (
    draft_id TEXT NOT NULL PRIMARY KEY,
    points_revision INTEGER NOT NULL CHECK (typeof(points_revision) = 'integer'),
    distance_m REAL NOT NULL CHECK (typeof(distance_m) IN ('real', 'integer') AND distance_m > 0 AND distance_m <= 1.7976931348623157e308),
    duration_s REAL NOT NULL CHECK (typeof(duration_s) IN ('real', 'integer') AND duration_s > 0 AND duration_s <= 1.7976931348623157e308),
    obtained_at TEXT NOT NULL CHECK (typeof(obtained_at) = 'text' AND length(obtained_at) >= 20 AND strftime('%Y-%m-%dT%H:%M:%fZ', obtained_at) IS NOT NULL),
    FOREIGN KEY (draft_id, points_revision) REFERENCES draft(id, points_revision)
        ON DELETE CASCADE
);

CREATE TABLE event_log (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at TEXT NOT NULL CHECK (typeof(occurred_at) = 'text' AND length(occurred_at) >= 20 AND strftime('%Y-%m-%dT%H:%M:%fZ', occurred_at) IS NOT NULL),
    code TEXT NOT NULL CHECK (code IN ('ROUTE_READY', 'ROUTE_ERROR', 'DRAFT_SAVED', 'STORAGE_ERROR', 'DATA_CLEARED', 'APP_UPDATED')),
    app_version TEXT NOT NULL CHECK (typeof(app_version) = 'text' AND length(trim(app_version)) BETWEEN 1 AND 32),
    status TEXT NOT NULL CHECK (status IN ('ready', 'error', 'saved', 'cleared', 'updated'))
);

CREATE TRIGGER event_log_keep_last_100
AFTER INSERT ON event_log
BEGIN
    DELETE FROM event_log
    WHERE event_id NOT IN (
        SELECT event_id FROM event_log ORDER BY event_id DESC LIMIT 100
    );
END;

PRAGMA user_version = 1;
COMMIT;
