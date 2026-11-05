#!/bin/sh
set -eu

: "${MES_APP_PASSWORD:?MES_APP_PASSWORD is required}"
: "${MES_MIGRATOR_PASSWORD:?MES_MIGRATOR_PASSWORD is required}"

psql \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  --set=ON_ERROR_STOP=1 \
  --set=database_name="$POSTGRES_DB" \
  --set=app_password="$MES_APP_PASSWORD" \
  --set=migrator_password="$MES_MIGRATOR_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE mes_app LOGIN PASSWORD %L', :'app_password') \gexec
SELECT format('CREATE ROLE mes_migrator LOGIN PASSWORD %L', :'migrator_password') \gexec

GRANT CONNECT ON DATABASE :"database_name" TO mes_app, mes_migrator;
GRANT USAGE ON SCHEMA public TO mes_app, mes_migrator;
GRANT CREATE ON SCHEMA public TO mes_migrator;
ALTER DEFAULT PRIVILEGES FOR ROLE mes_migrator IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE ON TABLES TO mes_app;
ALTER DEFAULT PRIVILEGES FOR ROLE mes_migrator IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO mes_app;
SQL
