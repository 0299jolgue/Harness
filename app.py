"""Mega Harness: web app and OpenAI-compatible API proxy for ShardCloud."""
from __future__ import annotations

import os
import secrets
import shutil
import tempfile
import mimetypes
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agent import run_agent, confirm_delete, PendingStore
from workspace import resolve, MAX_FILE_BYTES

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
WORKSPACE = ROOT / "projetos"
WORKSPACE.mkdir(exist_ok=True)
pending = PendingStore()
ACCESS_KEY = os.environ.get("MEGA_HARNESS_KEY") or secrets.token_urlsafe(32)
if not os.environ.get("MEGA_HARNESS_KEY"):
    print("Mega Harness access key (configure MEGA_HARNESS_KEY in ShardCloud to keep it stable):", ACCESS_KEY, flush=True)
UPLOAD_CHUNK_BYTES = 8 * 1024 * 1024
uploads: dict[str, dict[str, Any]] = {}
app = FastAPI(title="Mega Harness", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.middleware("http")
async def require_session(request: Request, call_next):
    if request.url.path.startswith("/api/") and request.url.path != "/api/auth/login":
        supplied = request.cookies.get("mega_harness_session", "")
        if not secrets.compare_digest(supplied, ACCESS_KEY):
            return JSONResponse({"detail": "Autenticação necessária."}, status_code=401)
    return await call_next(request)


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
    image_base_url: str = Field(default="", max_length=500)
    image_api_key: str = Field(default="", max_length=2000)


class ConfirmationRequest(BaseModel):
    confirmation_id: str
    approved: bool


class UploadStart(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    size: int = Field(ge=0, le=MAX_FILE_BYTES)
    content_type: str = Field(default="application/octet-stream", max_length=200)


class UploadComplete(BaseModel):
    upload_id: str


class LoginRequest(BaseModel):
    key: str = Field(min_length=1, max_length=300)


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


@app.post("/api/auth/login")
async def login(req: LoginRequest, request: Request):
    if not secrets.compare_digest(req.key, ACCESS_KEY):
        raise HTTPException(401, "Chave de acesso incorreta.")
    response = JSONResponse({"ok": True})
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    secure = request.url.scheme == "https" or "https" in forwarded_proto
    response.set_cookie("mega_harness_session", ACCESS_KEY, httponly=True,
                        secure=secure, samesite="lax", max_age=7 * 24 * 60 * 60)
    return response


@app.post("/api/uploads/start")
async def upload_start(req: UploadStart):
    upload_id = secrets.token_urlsafe(20)
    temp_dir = Path(tempfile.mkdtemp(prefix="mega-upload-"))
    safe_name = "".join(ch for ch in Path(req.filename.replace("\\", "/")).name if ch.isprintable()).strip()[:220] or "ficheiro"
    stored_name = f"{secrets.token_hex(8)}-{safe_name}"
    uploads[upload_id] = {"dir": temp_dir, "size": req.size, "name": stored_name,
                          "original": safe_name, "type": req.content_type, "parts": {}}
    return {"upload_id": upload_id, "chunk_size": UPLOAD_CHUNK_BYTES,
            "path": f"attachments/{stored_name}"}


@app.put("/api/uploads/{upload_id}/{part_number}")
async def upload_part(upload_id: str, part_number: int, request: Request):
    info = uploads.get(upload_id)
    if info is None: raise HTTPException(404, "Upload expirado ou inexistente.")
    if part_number < 0 or part_number > 2000: raise HTTPException(400, "Índice de bloco inválido.")
    length = request.headers.get("content-length")
    try:
        if length and int(length) > UPLOAD_CHUNK_BYTES: raise HTTPException(413, "Bloco acima de 8 MB.")
    except ValueError:
        raise HTTPException(400, "Content-Length inválido.") from None
    data = await request.body()
    if len(data) > UPLOAD_CHUNK_BYTES: raise HTTPException(413, "Bloco acima de 8 MB.")
    part = info["dir"] / f"{part_number:06d}.part"
    part.write_bytes(data)
    info["parts"][part_number] = len(data)
    return {"ok": True, "part": part_number, "bytes": len(data)}


@app.post("/api/uploads/complete")
async def upload_complete(req: UploadComplete):
    info = uploads.pop(req.upload_id, None)
    if info is None: raise HTTPException(404, "Upload expirado ou inexistente.")
    temp_dir = info["dir"]
    dest_rel = f"attachments/{info['name']}"
    dest = resolve(WORKSPACE, dest_rel)
    dest.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    try:
        with dest.open("wb") as output:
            for number in sorted(info["parts"]):
                if number != len([n for n in info["parts"] if n < number]):
                    raise HTTPException(400, "Falta um bloco do upload; tenta novamente.")
                part = temp_dir / f"{number:06d}.part"
                with part.open("rb") as source:
                    while chunk := source.read(1024 * 1024):
                        total += len(chunk)
                        if total > info["size"] or total > MAX_FILE_BYTES:
                            raise HTTPException(413, "O ficheiro excede o tamanho indicado.")
                        output.write(chunk)
        if total != info["size"]:
            dest.unlink(missing_ok=True)
            raise HTTPException(400, "O tamanho recebido não corresponde ao ficheiro.")
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
    return {"path": dest_rel, "name": info["original"], "size": total,
            "type": info["type"], "url": f"/api/workspace/files/{dest_rel}"}


@app.get("/api/workspace/files/{relative_path:path}")
async def workspace_file(relative_path: str):
    try: file = resolve(WORKSPACE, relative_path)
    except ValueError as exc: raise HTTPException(403, str(exc)) from None
    if not file.is_file(): raise HTTPException(404, "Ficheiro não encontrado.")
    media_type = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
    return FileResponse(file, media_type=media_type, filename=file.name,
                        content_disposition_type="inline")


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
