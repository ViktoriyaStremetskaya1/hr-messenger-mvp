from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import admin, auth, campaigns, candidates, messaging, scenarios, tags, users, vacancies, webhooks
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.services import messaging as _messaging  # noqa: F401  регистрирует фоновые задачи
from app.services import campaigns as _campaigns  # noqa: F401
from app.services import scenario_engine as _engine  # noqa: F401

setup_logging()
settings = get_settings()

app = FastAPI(title="HR Messenger MVP", version="0.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (auth.router, users.router, vacancies.router, tags.router, candidates.router, admin.router, messaging.router, webhooks.router, scenarios.router, campaigns.router):
    app.include_router(r, prefix="/api")


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
