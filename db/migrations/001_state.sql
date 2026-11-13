CREATE TABLE dispatch_snapshots (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  plan_date date NOT NULL,
  version integer NOT NULL CHECK (version > 0),
  request jsonb NOT NULL CHECK (jsonb_typeof(request) = 'object'),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (plan_date, version)
);
CREATE TABLE dispatch_plans (
  snapshot_id bigint PRIMARY KEY REFERENCES dispatch_snapshots(id),
  response jsonb NOT NULL CHECK (jsonb_typeof(response) = 'object'),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE dispatch_events (
  id text PRIMARY KEY,
  plan_date date NOT NULL,
  type text NOT NULL,
  payload jsonb NOT NULL,
  occurred_at timestamptz NOT NULL,
  received_at timestamptz NOT NULL DEFAULT now()
);
