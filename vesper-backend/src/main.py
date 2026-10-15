from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.router import router as agents_router
from src.auth.router import router as auth_router
from src.core.config import settings
from src.core.database import get_db
from src.core.exceptions import register_exception_handlers
from src.core.logging_config import configure_logging
from src.repositories.router import router as repositories_router
from src.review_jobs.router import router as review_jobs_router
from src.reviews.router import router as reviews_router
from src.tenants.router import router as tenants_router
from src.triggers.router import router as triggers_router
from src.users.router import router as users_router
from src.webhooks.router import router as webhooks_router

configure_logging()
app = FastAPI(title="Vesper API")

# Necesario cuando el frontend Next.js y este backend se sirven desde
# origenes distintos en produccion (dominios/puertos separados). NUNCA
# `allow_origins=["*"]` con `allow_credentials=True` (CORS lo prohi­be).
# Con `cors_origins` vacio (default) no se registra el middleware -> correcto
# para dev/mismo-origen.
if settings.cors_origins_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

register_exception_handlers(app)
app.include_router(auth_router)
app.include_router(tenants_router)
app.include_router(users_router)
app.include_router(repositories_router)
app.include_router(review_jobs_router)
app.include_router(triggers_router)
app.include_router(agents_router)
app.include_router(reviews_router)
app.include_router(webhooks_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
async def health_ready(db: AsyncSession = Depends(get_db)) -> JSONResponse:
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        await db.rollback()
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return JSONResponse(status_code=200, content={"status": "ready"})
