"""FastAPI stub server that echoes vendor calls during dry runs."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import FastAPI, Request

app = FastAPI(title="Dragonfly Vendor Stub")


async def _echo_response(request: Request, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Return a simple echo payload for stubbed vendor integrations."""

    return {
        "ok": True,
        "path": str(request.url.path),
        "json": payload,
    }


@app.post("/lob")
async def stub_lob(request: Request, payload: Dict[str, Any]) -> Dict[str, Any]:
    return await _echo_response(request, payload)


@app.post("/twilio")
async def stub_twilio(request: Request, payload: Dict[str, Any]) -> Dict[str, Any]:
    return await _echo_response(request, payload)


@app.post("/postmark")
async def stub_postmark(request: Request, payload: Dict[str, Any]) -> Dict[str, Any]:
    return await _echo_response(request, payload)
