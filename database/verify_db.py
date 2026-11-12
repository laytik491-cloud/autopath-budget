from pathlib import Path
import sqlite3,json,datetime,tempfile
ROOT=Path(__file__).resolve().parent
SCHEMA=(ROOT/'schema.sql').read_text(encoding='utf-8')
SEED=(ROOT/'seed.sql').read_text(encoding='utf-8')
RESULTS=[]

def fresh(seed=True):
 c=sqlite3.connect(':memory:');c.executescript(SCHEMA)
 assert c.execute('PRAGMA foreign_keys').fetchone()==(1,)
 if seed:c.executescript(SEED)
 return c

def sqls(c,script):
 
 c.execute('BEGIN')
 for statement in script.split(';'):
  if statement.strip():c.execute(statement)
 c.commit()

def pair(n,title,good,bad,expected_error,summary):
 c=fresh();sqls(c,good);ok=c.execute('PRAGMA foreign_key_check').fetchall()==[];c.close();assert ok
 errors=[]
 for script in bad:
  c=fresh()
  try:
   sqls(c,script)
  except sqlite3.IntegrityError as e:
   error=e.sqlite_errorname;assert error==expected_error,(title,error,str(e));c.rollback();errors.append(error)
  else:raise AssertionError('Недопустимая операция принята: '+title)
  assert c.execute('PRAGMA foreign_key_check').fetchall()==[]
  c.close()
 RESULTS.append(dict(id=f'DB-{n:02}',title=title,good_sql=good,bad_sql=bad,actual='Корректный запрос выполнен; недопустимые варианты отклонены: '+', '.join(errors),detail=summary,status='Пройден'))

def check(n,title,sql,fn,summary):
 c=fresh();fn(c);c.close()
 RESULTS.append(dict(id=f'DB-{n:02}',title=title,good_sql=sql,bad_sql=[],actual=summary,detail=summary,status='Пройден'))

def creation(c):
 assert c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()==[('draft',),('event_log',),('manual_trip',),('point',),('route',)]
 assert c.execute('PRAGMA user_version').fetchone()==(2,)
check(1,'Создание схемы','schema.sql; SELECT name FROM sqlite_master; PRAGMA foreign_keys; PRAGMA user_version;',creation,'Созданы draft, point, route, manual_trip, event_log; foreign_keys = 1; user_version = 2.')
JOIN='''SELECT d.id,a.label,b.label,r.distance_m,r.duration_s,d.consumption_text,d.price_text,d.participants
FROM draft d JOIN point a ON a.draft_id=d.id AND a.position=d.start_position
JOIN point b ON b.draft_id=d.id AND b.position=d.end_position
JOIN route r ON r.draft_id=d.id AND r.points_revision=d.points_revision;'''
def join(c):
 row=c.execute(JOIN).fetchall()
 assert row==[('current','Точка A','Точка B',600000.0,7200.0,'8','60',4)],row
 assert [c.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ['draft','point','route','event_log']]==[1,2,1,2]
