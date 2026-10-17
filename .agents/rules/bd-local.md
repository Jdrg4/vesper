# BD local de pruebas y seed

Para todo trabajo de validación usar la **BD local de pruebas**:

- **Motor:** PostgreSQL 16+ local en el puerto **55432** (usuario/clave `vesper`/`vesper`).
- **BD:** `vesper_dev` (validación manual) y `vesper_test` (pytest; recrea el esquema en cada
  test). Override de la de tests con `TEST_DATABASE_URL`.
- **Sin `.env`**, `src/core/config.py` ya apunta por defecto a `vesper_dev`.
  Una URL de producción jamás se pone aquí.
- **`scripts/seed_test_users.py`** aborta si `DATABASE_URL` no es local
  (`_abort_if_not_local`, exit 2). **Es idempotente.**

```bash
# Una vez: rol y bases
psql -p 55432 -U postgres -c "CREATE ROLE vesper LOGIN PASSWORD 'vesper' CREATEDB"
psql -p 55432 -U postgres -c "CREATE DATABASE vesper_dev OWNER vesper"
psql -p 55432 -U postgres -c "CREATE DATABASE vesper_test OWNER vesper"

cd vesper-backend
export PYTHONPATH=.            # PowerShell: $env:PYTHONPATH="."
alembic upgrade head
python scripts/seed_test_users.py
```

**Credenciales de prueba:** ver [docs/test-users.md](docs/test-users.md)
(`admin@vesper.example` / `demo@vesper.example`, password `changeme123`,
tenant `vesper-demo`).
