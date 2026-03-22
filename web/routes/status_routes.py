"""Status API routes: GET /api/status, WS /api/ws/stats."""

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect

from web.app import get_collector, get_settings, require_auth
from web.auth import decode_token

router = APIRouter(tags=["status"])


@router.get("/api/status", dependencies=[Depends(require_auth)])
async def get_status():
    """Return the latest collected stats snapshot."""
    return get_collector().latest


@router.websocket("/api/ws/stats")
async def ws_stats(ws: WebSocket, token: str = Query(...)):
    """Stream live stats over WebSocket.

    WebSocket connections cannot send Authorization headers, so the JWT
    token is passed as a query parameter and verified before accepting
    the connection.
    """
    try:
        decode_token(token, get_settings()["jwt_secret"])
    except Exception:
        await ws.close(code=1008, reason="Invalid token")
        return

    collector = get_collector()
    await ws.accept()
    collector.clients.add(ws)
    try:
        while True:
            await ws.receive_text()  # Keep connection alive
    except WebSocketDisconnect:
        collector.clients.discard(ws)
