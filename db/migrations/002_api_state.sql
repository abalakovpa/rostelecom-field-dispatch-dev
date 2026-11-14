CREATE TABLE api_state (
  singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
  document jsonb NOT NULL DEFAULT '{}'::jsonb
);
INSERT INTO api_state(singleton) VALUES (true);