check(2,'INSERT SELECT и JOIN',JOIN,join,'seed.sql добавил 1 черновик, 2 точки, 1 маршрут и 2 события. JOIN: current; Точка A → Точка B; 600000 м; 7200 с; C=8; F=60; N=4.')
pair(3,'UNIQUE для координат точек',"UPDATE point SET lat=60.1,lon=151.9 WHERE position=1;",["UPDATE point SET lat=59.5,lon=150.8 WHERE position=1;"],'SQLITE_CONSTRAINT_UNIQUE','Разные точки приняты; совпадающие точки одного черновика запрещены.')
pair(4,'NOT NULL для обязательного поля',"UPDATE point SET label='Точка B2' WHERE position=1;",["UPDATE point SET label=NULL WHERE position=1;"],'SQLITE_CONSTRAINT_NOTNULL','Непустая подпись принята; NULL отклонён.')
pair(5,'Внешний ключ точки',"UPDATE point SET label='Точка B2' WHERE draft_id='current' AND position=1;",["INSERT INTO point VALUES ('missing',0,'Точка X',1,2);"],'SQLITE_CONSTRAINT_FOREIGNKEY','Существующий родитель принят; ссылка missing отклонена.')
pair(6,'Единственный текущий черновик',"UPDATE draft SET revision=2 WHERE id='current';",["INSERT INTO draft (id,schema_version,revision,points_revision,consumption_text,price_text,participants) VALUES ('other',1,1,1,'8','60',4);"],'SQLITE_CONSTRAINT_CHECK','Допускается только id=current; другой идентификатор запрещён.')
pair(7,'Первичный ключ черновика',"UPDATE draft SET revision=2 WHERE id='current';",["INSERT INTO draft (id,schema_version,revision,points_revision,consumption_text,price_text,participants) VALUES ('current',1,2,2,'8','60',4);"],'SQLITE_CONSTRAINT_PRIMARYKEY','Обновление принято; второй current отклонён по PK.')
pair(8,'Две обязательные точки на COMMIT',"UPDATE point SET label='Точка B2' WHERE position=1;",["DELETE FROM point WHERE position=1;"],'SQLITE_CONSTRAINT_FOREIGNKEY','Полный черновик принят; отсутствие конца отклонено при COMMIT, затем выполнен ROLLBACK.')
pair(9,'Обязательный маршрут на COMMIT',"UPDATE route SET duration_s=3600 WHERE draft_id='current';",["DELETE FROM route;"],'SQLITE_CONSTRAINT_FOREIGNKEY','Маршрут с положительным временем принят; отсутствие маршрута отклонено при COMMIT.')
pair(10,'Участники только целые 1–9',"UPDATE draft SET participants=1; UPDATE draft SET participants=9;",["UPDATE draft SET participants=0;","UPDATE draft SET participants=10;","UPDATE draft SET participants=1.5;"],'SQLITE_CONSTRAINT_CHECK','1 и 9 приняты; 0, 10 и 1,5 отклонены.')
pair(11,'Расход 0,1–100 точно',"UPDATE draft SET consumption_text='0.1'; UPDATE draft SET consumption_text='100';",["UPDATE draft SET consumption_text='0.099';","UPDATE draft SET consumption_text='100.001';","UPDATE draft SET consumption_text='100.00000000000000001';"],'SQLITE_CONSTRAINT_CHECK','Границы приняты; значения за пределами, включая 100.00000000000000001, отклонены без преобразования в REAL.')
pair(12,'Цена 0,01–1000 точно',"UPDATE draft SET price_text='0.01'; UPDATE draft SET price_text='1000';",["UPDATE draft SET price_text='0.009';","UPDATE draft SET price_text='1000.001';","UPDATE draft SET price_text='1000.00000000000000001';"],'SQLITE_CONSTRAINT_CHECK','Границы приняты; три значения за пределами отклонены.')
pair(13,'Диапазоны координат',"UPDATE point SET lat=-90,lon=-180 WHERE position=0; UPDATE point SET lat=90,lon=180 WHERE position=1;",["UPDATE point SET lat=90.001 WHERE position=0;","UPDATE point SET lon=180.001 WHERE position=0;"],'SQLITE_CONSTRAINT_CHECK','Широта ±90 и долгота ±180 приняты; выход за границы отклонён.')
pair(14,'Положительное конечное расстояние',"UPDATE route SET distance_m=1;",["UPDATE route SET distance_m=0;","UPDATE route SET distance_m=-1;","UPDATE route SET distance_m=1e999;"],'SQLITE_CONSTRAINT_CHECK','1 м принят; 0, −1 и бесконечность отклонены.')
pair(15,'Положительная конечная длительность',"UPDATE route SET duration_s=1;",["UPDATE route SET duration_s=0;","UPDATE route SET duration_s=1e999;"],'SQLITE_CONSTRAINT_CHECK','1 с принята; 0 и бесконечность отклонены.')
pair(16,'Поддерживаемая версия DTO',"UPDATE draft SET schema_version=1;",["UPDATE draft SET schema_version=99;"],'SQLITE_CONSTRAINT_CHECK','Версия 1 принята; 99 отклонена. Для новой версии необходима миграция.')
pair(17,'Маршрут связан с версией точек',"UPDATE route SET distance_m=300000 WHERE points_revision=1;",["UPDATE route SET points_revision=2;","UPDATE draft SET points_revision=2;"],'SQLITE_CONSTRAINT_FOREIGNKEY','Совпадающая версия принята; рассогласование route и draft отклонено.')
pair(18,'Формат десятичного текста',"UPDATE draft SET consumption_text='8.1234567890123456789';",["UPDATE draft SET consumption_text='8,5';","UPDATE draft SET consumption_text='abc';","UPDATE draft SET consumption_text='1e1';"],'SQLITE_CONSTRAINT_CHECK','Десятичный текст сохранён; запятая, буквы и экспонента в физическом формате отклонены. Интерфейс нормализует их до записи.')
pair(19,'Распознаваемая дата маршрута',"UPDATE route SET obtained_at='2026-10-13T00:00:00Z';",["UPDATE route SET obtained_at='not-a-date';"],'SQLITE_CONSTRAINT_CHECK','Дата ISO 8601 принята; нераспознаваемая строка отклонена. Полная проверка даты остаётся в адаптере.')
EVENTS="""DELETE FROM event_log;
WITH RECURSIVE seq(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM seq WHERE n<100)
INSERT INTO event_log(occurred_at,code,app_version,status)
SELECT strftime('%Y-%m-%dT%H:%M:%SZ','2026-10-12T13:00:00Z','+'||n||' seconds'),'ROUTE_READY','1.0.0','ready' FROM seq;"""
def retention(c):
 c.executescript(EVENTS)
 assert c.execute('SELECT count(*) FROM event_log').fetchone()==(100,)
 first=c.execute('SELECT min(event_id) FROM event_log').fetchone()[0]
 c.execute("INSERT INTO event_log(occurred_at,code,app_version,status) VALUES ('2026-10-12T13:02:00Z','ROUTE_READY','1.0.0','ready')");c.commit()
 assert c.execute('SELECT count(*),min(event_id),max(event_id) FROM event_log').fetchone()==(100,first+1,first+100)
