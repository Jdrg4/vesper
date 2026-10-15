"""Router del dominio `reviews` (prefijo `/api/v1/reviews`).

F7: `GET /` (lista del tenant), `GET /{id}`, `POST /` (disparar manualmente
la pasada de revision sobre un job/PR ya completado), `GET /{id}/events`
(SSE).
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/reviews", tags=["reviews"])

# TODO(F7): endpoints.
