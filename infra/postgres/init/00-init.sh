#!/bin/bash
# Runs once, on first boot of an empty data volume.
#
#   1. extensions on the application database
#   2. separate databases for SpiceDB and Langfuse — a migration in either
#      must never be able to touch application data
#   3. the INSERT-only audit role (INS-11)
#
# Delete the pgdata volume to re-run:  docker compose down -v
set -euo pipefail

echo "[init] extensions on ${POSTGRES_DB}"
psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER}" --dbname "${POSTGRES_DB}" <<-SQL
	CREATE EXTENSION IF NOT EXISTS vector;
	CREATE EXTENSION IF NOT EXISTS pg_trgm;
	CREATE EXTENSION IF NOT EXISTS pgcrypto;
SQL

echo "[init] sidecar databases"
psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER}" --dbname postgres <<-SQL
	CREATE DATABASE spicedb;
	CREATE DATABASE langfuse;
SQL

echo "[init] INSERT-only audit role: ${INSIGHT_AUDIT_USER}"
psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER}" --dbname "${POSTGRES_DB}" <<-SQL
	CREATE ROLE ${INSIGHT_AUDIT_USER} LOGIN PASSWORD '${INSIGHT_AUDIT_PASSWORD}';
	GRANT CONNECT ON DATABASE ${POSTGRES_DB} TO ${INSIGHT_AUDIT_USER};
	GRANT USAGE ON SCHEMA public TO ${INSIGHT_AUDIT_USER};

	-- This role may append audit records and read them back. It may never
	-- UPDATE or DELETE. That is what makes the hash chain meaningful: even a
	-- fully compromised application cannot rewrite history.
	ALTER DEFAULT PRIVILEGES IN SCHEMA public
	  GRANT SELECT, INSERT ON TABLES TO ${INSIGHT_AUDIT_USER};
	ALTER DEFAULT PRIVILEGES IN SCHEMA public
	  GRANT USAGE ON SEQUENCES TO ${INSIGHT_AUDIT_USER};
SQL

echo "[init] done"
