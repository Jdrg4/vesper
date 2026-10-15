"""Router de webhooks de GitHub (prefijo /api/v1/webhooks)."""

import json

import structlog
from fastapi import APIRouter, Depends, Header, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.webhooks import services

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])

logger = structlog.get_logger(__name__)


@router.post("/github", status_code=status.HTTP_202_ACCEPTED)
async def github_webhook(
    request: Request,
    x_github_event: str = Header(default=""),
    x_hub_signature_256: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Eventos de la GitHub App. Sin JWT: lo autentica la firma.

    Responde siempre rapido: GitHub reintenta el envio si el handler tarda mas
    de 10 segundos.
    """
    body = await request.body()
    services.verify_signature(body, x_hub_signature_256)

    if x_github_event != "push":
        # `ping` llega al crear el webhook; `pull_request`, `issue_comment` y
        # `check_run` son materia de F7.
        # `github_event` y no `event`: structlog ya usa `event` para el nombre
        # del propio evento de log y la llamada revienta con TypeError.
        logger.info("webhook_event_ignored", github_event=x_github_event)
        return {"handled": False, "event": x_github_event}

    payload = json.loads(body)
    encolados = await services.handle_push(db, payload)
    return {"handled": True, "queued": encolados}
