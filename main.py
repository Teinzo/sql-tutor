"""SQL Tutor - web aplikacija za AI-potpomognuto učenje SQL-a.

Ulazna točka aplikacije: postavlja FastAPI, statičke datoteke, predloške,
rute stranica te uključuje API usmjerivače.

Pokretanje:
    uvicorn main:app --reload
"""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from auth import get_current_user_optional, purge_expired_sessions
from config import APP_NAME, LLM_MODEL, LLM_PROVIDER, is_llm_configured
from database import init_db
from routes_admin import router as admin_router
from routes_ai import router as ai_router
from routes_auth import router as auth_router
from routes_stats import router as stats_router
from routes_tasks import router as tasks_router
from schemas import list_schemas

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

STATIC_DIR.mkdir(exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    purge_expired_sessions()
    print(f"[{APP_NAME}] Baza podataka spremna.")
    if is_llm_configured():
        print(f"[{APP_NAME}] Jezični model: {LLM_MODEL} ({LLM_PROVIDER})")
    else:
        print(
            f"[{APP_NAME}] UPOZORENJE: OPENAI_API_KEY nije postavljen - "
            "AI funkcionalnosti neće raditi."
        )
    yield


app = FastAPI(
    title=APP_NAME,
    description="Web aplikacija za učenje SQL-a temeljena na umjetnoj inteligenciji",
    version="1.0.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

app.include_router(auth_router)
app.include_router(tasks_router)
app.include_router(ai_router)
app.include_router(stats_router)
app.include_router(admin_router)


def render(request: Request, naziv: str, user: Optional[dict] = None, **kontekst):
    """Pomoćna funkcija koja u svaki predložak ubacuje zajednički kontekst."""
    return templates.TemplateResponse(
        request=request,
        name=naziv,
        context={
            "user": user,
            "app_name": APP_NAME,
            "ai_dostupan": is_llm_configured(),
            **kontekst,
        },
    )


def _na_prijavu() -> RedirectResponse:
    return RedirectResponse(url="/login", status_code=303)


# ---------------------------------------------------------------------------
# Javne stranice
# ---------------------------------------------------------------------------
@app.get("/", include_in_schema=False)
async def stranica_pocetna(
    request: Request, user: Optional[dict] = Depends(get_current_user_optional)
):
    if user:
        return RedirectResponse(url="/dashboard", status_code=303)
    return render(request, "index.html", user)


@app.get("/login", include_in_schema=False)
async def stranica_prijava(
    request: Request, user: Optional[dict] = Depends(get_current_user_optional)
):
    if user:
        return RedirectResponse(url="/dashboard", status_code=303)
    return render(request, "login.html", user)


@app.get("/register", include_in_schema=False)
async def stranica_registracija(
    request: Request, user: Optional[dict] = Depends(get_current_user_optional)
):
    if user:
        return RedirectResponse(url="/dashboard", status_code=303)
    return render(request, "register.html", user)


# ---------------------------------------------------------------------------
# Stranice za prijavljene korisnike
# ---------------------------------------------------------------------------
@app.get("/dashboard", include_in_schema=False)
async def stranica_nadzorna_ploca(
    request: Request, user: Optional[dict] = Depends(get_current_user_optional)
):
    if not user:
        return _na_prijavu()
    return render(request, "dashboard.html", user)


@app.get("/tasks", include_in_schema=False)
async def stranica_zadaci(
    request: Request, user: Optional[dict] = Depends(get_current_user_optional)
):
    if not user:
        return _na_prijavu()
    return render(request, "tasks.html", user, sheme=list_schemas())


@app.get("/tasks/{task_id}", include_in_schema=False)
async def stranica_zadatak(
    task_id: int,
    request: Request,
    user: Optional[dict] = Depends(get_current_user_optional),
):
    if not user:
        return _na_prijavu()
    return render(request, "task_detail.html", user, task_id=task_id)


@app.get("/chat", include_in_schema=False)
async def stranica_chat(
    request: Request, user: Optional[dict] = Depends(get_current_user_optional)
):
    if not user:
        return _na_prijavu()
    return render(request, "chat.html", user, sheme=list_schemas())


@app.get("/generate", include_in_schema=False)
async def stranica_generiranje(
    request: Request, user: Optional[dict] = Depends(get_current_user_optional)
):
    if not user:
        return _na_prijavu()
    return render(request, "generate.html", user, sheme=list_schemas())


@app.get("/progress", include_in_schema=False)
async def stranica_napredak(
    request: Request, user: Optional[dict] = Depends(get_current_user_optional)
):
    if not user:
        return _na_prijavu()
    return render(request, "progress.html", user)


@app.get("/survey", include_in_schema=False)
async def stranica_anketa(
    request: Request, user: Optional[dict] = Depends(get_current_user_optional)
):
    if not user:
        return _na_prijavu()
    return render(request, "survey.html", user)


@app.get("/admin", include_in_schema=False)
async def stranica_admin(
    request: Request, user: Optional[dict] = Depends(get_current_user_optional)
):
    if not user:
        return _na_prijavu()
    if user["role"] != "nastavnik":
        return RedirectResponse(url="/dashboard", status_code=303)
    return render(request, "admin.html", user, sheme=list_schemas())


# ---------------------------------------------------------------------------
# Pomoćni API
# ---------------------------------------------------------------------------
@app.get("/api/schemas", tags=["sheme"])
async def api_sheme():
    """Popis dostupnih vježbovnih shema baza."""
    return {"schemas": list_schemas()}


@app.get("/api/health", tags=["sustav"])
async def api_zdravlje():
    """Provjera stanja sustava i konfiguracije jezičnog modela."""
    return {
        "status": "ok",
        "ai_konfiguriran": is_llm_configured(),
        "provider": LLM_PROVIDER,
        "model": LLM_MODEL if is_llm_configured() else None,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
