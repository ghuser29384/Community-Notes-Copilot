\set ON_ERROR_STOP on
\pset format csv
\pset tuples_only off

CREATE TEMP TABLE audit_results (
  case_id text PRIMARY KEY,
  category text NOT NULL,
  expectation text NOT NULL,
  accepted boolean NOT NULL,
  sqlstate text,
  message text
);

CREATE OR REPLACE FUNCTION pg_temp.try_case(
  p_case_id text,
  p_category text,
  p_expectation text,
  p_sql text
) RETURNS void AS $$
BEGIN
  EXECUTE p_sql;
  INSERT INTO audit_results VALUES (p_case_id, p_category, p_expectation, true, null, 'statement accepted');
EXCEPTION WHEN OTHERS THEN
  INSERT INTO audit_results VALUES (p_case_id, p_category, p_expectation, false, SQLSTATE, SQLERRM);
END;
$$ LANGUAGE plpgsql;

-- all_reports validation and lifecycle constraints.
SELECT pg_temp.try_case('DB-001','all_reports','reject blank report text',
  $$INSERT INTO cognicity.all_reports(fkey,created_at,text,source,status,disaster_type,lang,report_data,tags,the_geom)
    VALUES(900001,now(),'','audit','confirmed','flood','id','{}','{}',ST_SetSRID(ST_MakePoint(106.8,-6.2),4326))$$);
SELECT pg_temp.try_case('DB-002','all_reports','reject unknown disaster type',
  $$INSERT INTO cognicity.all_reports(fkey,created_at,text,source,status,disaster_type,lang,report_data,tags,the_geom)
    VALUES(900002,now(),'synthetic','audit','confirmed','not-a-disaster','id','{}','{}',ST_SetSRID(ST_MakePoint(106.8,-6.2),4326))$$);
SELECT pg_temp.try_case('DB-003','all_reports','reject unknown status',
  $$INSERT INTO cognicity.all_reports(fkey,created_at,text,source,status,disaster_type,lang,report_data,tags,the_geom)
    VALUES(900003,now(),'synthetic','audit','definitely-real','flood','id','{}','{}',ST_SetSRID(ST_MakePoint(106.8,-6.2),4326))$$);
SELECT pg_temp.try_case('DB-004','all_reports','reject future event timestamp',
  $$INSERT INTO cognicity.all_reports(fkey,created_at,text,source,status,disaster_type,lang,report_data,tags,the_geom)
    VALUES(900004,now()+interval '365 days','synthetic','audit','confirmed','flood','id','{}','{}',ST_SetSRID(ST_MakePoint(106.8,-6.2),4326))$$);
SELECT pg_temp.try_case('DB-005','all_reports','reject timestamp implausibly older than platform event window',
  $$INSERT INTO cognicity.all_reports(fkey,created_at,text,source,status,disaster_type,lang,report_data,tags,the_geom)
    VALUES(900005,'1900-01-01','synthetic','audit','confirmed','flood','id','{}','{}',ST_SetSRID(ST_MakePoint(106.8,-6.2),4326))$$);
SELECT pg_temp.try_case('DB-006','all_reports','reject longitude/latitude outside WGS84 bounds',
  $$INSERT INTO cognicity.all_reports(fkey,created_at,text,source,status,disaster_type,lang,report_data,tags,the_geom)
    VALUES(900006,now(),'synthetic','audit','confirmed','flood','id','{}','{}',ST_SetSRID(ST_MakePoint(181,91),4326))$$);
SELECT pg_temp.try_case('DB-007','all_reports','reject unsupported language code',
  $$INSERT INTO cognicity.all_reports(fkey,created_at,text,source,status,disaster_type,lang,report_data,tags,the_geom)
    VALUES(900007,now(),'synthetic','audit','confirmed','flood','xx-invalid','{}','{}',ST_SetSRID(ST_MakePoint(106.8,-6.2),4326))$$);
