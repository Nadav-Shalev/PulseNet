# PulseNet Database

| File | Role |
| --- | --- |
| `migrations/NNN_<name>.sql` | What actually builds and changes databases, applied in number order by `backend/migrate.py`. |
| `migrations/000_baseline.sql` | The schema when migrations were introduced. Frozen: never edit it. |
| `schema.sql` | The full current schema in one readable file (and the source of the ER diagram). Kept in sync with the migrations by hand. |

## Create or update a database

From the project root, with MySQL credentials in `backend/.env`:

```bash
python backend/migrate.py                             # migrate DB_NAME from backend/.env
python backend/migrate.py --status                    # list applied / pending, change nothing
python backend/migrate.py --db pulsenet_e2e           # another database (created if missing)
python backend/migrate.py --db pulsenet_e2e --reset   # drop + rebuild (*_e2e / *_test only)
```

The script needs only Python and `mysql-connector-python` (no `mysql` CLI). It
prints the server version first, records every applied migration in the
`schema_migrations` table, and on each run applies only what is still pending, so
the same command works on a new laptop, the local dev database and RDS.

- **Empty database:** runs `000_baseline.sql`, then every later migration.
- **Database built from `schema.sql` before migrations existed** (has the tables
  but no `schema_migrations`): stamped as `000_baseline` without re-running it,
  then the later migrations run.
- **Non-empty database without PulseNet tables:** refused, nothing is touched.

## Changing the schema

1. Add `database/migrations/NNN_<lower_snake_name>.sql` with the next free number,
   e.g. `001_add_likes.sql`. Keep it small: MySQL commits DDL immediately, so a
   migration that fails halfway cannot be rolled back.
2. Apply the same change to `schema.sql` and to `docs/db-diagram.mmd` / `docs/db-diagram.md`.
3. Run `python backend/migrate.py` locally; on the server it runs as part of the
   deploy steps.

The backend tests guard the folder: file names must match `NNN_name.sql` with no
duplicate numbers, `000_baseline.sql` must be unchanged, and every table in
`schema.sql` must be created by some migration.
