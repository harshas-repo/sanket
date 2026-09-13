"""API router assembly.

Kept as one list so it is obvious what the surface of the product is: six groups,
not dozens of micro-endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter

from backend.app.api import (
    agent,
    auth,
    community,
    incidents,
    operations,
    response_center,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(community.router)
api_router.include_router(operations.router)
api_router.include_router(incidents.router)
api_router.include_router(response_center.router)
api_router.include_router(agent.router)

__all__ = ["api_router"]
