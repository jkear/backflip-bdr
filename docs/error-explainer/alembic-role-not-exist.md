# Error: `role "backflip" does not exist`

**Command:** `uv run alembic upgrade head`
**Date:** 2026-02-28

---

## Root Cause

A **local PostgreSQL installation** (Homebrew/macOS) is running on `localhost:5432`,
which shadows the Docker container's PostgreSQL that also binds to port 5432.

When `asyncpg` connects to `localhost:5432`, macOS resolves `localhost` to `::1` (IPv6)
or `127.0.0.1` (IPv4), both of which hit the **local** Postgres — not the Docker one.

The local Postgres doesn't have a `backflip` role, so authentication fails:

```
asyncpg.exceptions.InvalidAuthorizationSpecificationError: role "backflip" does not exist
```

### Evidence

```
$ lsof -i :5432 -sTCP:LISTEN
COMMAND     PID  ...  NAME
postgres   2619  ...  localhost:postgresql   <-- local Postgres (catches localhost)
OrbStack  30628  ...  *:postgresql           <-- Docker container (wildcard bind)
```

Inside the Docker container, the role exists just fine:

```
$ docker exec backflip_sdr-agent_teams-postgres-1 psql -U backflip -c "SELECT current_user;"
 current_user
--------------
 backflip
```

---

## Fix Applied

Two issues were resolved:

### Issue 1: Port collision (local PG vs Docker PG)

Changed `docker-compose.yml` to map Docker Postgres to host port **5433**:

```yaml
ports:
  - "5433:5432"   # host:container — avoids collision with local PG on 5432
```

Updated `DATABASE_URL` in `.env` and `.env.example` to match:

```
DATABASE_URL=postgresql+asyncpg://backflip:<password>@localhost:5433/backflip_sdr
```

### Issue 2: Stale password in Docker volume

After fixing the port, the connection reached Docker Postgres but got
`password authentication failed`. This happened because:

- `POSTGRES_PASSWORD` is only read during the **first** `docker-entrypoint-initdb.d` run
- The Docker volume persisted from an earlier init with a different password
- Changing `DB_PASSWORD` in `.env` and restarting the container does NOT update the role's password

Fixed by resetting the password inside the running container:

```bash
docker exec backflip_sdr-agent_teams-postgres-1 \
  psql -U backflip -d backflip_sdr \
  -c "ALTER USER backflip WITH PASSWORD 'backflipdbpass';"
```

### Alternative options (if Issue 1 recurs)

**Option B: Use OrbStack's direct IP**

```bash
docker inspect backflip_sdr-agent_teams-postgres-1 | grep IPAddress
# Then use that IP in DATABASE_URL
```

**Option C: Stop the local PostgreSQL**

```bash
brew services stop postgresql@16
```

---

## Error Trace Summary

```
env.py:79  →  run_migrations_online()
env.py:73  →  asyncio.run(run_async_migrations())
env.py:66  →  async with connectable.connect()
             ↓ SQLAlchemy async engine → asyncpg
asyncpg/connection.py:2443  →  connect()
             ↓
FATAL: role "backflip" does not exist   ← local PG rejects the connection
```

The entire traceback is SQLAlchemy/asyncpg boilerplate around a single failed
`connect()` call. The only meaningful line is the last one.
