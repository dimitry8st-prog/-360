from __future__ import annotations

import json
import logging
import logging.config
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select

from app.config import settings
from app.ai_service import AIProviderError, AIService
from app.database import Artifact, AuditLog, Conversation, FileRecord, Message, SessionLocal, User, init_db
from app.security import hash_password, make_session, read_session, verify_password
from app.services import ChartService, ExportService, FileService, FileServiceError, pretty_json

cfg = settings()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.filters["pretty_json"] = pretty_json
templates.env.policies["json.dumps_function"] = lambda obj, **kwargs: json.dumps(obj, ensure_ascii=False, **{k: v for k, v in kwargs.items() if k != "ensure_ascii"})
templates.env.policies["json.dumps_kwargs"] = {"ensure_ascii": False, "sort_keys": False}
files = FileService(cfg)
charts = ChartService(cfg)
exports = ExportService(cfg)
ai = AIService(cfg)
logger = logging.getLogger("dis360")
connections: dict[int, set[WebSocket]] = {}


def configure_logging() -> None:
    logging.config.dictConfig({"version": 1, "disable_existing_loggers": False, "formatters": {"json": {"format": '{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}'}}, "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "json"}}, "root": {"handlers": ["console"], "level": cfg.log_level}})


def audit(db, event: str, request_id: str, user_id: int | None = None, details: dict | None = None) -> None:
    db.add(AuditLog(user_id=user_id, event=event, request_id=request_id, details=json.dumps(details or {}, ensure_ascii=False)))
    db.commit()


def current_user(request: Request, db) -> User | None:
    uid = read_session(request.cookies.get("dis360_session"))
    return db.get(User, uid) if uid else None


def signed_in(user_id: int) -> RedirectResponse:
    response = RedirectResponse("/dashboard", status_code=303)
    response.set_cookie("dis360_session", make_session(user_id), httponly=True, secure=cfg.app_env == "production", samesite="lax", max_age=604800)
    return response


def home_error(message: str, form: str = "login", email: str = "") -> RedirectResponse:
    query = f"error={quote(message)}&form={quote(form)}"
    if email:
        query += f"&email={quote(email)}"
    return RedirectResponse(f"/?{query}", status_code=303)


async def publish(user_id: int, stage: str, message: str) -> None:
    dead: list[WebSocket] = []
    for socket in connections.get(user_id, set()):
        try: await socket.send_json({"stage": stage, "message": message})
        except Exception: dead.append(socket)
    for socket in dead: connections.get(user_id, set()).discard(socket)


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
    if user:
        return RedirectResponse("/dashboard", status_code=303)
    return templates.TemplateResponse("index.html", {
        "request": request,
        "user": user,
        "app_name": cfg.app_name,
        "error": request.query_params.get("error"),
        "form": request.query_params.get("form", "login"),
        "email": request.query_params.get("email", ""),
        "demo_email": cfg.admin_email,
        "demo_password": cfg.admin_password,
    })


@app.get("/register")
@app.get("/login")
def auth_pages():
    return RedirectResponse("/", status_code=303)


@app.post("/register")
def register(email: str = Form(...), password: str = Form(...)):
    email = email.strip().lower()
    if len(password) < 10:
        return home_error("Пароль должен содержать не менее 10 символов.", "register", email)
    with SessionLocal() as db:
        existing = db.scalar(select(User).where(User.email == email))
        if existing:
            if verify_password(password, existing.password_hash):
                audit(db, "login_success", str(uuid4()), existing.id)
                return signed_in(existing.id)
            return home_error("Этот email уже зарегистрирован. Войдите.", "login", email)
        user = User(email=email, password_hash=hash_password(password))
        db.add(user)
        db.commit()
        db.refresh(user)
        audit(db, "user_registered", str(uuid4()), user.id)
        return signed_in(user.id)


@app.post("/login")
def login(email: str = Form(...), password: str = Form(...)):
    email = email.strip().lower()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        if not user or not verify_password(password, user.password_hash):
            audit(db, "login_failed", str(uuid4()), details={"email_masked": "***"})
            return home_error("Неверный email или пароль.", "login", email)
        audit(db, "login_success", str(uuid4()), user.id)
        return signed_in(user.id)


@app.post("/logout")
def logout():
    response = RedirectResponse("/", status_code=303); response.delete_cookie("dis360_session"); return response


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    with SessionLocal() as db:
        user = current_user(request, db)
        if not user: return RedirectResponse("/", status_code=303)
        records = db.scalars(select(FileRecord).where(FileRecord.user_id == user.id).order_by(FileRecord.created_at.desc())).all()
    return templates.TemplateResponse("dashboard.html", {"request": request, "user": user, "records": records, "app_name": cfg.app_name, "error": None})


@app.get("/chat/{conversation_id}", response_class=HTMLResponse)
def chat(request: Request, conversation_id: str):
    with SessionLocal() as db:
        user = current_user(request, db)
        if not user: return RedirectResponse("/", status_code=303)
        conversation = db.scalar(select(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == user.id))
        if not conversation: raise HTTPException(404, "Чат не найден.")
        records = db.scalars(select(FileRecord).where(FileRecord.user_id == user.id).order_by(FileRecord.created_at.desc())).all()
        active = db.get(FileRecord, conversation.active_file_id) if conversation.active_file_id else None
        artifacts = db.scalars(select(Artifact).where(Artifact.conversation_id == conversation.id).order_by(Artifact.created_at.desc())).all()
        messages = list(conversation.messages)
    return templates.TemplateResponse("chat.html", {"request": request, "user": user, "conversation": conversation, "records": records, "active": active, "artifacts": artifacts, "messages": messages, "app_name": cfg.app_name})


@app.post("/chat/new")
def new_chat(request: Request):
    with SessionLocal() as db:
        user = current_user(request, db)
        if not user: raise HTTPException(401, "Сначала войдите.")
        conversation = Conversation(id=uuid4().hex, user_id=user.id, title="Новый анализ")
        db.add(conversation); db.commit()
        audit(db, "chat_created", str(uuid4()), user.id, {"conversation_id": conversation.id})
    return RedirectResponse(f"/chat/{conversation.id}", status_code=303)


@app.post("/chat/{conversation_id}/upload")
async def chat_upload(request: Request, conversation_id: str, data_file: UploadFile = File(...)):
    request_id = str(uuid4())
    with SessionLocal() as db:
        user = current_user(request, db)
        if not user: raise HTTPException(401, "Сначала войдите.")
        conversation = db.scalar(select(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == user.id))
        if not conversation: raise HTTPException(404, "Чат не найден.")
        await publish(user.id, "upload", "Загружаю и проверяю файл…")
        try:
            file_id, original, kind, total, path = await files.save(data_file)
            result = files.analyze(path, kind)
            record = FileRecord(id=file_id, user_id=user.id, original_name=original, stored_name=path.name, kind=kind, size_bytes=total)
            conversation.active_file_id = file_id
            if conversation.title == "Новый анализ": conversation.title = f"Анализ {original}"[:200]
            db.add(record)
            db.add(Message(conversation_id=conversation.id, role="assistant", text=f"Файл «{original}» проверен. {result['summary']} Теперь задайте вопрос или постройте график."))
            db.commit()
            audit(db, "chat_file_uploaded", request_id, user.id, {"file_id": file_id, "kind": kind, "size": total})
            await publish(user.id, "ready", "Файл готов к анализу")
        except FileServiceError as exc:
            audit(db, "chat_upload_failed", request_id, user.id, {"error_type": type(exc).__name__})
            await publish(user.id, "error", str(exc))
            raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/chat/{conversation_id}", status_code=303)


@app.post("/chat/{conversation_id}/activate/{file_id}")
def activate_file(request: Request, conversation_id: str, file_id: str):
    with SessionLocal() as db:
        user = current_user(request, db)
        conversation = db.scalar(select(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == user.id)) if user else None
        record = db.scalar(select(FileRecord).where(FileRecord.id == file_id, FileRecord.user_id == user.id)) if user else None
        if not conversation or not record: raise HTTPException(404, "Файл или чат не найден.")
        conversation.active_file_id = record.id; db.commit()
    return RedirectResponse(f"/chat/{conversation_id}", status_code=303)


@app.post("/chat/{conversation_id}/message")
async def chat_message(request: Request, conversation_id: str, question: str = Form(...)):
    request_id = str(uuid4())
    question = question.strip()
    if not question or len(question) > 4000: raise HTTPException(400, "Сообщение должно содержать от 1 до 4000 символов.")
    with SessionLocal() as db:
        user = current_user(request, db)
        conversation = db.scalar(select(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == user.id)) if user else None
        if not user or not conversation: raise HTTPException(404, "Чат не найден.")
        today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        today_count = db.scalar(select(func.count(Message.id)).join(Conversation).where(Conversation.user_id == user.id, Message.role == "user", Message.created_at >= today)) or 0
        if today_count >= cfg.daily_limit: raise HTTPException(429, "Достигнут лимит запросов. Обратитесь к администратору.")
        context = None
        if conversation.active_file_id:
            record = db.scalar(select(FileRecord).where(FileRecord.id == conversation.active_file_id, FileRecord.user_id == user.id))
            if record: context = files.analyze(cfg.upload_dir / record.stored_name, record.kind)
        history = [{"role": m.role, "content": m.text} for m in conversation.messages]
        db.add(Message(conversation_id=conversation.id, role="user", text=question)); db.commit()
        await publish(user.id, "analysis", "ДИС анализирует контекст…")
        try:
            answer = ai.answer(question, context, history)
            db.add(Message(conversation_id=conversation.id, role="assistant", text=answer.text)); db.commit()
            audit(db, "ai_answer_created", request_id, user.id, {"provider": answer.provider, "model": answer.model, "stub": answer.is_stub})
            await publish(user.id, "ready", "Ответ готов")
        except AIProviderError as exc:
            audit(db, "ai_request_failed", request_id, user.id, {"error_type": type(exc).__name__})
            await publish(user.id, "error", str(exc)); raise HTTPException(502, str(exc)) from exc
    return RedirectResponse(f"/chat/{conversation_id}", status_code=303)


@app.post("/chat/{conversation_id}/chart")
async def chat_chart(request: Request, conversation_id: str, chart_type: str = Form("bar"), x_column: str = Form(""), y_column: str = Form("")):
    with SessionLocal() as db:
        user = current_user(request, db)
        conversation = db.scalar(select(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == user.id)) if user else None
        record = db.get(FileRecord, conversation.active_file_id) if conversation and conversation.active_file_id else None
        if not user or not conversation or not record or record.user_id != user.id: raise HTTPException(400, "Сначала выберите табличный файл.")
        await publish(user.id, "chart", "Строю график по исходным данным…")
        try: chart = charts.create(cfg.upload_dir / record.stored_name, chart_type, x_column or None, y_column or None)
        except (FileServiceError, ValueError) as exc: raise HTTPException(400, str(exc)) from exc
        artifact = Artifact(id=uuid4().hex, user_id=user.id, conversation_id=conversation.id, file_id=record.id, kind="chart", title=f"График {chart_type}: {record.original_name}", url=chart["html_url"])
        db.add(artifact); db.add(Message(conversation_id=conversation.id, role="assistant", text=f"График построен локально. {chart['method']} Проверьте подписи и исходные значения перед управленческим решением.")); db.commit()
        audit(db, "chart_created", str(uuid4()), user.id, {"file_id": record.id, "type": chart_type})
        await publish(user.id, "ready", "График готов")
    return RedirectResponse(f"/chat/{conversation_id}", status_code=303)


@app.post("/chat/{conversation_id}/export")
def export_chat(request: Request, conversation_id: str):
    with SessionLocal() as db:
        user = current_user(request, db)
        conversation = db.scalar(select(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == user.id)) if user else None
        if not user or not conversation: raise HTTPException(404, "Чат не найден.")
        result = exports.markdown(conversation.title, list(conversation.messages))
        artifact = Artifact(id=uuid4().hex, user_id=user.id, conversation_id=conversation.id, file_id=conversation.active_file_id, kind="report", title="Отчёт Markdown", url=result["url"])
        db.add(artifact); db.commit(); audit(db, "report_exported", str(uuid4()), user.id, {"format": "markdown"})
    return RedirectResponse(f"/chat/{conversation_id}", status_code=303)


@app.post("/analyze", response_class=HTMLResponse)
async def analyze(
    request: Request,
    data_file: UploadFile = File(...),
    chart_type: str = Form("bar"),
    x_column: str = Form(""),
    y_column: str = Form(""),
    analyst_mode: str = Form("business"),
    question: str = Form(""),
):
    request_id = str(uuid4())
    with SessionLocal() as db:
        user = current_user(request, db)
        if not user:
            return RedirectResponse("/", status_code=303)
        try:
            file_id, original, kind, total, path = await files.save(data_file)
            record = FileRecord(id=file_id, user_id=user.id, original_name=original, stored_name=path.name, kind=kind, size_bytes=total)
            db.add(record)
            db.commit()
            result = files.analyze(path, kind, analyst_mode, question)
            chart = charts.create(path, chart_type, x_column or None, y_column or None) if kind == "table" else None
            conversation = Conversation(id=uuid4().hex, user_id=user.id, title=f"Анализ {original}")
            db.add(conversation)
            db.flush()
            user_text = question or f"Проанализируй {original}"
            db.add_all([
                Message(conversation_id=conversation.id, role="user", text=user_text),
                Message(conversation_id=conversation.id, role="assistant", text=result["summary"]),
            ])
            db.commit()
            audit(db, "file_analyzed", request_id, user.id, {"file_id": file_id, "kind": kind, "size": total, "mode": analyst_mode})
        except FileServiceError as exc:
            audit(db, "analysis_failed", request_id, user.id, {"error_type": type(exc).__name__})
            records = db.scalars(select(FileRecord).where(FileRecord.user_id == user.id).order_by(FileRecord.created_at.desc())).all()
            return templates.TemplateResponse(
                "dashboard.html",
                {"request": request, "user": user, "records": records, "app_name": cfg.app_name, "error": str(exc)},
                status_code=400,
            )
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
    user_id = read_session(token)
    if not user_id:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION); return
    await websocket.accept()
    connections.setdefault(user_id, set()).add(websocket)
    await websocket.send_json({"stage": "connected", "message": "ДИС готов к анализу"})
    try:
        while True:
            message = await websocket.receive_text()
            await websocket.send_json({"stage": "ready", "message": "Канал работает", "echo": message[:40]})
    except WebSocketDisconnect:
        connections.get(user_id, set()).discard(websocket)
        logger.info("websocket_disconnected")
