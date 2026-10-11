#!/bin/bash
# Creates the local demo database (once): installs PostgreSQL if needed, creates the
# knightscribe database and its tables, and adds the demo course with default settings.
# Safe to run again: existing data is kept.
#
#   bash backend/setup_local_db.sh
#
# Then start the backend with: bash backend/start_local.sh
cd "$(dirname "$0")" || exit 1
DB="${DB_NAME:-knightscribe}"

if ! command -v psql >/dev/null; then
  echo "Installing PostgreSQL..."
  sudo apt-get update -qq && sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq postgresql || exit 1
fi
sudo service postgresql start >/dev/null 2>&1 || true
sleep 1

as_postgres() { sudo su postgres -c "psql -v ON_ERROR_STOP=1 -tAc \"$1\""; }
[ "$(as_postgres "SELECT 1 FROM pg_roles WHERE rolname = 'knightscribe'")" = "1" ] ||
  as_postgres "CREATE ROLE knightscribe LOGIN PASSWORD 'knightscribe'"
[ "$(as_postgres "SELECT 1 FROM pg_database WHERE datname = '$DB'")" = "1" ] ||
  as_postgres "CREATE DATABASE $DB OWNER knightscribe"

export PGPASSWORD=knightscribe
db() { psql -h 127.0.0.1 -U knightscribe -d "$DB" -v ON_ERROR_STOP=1 -q "$@"; }
db -f schema.sql || exit 1   # every table is CREATE ... IF NOT EXISTS
db <<'SQL'
INSERT INTO courses (name, code, professor_name)
SELECT 'KnightScribe Demo Course', 'KNT 1000', 'Demo Professor'
WHERE NOT EXISTS (SELECT 1 FROM courses);
INSERT INTO course_settings (course_id)
SELECT id FROM courses
WHERE id NOT IN (SELECT course_id FROM course_settings);
SQL
echo "Database '$DB' is ready:"
db -tA -c "SELECT ' course ' || id || ': ' || name || ' (' || code || ')' FROM courses ORDER BY id"