SELECT pg_temp.try_case('DB-008','all_reports','require report_data to be a JSON object rather than scalar',
  $$INSERT INTO cognicity.all_reports(fkey,created_at,text,source,status,disaster_type,lang,report_data,tags,the_geom)
    VALUES(900008,now(),'synthetic','audit','confirmed','flood','id','123','[]',ST_SetSRID(ST_MakePoint(106.8,-6.2),4326))$$);
SELECT pg_temp.try_case('DB-009','all_reports','reject duplicate source/fkey report',
  $$INSERT INTO cognicity.all_reports(fkey,created_at,text,source,status,disaster_type,lang,report_data,tags,the_geom)
    VALUES(900001,now(),'duplicate synthetic','audit','confirmed','flood','id','{}','{}',ST_SetSRID(ST_MakePoint(106.8,-6.2),4326))$$);
SELECT pg_temp.try_case('DB-010','all_reports','reject extremely precise public household-scale coordinates or apply privacy tier',
  $$INSERT INTO cognicity.all_reports(fkey,created_at,text,source,status,disaster_type,lang,report_data,tags,the_geom)
    VALUES(900010,now(),'trapped at home - synthetic','audit','confirmed','flood','id','{"sensitivity":"high"}','{}',ST_SetSRID(ST_MakePoint(106.827153123456,-6.175392123456),4326))$$);
SELECT pg_temp.try_case('DB-011','all_reports','reject embedded contact PII from public report_data unless explicitly classified',
  $$INSERT INTO cognicity.all_reports(fkey,created_at,text,source,status,disaster_type,lang,report_data,tags,the_geom)
    VALUES(900011,now(),'synthetic','audit','confirmed','flood','id','{"phone":"+620000000000","name":"synthetic person"}','{}',ST_SetSRID(ST_MakePoint(106.8,-6.2),4326))$$);

-- GRASP card/report validation.
SELECT pg_temp.try_case('DB-012','grasp.cards','reject blank username/network/language',
  $$INSERT INTO grasp.cards(card_id,username,network,language,received)
    VALUES('11111111-1111-1111-1111-111111111111','','','',null)$$);
SELECT pg_temp.try_case('DB-013','grasp.cards','reject duplicate card identifier',
  $$INSERT INTO grasp.cards(card_id,username,network,language,received)
    VALUES('11111111-1111-1111-1111-111111111111','duplicate','audit','en',false)$$);
SELECT pg_temp.try_case('DB-014','grasp.reports','require event time',
  $$INSERT INTO grasp.reports(card_id,created_at,disaster_type,text,card_data,status,the_geom)
    VALUES('11111111-1111-1111-1111-111111111111',null,'flood','synthetic','{}','confirmed',ST_SetSRID(ST_MakePoint(106.8,-6.2),4326))$$);
SELECT pg_temp.try_case('DB-015','grasp.reports','require report text or structured description',
  $$INSERT INTO grasp.reports(card_id,created_at,disaster_type,text,card_data,status,the_geom)
    VALUES('22222222-2222-2222-2222-222222222222',now(),'flood',null,'{}','confirmed',ST_SetSRID(ST_MakePoint(106.8,-6.2),4326))$$);
SELECT pg_temp.try_case('DB-016','grasp.reports','require geometry',
  $$INSERT INTO grasp.reports(card_id,created_at,disaster_type,text,card_data,status,the_geom)
    VALUES('33333333-3333-3333-3333-333333333333',now(),'flood','synthetic','{}','confirmed',null)$$);
SELECT pg_temp.try_case('DB-017','grasp.reports','reject unknown status',
  $$INSERT INTO grasp.reports(card_id,created_at,disaster_type,text,card_data,status,the_geom)
    VALUES('44444444-4444-4444-4444-444444444444',now(),'flood','synthetic','{}','bogus-status',ST_SetSRID(ST_MakePoint(106.8,-6.2),4326))$$);
