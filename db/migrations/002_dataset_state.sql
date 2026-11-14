BEGIN;
CREATE TABLE dispatch.dataset_state (
  singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
  reference jsonb,
  matrix_id text REFERENCES dispatch.travel_matrices(matrix_id)
);
INSERT INTO dispatch.dataset_state(singleton,reference,matrix_id)
VALUES(true,(SELECT reference_snapshot FROM dispatch.planning_days ORDER BY date DESC LIMIT 1),
    (SELECT matrix_id FROM dispatch.planning_days ORDER BY date DESC LIMIT 1));
INSERT INTO dispatch.schema_migrations(version) VALUES(2);
COMMIT;
