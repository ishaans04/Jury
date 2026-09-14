"""GET /health. The one route that needs no auth (Task 4.4)."""
from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}
