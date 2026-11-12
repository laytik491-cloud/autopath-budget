PRAGMA foreign_keys = ON;
BEGIN;
INSERT INTO draft
    (id, schema_version, revision, points_revision, consumption_text, price_text, participants)
VALUES ('current', 1, 1, 1, '8', '60', 4);
INSERT INTO point (draft_id, position, label, lat, lon) VALUES
    ('current', 0, 'Точка A', 59.5, 150.8),
    ('current', 1, 'Точка B', 60.0, 151.8);
INSERT INTO route (draft_id, points_revision, distance_m, duration_s, obtained_at)
VALUES ('current', 1, 600000, 7200, '2026-10-13T00:00:00+11:00');
INSERT INTO event_log (occurred_at, code, app_version, status) VALUES
    ('2026-10-12T13:00:00Z', 'ROUTE_READY', '1.0.0', 'ready'),
    ('2026-10-12T13:00:01Z', 'DRAFT_SAVED', '1.0.0', 'saved');
COMMIT;