check(20,'Журнал последних 100 событий',EVENTS+"\nINSERT INTO event_log(occurred_at,code,app_version,status) VALUES ('2026-10-12T13:02:00Z','ROUTE_READY','1.0.0','ready');",retention,'После 100 добавлений — 100 строк. После 101-го — 100 строк, первое из добавленных событий удалено.')
pair(21,'Разрешённые поля журнала',"INSERT INTO event_log(occurred_at,code,app_version,status) VALUES ('2026-10-12T13:00:02Z','APP_UPDATED','1.0.0','updated');",["UPDATE event_log SET code='USER_ADDRESS';","UPDATE event_log SET status='password';"],'SQLITE_CONSTRAINT_CHECK','Разрешённый код и статус приняты; произвольные значения отклонены. Полей адреса, координат и текста запроса в таблице нет.')
def rollback(c):
 try:sqls(c,"UPDATE draft SET consumption_text='10'; DELETE FROM point WHERE position=1;")
 except sqlite3.IntegrityError as e:
  assert e.sqlite_errorname=='SQLITE_CONSTRAINT_FOREIGNKEY';c.rollback()
 else:raise AssertionError('Неполный черновик сохранён')
 assert c.execute('SELECT consumption_text FROM draft').fetchone()==('8',)
 assert c.execute('SELECT count(*) FROM point').fetchone()==(2,)
