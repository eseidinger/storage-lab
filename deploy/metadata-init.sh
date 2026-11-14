#!/bin/sh
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v api_password="$API_DB_PASSWORD" -v worker_password="$WORKER_DB_PASSWORD" <<'SQL'
CREATE ROLE storage_lab_worker LOGIN PASSWORD :'worker_password';
CREATE ROLE storage_lab_api LOGIN PASSWORD :'api_password';
ALTER DATABASE storage_lab OWNER TO storage_lab_worker;
REVOKE ALL ON DATABASE storage_lab FROM PUBLIC;
GRANT CONNECT ON DATABASE storage_lab TO storage_lab_api;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO storage_lab_api;
ALTER DEFAULT PRIVILEGES FOR ROLE storage_lab_worker IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO storage_lab_api;
ALTER DEFAULT PRIVILEGES FOR ROLE storage_lab_worker IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO storage_lab_api;
SQL
