library os - Secure Production Setup

Quick setup (recommended for production):
LibrarySystemPRO - Secure Production Setup

Quick setup (recommended for production):

1. Create a Python virtualenv and install dependencies

```bash
python -m venv .venv
.venv\Scripts\activate    # Windows
pip install --upgrade pip
pip install -r requirements.txt
```

2. Environment variables (example `.env`)

```
SECRET_KEY=change_this
JWT_SECRET=change_this_jwt_secret
DATABASE_URL=postgresql://user:pass@host:5432/librarydb
BACKUP_ENCRYPTION_KEY=enter_a_fernet_key_here
SESSION_COOKIE_SECURE=1
REFRESH_TOKEN_EXPIRES=604800   # 7 days in seconds
PG_DUMP_PATH=pg_dump           # if using pg_dump for backups
DB_POOL_SIZE=20
DB_MAX_OVERFLOW=10
```

3. Initialize Flask-Migrate and run migrations (Postgres must be accessible)

```bash
set FLASK_APP=app.py
flask db init        # only once
flask db migrate -m "initial"
flask db upgrade
```

4. Run the app (production: use gunicorn / uwsgi behind a reverse proxy)

```bash
python app.py
# or (recommended) use gunicorn
# pip install gunicorn
# gunicorn -w 4 -b 0.0.0.0:8000 app:create_app()
```

5. Creating backups

Use the admin UI (Backups) or call `/admin/backups/create` as an admin. If `BACKUP_ENCRYPTION_KEY` is set, backups will be encrypted.

6. Seed data (optional)

A `scripts/seed_data.py` helper script is provided to generate sample students and books. Run it from the workspace in an activated venv.

7. Security notes

- Use managed Postgres (AWS RDS/Azure DB/GCP Cloud SQL) for durability and automated backups.
- Enable TLS for all traffic and set `SESSION_COOKIE_SECURE=1`.
- Provide a strong `JWT_SECRET` and rotate periodically.
- Token rotation and revocation checks are DB-backed (no Redis required).
- Configure a process supervisor (systemd) and monitoring (Prometheus/Grafana).

If you want, I can:
- add a `docker-compose` example with Postgres;
- add seed data generation now (default 5k students, 100k books).
 
Notes
-----
- Copy `.env.example` to `.env` and customize values.
- Initialize the database and run migrations as described below.
