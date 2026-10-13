from fastapi import Depends, FastAPI
from sqlalchemy import text
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from autopost_server.api.routes.auth import router as auth_router
from autopost_server.api.routes.idea_collections import router as idea_collections_router
from autopost_server.api.routes.ideas import router as ideas_router
from autopost_server.api.routes.instagram_accounts import router as instagram_accounts_router
from autopost_server.api.routes.programs import router as programs_router
from autopost_server.config import settings
from autopost_server.db import get_db

app = FastAPI(title="Autopost Server")

# serve ad Authlib per conservare state/nonce tra /auth/google/login e il callback
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret_key.get_secret_value())
# il frontend chiama l'API da un'altra origine con credentials: "include" per inviare il cookie
if settings.frontend_origin:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
app.include_router(auth_router)
app.include_router(idea_collections_router)
app.include_router(ideas_router)
app.include_router(instagram_accounts_router)
app.include_router(programs_router)


@app.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "db": "ok"}
