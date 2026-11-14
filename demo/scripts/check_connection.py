"""Read-only connection check. Credentials are never printed."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'demo/backend'))
from dotenv import load_dotenv
from api.settings import Settings
from api.repository import PostgresRepository, StoreUnavailable

def main():
    load_dotenv(ROOT / '.env')
    settings = Settings.from_env()
    if settings.password == 'replace-with-local-password':
        print('Set POSTGRES_USER and POSTGRES_PASSWORD in .env using your pgAdmin connection.')
        return 1
    repo = PostgresRepository(settings)
    try:
        repo.health()
        rows = repo.fetch('''SELECT
            (SELECT count(*) FROM dispatch.service_centers) AS service_centers,
            (SELECT count(*) FROM dispatch.staff) AS staff,
            (SELECT count(*) FROM dispatch.orders) AS orders,
            (SELECT count(*) FROM dispatch.planning_days) AS days''')
    except StoreUnavailable:
        print('Connection failed. Check server host, port, database, user, password and dispatch schema in pgAdmin.')
        return 1
    print('PostgreSQL connection: OK (read-only)')
    print(f'Database: {settings.database}; host: {settings.host}; port: {settings.port}')
    for key, count in rows[0].items():
        print(f'{key}: {count}')
    if not rows[0]['days']:
        print('Database ready. Load reference, matrix and planning days through the API.')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
