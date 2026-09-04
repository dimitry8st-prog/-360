from __future__ import annotations

import json
import logging
import logging.config
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select

from app.config import settings
from app.database import AuditLog, Conversation, FileRecord, Message, SessionLocal, User, init_db
from app.security import hash_password, make_session, read_session, verify_password
from app.services import ChartService, FileService, FileServiceError

cfg = settings()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
files = FileService(cfg)
charts = ChartService(cfg)
logger = logging.getLogger("dis360")


def configure_logging() -> None:
    logging.config.dictConfig({"version": 1, "disable_existing_loggers": False, "formatters": {"json": {"format": '{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}'}}, "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "json"}}, "root": {"handlers": ["console"], "level": cfg.log_level}})


def audit(db, event: str, request_id: str, user_id: int | None = None, details: dict | None = None) -> None:
    db.add(AuditLog(user_id=user_id, event=event, request_id=request_id, details=json.dumps(details or {}, ensure_ascii=False)))
    db.commit()


def current_user(request: Request, db) -> User | None:
    uid = read_session(request.cookies.get("dis360_session"))
    return db.get(User, uid) if uid else None


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging(); files.ensure_storage(); init_db()
    with SessionLocal() as db:
        if not db.scalar(select(User).where(User.email == cfg.admin_email)):
            db.add(User(email=cfg.admin_email, password_hash=hash_password(cfg.admin_password), is_admin=True)); db.commit()
    logger.info("application_started")
    yield


app = FastAPI(title=cfg.app_name, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
app.mount("/outputs", StaticFiles(directory=str(cfg.output_dir)), name="outputs")


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid4())
    response = await call_next(request)
    response.headers["x-request-id"] = request_id
    response.headers["x-content-type-options"] = "nosniff"
    response.headers["x-frame-options"] = "DENY"
    return response


@app.get("/health")
def health():
    with SessionLocal() as db: db.scalar(select(func.count(User.id)))
    return {"status": "ok", "database": "ok", "websocket": "/ws/status", "ai": "configured" if cfg.openai_api_key else "demo_stub"}


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    with SessionLocal() as db:
        user = current_user(request, db)
    return templates.TemplateResponse("index.html", {"request": request, "user": user, "app_name": cfg.app_name})


@app.post("/register")
def register(email: str = Form(...), password: str = Form(...)):
    email = email.strip().lower()
    if len(password) < 10: raise HTTPException(400, "Пароль должен содержать не менее 10 символов.")
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.email == email)): raise HTTPException(409, "Email уже зарегистрирован.")
        user = User(email=email, password_hash=hash_password(password)); db.add(user); db.commit(); db.refresh(user)
        audit(db, "user_registered", str(uuid4()), user.id)
    response = RedirectResponse("/dashboard", status_code=303); response.set_cookie("dis360_session", make_session(user.id), httponly=True, secure=cfg.app_env == "production", samesite="lax", max_age=604800); return response


@app.post("/login")
def login(email: str = Form(...), password: str = Form(...)):
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email.strip().lower()))
        if not user or not verify_password(password, user.password_hash):
            audit(db, "login_failed", str(uuid4()), details={"email_masked": "***"}); raise HTTPException(401, "Неверный email или пароль.")
        audit(db, "login_success", str(uuid4()), user.id)
    response = RedirectResponse("/dashboard", status_code=303); response.set_cookie("dis360_session", make_session(user.id), httponly=True, secure=cfg.app_env == "production", samesite="lax", max_age=604800); return response


@app.post("/logout")
def logout():
    response = RedirectResponse("/", status_code=303); response.delete_cookie("dis360_session"); return response


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    with SessionLocal() as db:
        user = current_user(request, db)
        if not user: return RedirectResponse("/", status_code=303)
        records = db.scalars(select(FileRecord).where(FileRecord.user_id == user.id).order_by(FileRecord.created_at.desc())).all()
    return templates.TemplateResponse("dashboard.html", {"request": request, "user": user, "records": records, "app_name": cfg.app_name})


@app.post("/analyze", response_class=HTMLResponse)
async def analyze(request: Request, data_file: UploadFile = File(...), chart_type: str = Form("bar"), x_column: str = Form(""), y_column: str = Form("")):
    request_id = str(uuid4())
    with SessionLocal() as db:
        user = current_user(request, db)
        if not user: raise HTTPException(401, "Сначала войдите.")
        try:
            file_id, original, kind, total, path = await files.save(data_file)
            record = FileRecord(id=file_id, user_id=user.id, original_name=original, stored_name=path.name, kind=kind, size_bytes=total); db.add(record); db.commit()
            result = files.analyze(path, kind)
            chart = charts.create(path, chart_type, x_column or None, y_column or None) if kind == "table" else None
            conversation = Conversation(id=uuid4().hex, user_id=user.id, title=f"Анализ {original}"); db.add(conversation); db.flush()
            db.add_all([Message(conversation_id=conversation.id, role="user", text=f"Проанализируй {original}"), Message(conversation_id=conversation.id, role="assistant", text=result["summary"])]); db.commit()
            audit(db, "file_analyzed", request_id, user.id, {"file_id": file_id, "kind": kind, "size": total})
        except FileServiceError as exc:
            audit(db, "analysis_failed", request_id, user.id, {"error_type": type(exc).__name__}); raise HTTPException(400, str(exc)) from exc
    return templates.TemplateResponse("result.html", {"request": request, "user": user, "record": record, "result": result, "chart": chart, "request_id": request_id})


@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request):
    with SessionLocal() as db:
        user = current_user(request, db)
        if not user or not user.is_admin: raise HTTPException(403, "Доступ только администратору.")
        stats = {"users": db.scalar(select(func.count(User.id))), "files": db.scalar(select(func.count(FileRecord.id))), "messages": db.scalar(select(func.count(Message.id))), "errors": db.scalar(select(func.count(AuditLog.id)).where(AuditLog.event.like("%failed%")))}
        logs = db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(30)).all()
    return templates.TemplateResponse("admin.html", {"request": request, "user": user, "stats": stats, "logs": logs})


@app.websocket("/ws/status")
async def websocket_status(websocket: WebSocket):
    token = websocket.cookies.get("dis360_session")
    if not read_session(token):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION); return
    await websocket.accept()
    await websocket.send_json({"stage": "connected", "message": "ДИС готов к анализу"})
    try:
        while True:
            message = await websocket.receive_text()
            await websocket.send_json({"stage": "ready", "message": "Канал работает", "echo": message[:40]})
    except WebSocketDisconnect:
        logger.info("websocket_disconnected")