check(22,'Откат неполного сохранения',"BEGIN; UPDATE draft SET consumption_text='10'; DELETE FROM point WHERE position=1; COMMIT; ROLLBACK;",rollback,'COMMIT отклонён по FK; после ROLLBACK расход снова 8, обе точки на месте.')
def clear(c):
 sqls(c,'DELETE FROM draft; DELETE FROM event_log;')
 assert all(c.execute('SELECT count(*) FROM '+t).fetchone()==(0,) for t in ['draft','point','route','event_log'])
check(23,'Каскадная и полная очистка','BEGIN; DELETE FROM draft; DELETE FROM event_log; COMMIT;',clear,'В draft, point, route и event_log по 0 строк. Зависимые точки и маршрут удалены каскадом.')
def reopen(c):
 
 with tempfile.TemporaryDirectory(prefix='autopath-db-') as folder:
  path=Path(folder)/'reopen.sqlite'
  saved=sqlite3.connect(path);c.backup(saved);saved.close()
  other=sqlite3.connect(path);other.execute('PRAGMA foreign_keys=ON');join(other)
  assert other.execute('PRAGMA foreign_key_check').fetchall()==[]
  assert other.execute('PRAGMA integrity_check').fetchone()==('ok',)
  other.close()
check(24,'Повторное открытие и целостность','backup в файл; close; connect; JOIN; PRAGMA foreign_key_check; PRAGMA integrity_check;',reopen,'После закрытия и повторного открытия файла TD-01 восстановлен. foreign_key_check: 0 нарушений; integrity_check: ok. Браузерный IndexedDB здесь не проверялся.')

pair(25,'Ограничения ручного расстояния',"INSERT INTO manual_trip VALUES ('current',1,'150','8','60',4);",["INSERT INTO manual_trip VALUES ('current',1,'0','8','60',4);","INSERT INTO manual_trip VALUES ('current',1,'-1','8','60',4);","INSERT INTO manual_trip VALUES ('current',1,'1000001','8','60',4);","INSERT INTO manual_trip VALUES ('current',1,'abc','8','60',4);"],'SQLITE_CONSTRAINT_CHECK','Допустимое расстояние принято; ноль, отрицательное, превышение и текст отклонены.')
def manual_reopen(c):
 c.execute('DELETE FROM draft');c.execute('DELETE FROM event_log')
 c.execute("INSERT INTO manual_trip VALUES ('current',1,'150','8','60',4)");c.commit()
 with tempfile.TemporaryDirectory(prefix='autopath-manual-') as folder:
  path=Path(folder)/'manual.sqlite';saved=sqlite3.connect(path);c.backup(saved);saved.close()
  other=sqlite3.connect(path)
  assert other.execute('SELECT distance_text,consumption_text,price_text,participants FROM manual_trip').fetchone()==('150','8','60',4)
  assert other.execute('SELECT count(*) FROM point').fetchone()==(0,)
  assert other.execute('PRAGMA integrity_check').fetchone()==('ok',)
  other.close()
check(26,'Повторное открытие ручной поездки','INSERT manual_trip; backup; close; connect; SELECT;',manual_reopen,'150 км, расход 8, цена 60 и 4 участника восстановлены; точки для ручного расчёта отсутствуют.')
mem=fresh();dest=sqlite3.connect(ROOT/'autopath-test.sqlite');mem.backup(dest);dest.close();mem.close()
report=dict(sqlite_version=sqlite3.sqlite_version,run_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),database='autopath-test.sqlite',checks=len(RESULTS),passed=sum(x['status']=='Пройден' for x in RESULTS),results=RESULTS)
(ROOT/'verification-results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
lines=[f'SQLite {report["sqlite_version"]}; {report["checks"]}/{report["checks"]} проверок пройдено.']
for x in RESULTS:
 lines.extend(['',x['id']+' '+x['title'],'Корректный запрос:',x['good_sql'],'Недопустимые запросы:',*x['bad_sql'],'Результат: '+x['actual'],'Статус: '+x['status']])
(ROOT/'verification-results.txt').write_text('\n'.join(lines),encoding='utf-8')
print(lines[0])
