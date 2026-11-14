-- PROPOSAL for PostgreSQL 16; coordinate with the team's migration runner.
-- Initial empty-schema draft, not an upgrade for an existing database.
BEGIN;
CREATE SCHEMA dispatch;
SET LOCAL search_path = dispatch, public;

CREATE DOMAIN technology_code AS text CHECK (VALUE IN ('PON','FTTB','XDSL','DOCSIS'));
CREATE DOMAIN profile_code AS text CHECK (VALUE IN ('INSTALL','LTP3'));
CREATE DOMAIN equipment_counts AS jsonb CHECK (
  jsonb_typeof(VALUE) = 'object'
  AND VALUE ?& ARRAY['ONT','ROUTER','STB']
  AND VALUE - ARRAY['ONT','ROUTER','STB'] = '{}'::jsonb
  AND jsonb_typeof(VALUE->'ONT') = 'number'
  AND jsonb_typeof(VALUE->'ROUTER') = 'number'
  AND jsonb_typeof(VALUE->'STB') = 'number'
  AND (VALUE->>'ONT') ~ '^[0-9]+$'
  AND (VALUE->>'ROUTER') ~ '^[0-9]+$'
  AND (VALUE->>'STB') ~ '^[0-9]+$'
);

CREATE TABLE service_centers (
  service_center_id text PRIMARY KEY CHECK (service_center_id ~ '^SC-[0-9]{2}$'),
  name text NOT NULL,
  address text NOT NULL,
  lat double precision NOT NULL CHECK (lat BETWEEN -90 AND 90),
  lon double precision NOT NULL CHECK (lon BETWEEN -180 AND 180),
  opening_open time NOT NULL,
  opening_close time NOT NULL,
  restock_duration_min integer NOT NULL CHECK (restock_duration_min >= 0)
);

CREATE TABLE staff (
  staff_id text PRIMARY KEY CHECK (staff_id ~ '^ST-[0-9]{3}$'),
  display_name text,
  service_center_id text NOT NULL REFERENCES service_centers,
  profiles profile_code[] NOT NULL CHECK (cardinality(profiles) > 0 AND array_position(profiles, NULL) IS NULL),
  technologies technology_code[] NOT NULL CHECK (cardinality(technologies) > 0 AND array_position(technologies, NULL) IS NULL),
  height_permit boolean NOT NULL,
  shift_start time NOT NULL,
  shift_end time NOT NULL,
  break_duration_min integer NOT NULL CHECK (break_duration_min >= 0),
  break_window_from time NOT NULL,
  break_window_to time NOT NULL,
  equipment_start equipment_counts NOT NULL,
  equipment_capacity equipment_counts NOT NULL,
  experience_years numeric CHECK (experience_years >= 0),
  CHECK ((equipment_start->>'ONT')::numeric <= (equipment_capacity->>'ONT')::numeric),
  CHECK ((equipment_start->>'ROUTER')::numeric <= (equipment_capacity->>'ROUTER')::numeric),
  CHECK ((equipment_start->>'STB')::numeric <= (equipment_capacity->>'STB')::numeric)
);
CREATE INDEX staff_center_idx ON staff(service_center_id);

CREATE TABLE buildings (
  building_id text PRIMARY KEY CHECK (building_id ~ '^B-[0-9]{5}$'),
  address text NOT NULL,
  lat double precision NOT NULL CHECK (lat BETWEEN -90 AND 90),
  lon double precision NOT NULL CHECK (lon BETWEEN -180 AND 180),
  building_type text NOT NULL CHECK (building_type IN ('MKD','PRIVATE')),
  overhead_line boolean NOT NULL,
  zone_service_center_id text REFERENCES service_centers
);
CREATE TABLE access_nodes (
  access_node_id text PRIMARY KEY CHECK (access_node_id ~ '^AN-[0-9]{4}$'),
  node_type text NOT NULL CHECK (node_type IN ('OLT','SWITCH','DSLAM','CMTS')),
  technology technology_code NOT NULL,
  name text NOT NULL,
  address text,
  lat double precision NOT NULL CHECK (lat BETWEEN -90 AND 90),
  lon double precision NOT NULL CHECK (lon BETWEEN -180 AND 180),
  UNIQUE(access_node_id, technology)
);
CREATE TABLE access_node_buildings (
  access_node_id text NOT NULL REFERENCES access_nodes,
  building_id text NOT NULL REFERENCES buildings,
  PRIMARY KEY(access_node_id, building_id)
);
CREATE INDEX node_building_idx ON access_node_buildings(building_id);

CREATE TABLE work_types (
  code text PRIMARY KEY CHECK (code IN ('INST_PON_MKD','INST_FTTB_MKD','INST_PRIVATE_VLS',
    'ADD_SERVICE','SURVEY_PRIVATE','REPAIR','DEGRADATION','DISMANTLE')),
  name text NOT NULL,
  profiles profile_code[] NOT NULL CHECK (cardinality(profiles) > 0 AND array_position(profiles, NULL) IS NULL),
  duration_min integer NOT NULL CHECK (duration_min >= 1),
  max_start_delay_min integer CHECK (max_start_delay_min >= 0),
  deadline_kind text NOT NULL CHECK (deadline_kind IN ('SLOT','HOURS','WORKING_DAYS')),
  deadline_value integer CHECK (deadline_value >= 1),
  repeat_deadline_value integer CHECK (repeat_deadline_value >= 1),
  pgp_relevant boolean NOT NULL
);

