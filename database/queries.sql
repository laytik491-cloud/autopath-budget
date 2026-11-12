PRAGMA foreign_keys = ON;
SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name;
SELECT id, consumption_text, price_text, participants FROM draft;
SELECT d.id, a.label AS start_label, b.label AS end_label,
       r.distance_m, r.duration_s, d.consumption_text, d.price_text, d.participants
FROM draft AS d
JOIN point AS a ON a.draft_id = d.id AND a.position = d.start_position
JOIN point AS b ON b.draft_id = d.id AND b.position = d.end_position
JOIN route AS r ON r.draft_id = d.id AND r.points_revision = d.points_revision;
SELECT event_id, occurred_at, code, app_version, status FROM event_log ORDER BY event_id;
PRAGMA foreign_key_check;
PRAGMA integrity_check;
