"""Mega Harness: web app and OpenAI-compatible API proxy for ShardCloud."""
from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agent import run_agent, confirm_delete, PendingStore

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
WORKSPACE = ROOT / "projetos"
WORKSPACE.mkdir(exist_ok=True)
pending = PendingStore()
app = FastAPI(title="Mega Harness", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class Provider(BaseModel):
    base_url: str = Field(min_length=8, max_length=500)
    api_key: str = Field(default="", max_length=2000)
    model: str = Field(min_length=1, max_length=300)


class ChatRequest(Provider):
    messages: list[dict[str, Any]]
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_tokens: int = Field(default=2048, ge=1, le=8192)


class AgentRequest(ChatRequest):
    conversation_id: str = Field(default_factory=lambda: secrets.token_urlsafe(16))


class ConfirmationRequest(BaseModel):
    confirmation_id: str
    approved: bool


def safe_base_url(url: str) -> str:
    url = url.strip().rstrip("/")
    if not url.startswith("https://") and not url.startswith("http://127.0.0.1"):
        raise HTTPException(400, "A Base URL tem de usar HTTPS (ou localhost).")
    if any(ch in url for ch in "\r\n"):
        raise HTTPException(400, "Base URL inválida.")
    return url


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
async def health():
    return {"ok": True, "app": "Mega Harness"}


@app.post("/api/chat")
async def chat(req: ChatRequest):
    url = safe_base_url(req.base_url) + "/chat/completions"
    body = {"model": req.model, "messages": req.messages,
            "temperature": req.temperature, "max_tokens": req.max_tokens, "stream": False}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(300, connect=20), follow_redirects=False) as client:
            headers = {"Content-Type": "application/json"}
            if req.api_key:
                headers["Authorization"] = f"Bearer {req.api_key}"
            response = await client.post(url, json=body, headers=headers)
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Não foi possível contactar o fornecedor: {type(exc).__name__}") from None
    if response.status_code >= 400:
        detail = "O fornecedor rejeitou o pedido. Confirma Base URL, modelo e chave API."
        if response.status_code in (401, 403): detail = "Chave API recusada pelo fornecedor."
        raise HTTPException(502, detail)
    try:
        return response.json()
    except ValueError:
        raise HTTPException(502, "O fornecedor devolveu uma resposta inválida.") from None


@app.post("/api/agent/run")
async def agent(req: AgentRequest):
    return await run_agent(req, WORKSPACE, pending)


@app.post("/api/agent/confirm-delete")
async def agent_confirm(req: ConfirmationRequest):
    return await confirm_delete(req.confirmation_id, req.approved, pending, WORKSPACE)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "80")), access_log=False)