-- Матрица хранится целиком: сохраняются порядок points и направленность.
-- Квадратность, полноту точек и нулевую диагональ проверяет импортёр.
CREATE TABLE travel_matrices (
  matrix_id text PRIMARY KEY,
  payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'
    AND payload ?& ARRAY['matrix_id','points','durations_sec','distances_m']),
  CHECK (payload->>'matrix_id' = matrix_id)
);
CREATE TABLE planning_days (
  date date PRIMARY KEY,
  model_now timestamptz NOT NULL,
  matrix_id text NOT NULL REFERENCES travel_matrices,
  reference_snapshot jsonb NOT NULL CHECK (jsonb_typeof(reference_snapshot) = 'object'),
  input_snapshot jsonb NOT NULL CHECK (jsonb_typeof(input_snapshot) = 'object'),
  CHECK ((model_now AT TIME ZONE 'Asia/Yekaterinburg')::date = date)
);
CREATE TABLE absent_staff (
  date date NOT NULL REFERENCES planning_days,
  staff_id text NOT NULL REFERENCES staff,
  PRIMARY KEY(date, staff_id)
);
CREATE TABLE orders (
  date date NOT NULL REFERENCES planning_days,
  order_id text NOT NULL CHECK (order_id ~ '^ORD-[0-9]{8}-[0-9]{4}$'),
  work_type_code text NOT NULL REFERENCES work_types(code),
  technology technology_code NOT NULL,
  building_id text NOT NULL REFERENCES buildings,
  address text NOT NULL,
  lat double precision NOT NULL CHECK (lat BETWEEN -90 AND 90),
  lon double precision NOT NULL CHECK (lon BETWEEN -180 AND 180),
  building_type text NOT NULL CHECK (building_type IN ('MKD','PRIVATE')),
  requires_height boolean NOT NULL,
  access_node_id text NOT NULL,
  registered_at timestamptz NOT NULL,
  slot_start timestamptz NOT NULL,
  slot_end timestamptz NOT NULL,
  latest_start timestamptz NOT NULL,
  deadline timestamptz NOT NULL,
  required_equipment equipment_counts NOT NULL,
  is_repeat boolean NOT NULL,
  previous_order_id text, -- предшественник может отсутствовать в наборе: FK не нужен
  PRIMARY KEY(date, order_id),
  FOREIGN KEY(access_node_id, building_id) REFERENCES access_node_buildings,
  FOREIGN KEY(access_node_id, technology) REFERENCES access_nodes(access_node_id, technology),
  CHECK (slot_start < slot_end),
  CHECK (latest_start BETWEEN slot_start AND slot_end),
  CHECK (deadline >= latest_start),
  CHECK ((slot_start AT TIME ZONE 'Asia/Yekaterinburg')::date = date)
);
CREATE INDEX orders_pgp_idx ON orders(date, access_node_id, registered_at);
CREATE INDEX orders_slot_idx ON orders(date, slot_start);
CREATE INDEX orders_work_type_idx ON orders(work_type_code);
CREATE INDEX orders_building_idx ON orders(building_id);

-- Обучающая разметка из fact изолирована от рабочего входа солвера.
CREATE TABLE training_orders (
  order_id text PRIMARY KEY,
  payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
  CHECK (payload ? 'order_id' AND payload->>'order_id' = order_id)
);

CREATE TABLE events (
  date date NOT NULL REFERENCES planning_days,
  event_id text NOT NULL,
  type text NOT NULL CHECK (type IN ('NEW_ORDER','ORDER_CANCELLED','VISIT_DELAYED',
    'ORDER_TRANSFERRED','STAFF_UNAVAILABLE','TIME_TICK')),
  timestamp timestamptz NOT NULL,
  payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'
    AND payload ?& ARRAY['event_id','type','timestamp']),
  result jsonb NOT NULL CHECK (jsonb_typeof(result) = 'object'),
  PRIMARY KEY(date, event_id),
  CHECK (payload->>'event_id' = event_id AND payload->>'type' = type)
);
CREATE INDEX events_time_idx ON events(date, timestamp);

-- Версия целиком соответствует Plan: история остановок, ПГП и предупреждений
-- не перезаписывается при перепланировании. Полная проверка -- в API.
CREATE TABLE plans (
  date date NOT NULL REFERENCES planning_days,
  plan_version integer NOT NULL CHECK (plan_version >= 1),
  as_of timestamptz NOT NULL,
  based_on_event_id text,
  computation_ms integer CHECK (computation_ms >= 0),
  payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'
    AND payload ?& ARRAY['date','plan_version','as_of','routes','unassigned','pgp_groups','cancelled','alerts']),
  PRIMARY KEY(date, plan_version),
  FOREIGN KEY(date, based_on_event_id) REFERENCES events(date, event_id),
  CHECK (payload->>'date' = date::text),
  CHECK ((payload->>'plan_version')::integer = plan_version),
  CHECK ((payload->>'as_of')::timestamptz = as_of),
  CHECK (payload->>'based_on_event_id' IS NOT DISTINCT FROM based_on_event_id),
  CHECK ((plan_version = 1 AND based_on_event_id IS NULL)
    OR (plan_version > 1 AND based_on_event_id IS NOT NULL))
);
CREATE UNIQUE INDEX plans_event_idx ON plans(date, based_on_event_id) WHERE based_on_event_id IS NOT NULL;
CREATE VIEW current_plans AS
  SELECT DISTINCT ON (date) date, plan_version, as_of, payload
  FROM plans ORDER BY date, plan_version DESC;

CREATE TABLE schema_migrations (
  version integer PRIMARY KEY,
  applied_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO schema_migrations(version) VALUES (1);
COMMIT;