SELECT pg_temp.try_case('DB-018','grasp.reports','reject unknown disaster type',
  $$INSERT INTO grasp.reports(card_id,created_at,disaster_type,text,card_data,status,the_geom)
    VALUES('55555555-5555-5555-5555-555555555555',now(),'not-a-disaster','synthetic','{}','confirmed',ST_SetSRID(ST_MakePoint(106.8,-6.2),4326))$$);
SELECT pg_temp.try_case('DB-019','grasp.reports','require card_data to be a JSON object',
  $$INSERT INTO grasp.reports(card_id,created_at,disaster_type,text,card_data,status,the_geom)
    VALUES('66666666-6666-6666-6666-666666666666',now(),'flood','synthetic','123','confirmed',ST_SetSRID(ST_MakePoint(106.8,-6.2),4326))$$);
SELECT pg_temp.try_case('DB-020','grasp.reports','reject future event time',
  $$INSERT INTO grasp.reports(card_id,created_at,disaster_type,text,card_data,status,the_geom)
    VALUES('77777777-7777-7777-7777-777777777777',now()+interval '365 days','flood','synthetic','{}','confirmed',ST_SetSRID(ST_MakePoint(106.8,-6.2),4326))$$);

-- Lifecycle/state constraints.
SELECT pg_temp.try_case('DB-021','rem_status','restrict flood state to documented values',
  $$INSERT INTO cognicity.rem_status(local_area,state) SELECT pkey,-1 FROM cognicity.local_areas LIMIT 1$$);
SELECT pg_temp.try_case('DB-022','rem_status','reject implausibly high flood state',
  $$UPDATE cognicity.rem_status SET state=999 WHERE local_area=(SELECT pkey FROM cognicity.local_areas LIMIT 1)$$);
SELECT pg_temp.try_case('DB-023','rem_status_log','reject future state-change timestamp',
  $$INSERT INTO cognicity.rem_status_log(local_area,state,changed,username)
    SELECT pkey,1,now()+interval '365 days','audit' FROM cognicity.local_areas LIMIT 1$$);
SELECT pg_temp.try_case('DB-024','reports_points_log','reject negative confidence/points where semantically invalid',
  $$INSERT INTO cognicity.reports_points_log(report_id,value) VALUES(900001,-999)$$);

-- Output escaping and trigger behavior.
SELECT pg_temp.try_case('DB-025','grasp.push_to_all_reports','return valid JSON even when username/network contain quotes',
  $$DO $inner$
    DECLARE v text;
    BEGIN
      UPDATE grasp.cards SET username='audit"name', network='audit"network', language='en'
        WHERE card_id='11111111-1111-1111-1111-111111111111';
      UPDATE grasp.reports SET created_at=now(), text='synthetic', disaster_type='flood', card_data='{}', status='confirmed', the_geom=ST_SetSRID(ST_MakePoint(106.8,-6.2),4326)
        WHERE card_id='11111111-1111-1111-1111-111111111111';
      v := grasp.push_to_all_reports('11111111-1111-1111-1111-111111111111');
      PERFORM v::jsonb;
    END $inner$;$$);
SELECT pg_temp.try_case('DB-026','template trigger','avoid duplicate all_reports rows when a source row is updated',
  $$DO $inner$
    DECLARE n_before bigint; n_after bigint; rid bigint;
    BEGIN
      INSERT INTO template_data_source.reports(created_at,disaster_type,text,lang,url,the_geom)
        VALUES(now(),'flood','synthetic','en','audit://one',ST_SetSRID(ST_MakePoint(106.8,-6.2),4326)) RETURNING pkey INTO rid;
      SELECT count(*) INTO n_before FROM cognicity.all_reports WHERE source='data_source' AND fkey=rid;
      UPDATE template_data_source.reports SET text='synthetic update' WHERE pkey=rid;
      SELECT count(*) INTO n_after FROM cognicity.all_reports WHERE source='data_source' AND fkey=rid;
      IF n_after > n_before THEN RAISE EXCEPTION 'update created duplicate rows: before %, after %', n_before, n_after; END IF;
    END $inner$;$$);

SELECT * FROM audit_results ORDER BY case_id;
