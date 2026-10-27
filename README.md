# Autopost · Backend

**REST API that turns a queue of content ideas into scheduled Instagram posts.**

Autopost lets a user sign in with Google, connect one or more Instagram professional accounts, store ideas in collections and create *programs*: cron schedules that pick the next unused idea, generate a carousel with Claude and publish it through the Instagram API. This repository is the FastAPI backend; the dashboard lives in [autopost_frontend](https://github.com/WiktorVerga/autopost_frontend).

![Python](https://img.shields.io/badge/Python_3.14-3776ab?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169e1?logo=postgresql&logoColor=white)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy_2-d71f00)
![Status](https://img.shields.io/badge/status-work_in_progress-orange)

<p align="center">
  <img src="https://raw.githubusercontent.com/WiktorVerga/autopost_frontend/master/docs/screenshots/overview.png" width="80%" alt="Autopost dashboard (frontend) showing programs and recent activity" />
</p>

<sub>The dashboard served by <a href="https://github.com/WiktorVerga/autopost_frontend">autopost_frontend</a>, shown with sample data.</sub>

---

## How it works

```mermaid
flowchart LR
    FE["Next.js dashboard"] -- "/api/* (cookie)" --> API["FastAPI"]
    API --> DB[("PostgreSQL")]
    API -- "OAuth" --> G["Google sign-in"]
    API -- "OAuth + Graph API" --> IG["Instagram API"]
    SCH["Scheduler"] --> PIPE["Pipeline"]
    PIPE -- "idea → carousel.json" --> CL["Claude"]
    PIPE -- "render slides" --> R["HTML template → images"]
    PIPE -- "publish" --> IG
    PIPE --> DB
```

Each program run follows a small state machine:

```
pick next unused idea → post "pending" → generate → "generated" → (publish mode only) publish → "published"
                                             └──────────── any error ────────────▶ "failed" + error log
```

A failed post frees its idea again, so the next run can retry it. In `preview` mode the post is generated and stored but never published.

## Features

- **Google sign-in** via Authlib. The API issues a JWT stored in an HttpOnly cookie (or returned as JSON when no frontend URL is configured).
- **Instagram account linking** with the *Instagram API with Instagram Login*: authorization code → short-lived token → 60-day long-lived token, with a helper to refresh tokens that are about to expire.
- **Encrypted secrets at rest.** Instagram access tokens are stored with a custom SQLAlchemy column type backed by Fernet encryption.
- **CRUD resources** scoped to the signed-in user: idea collections, ideas, programs, Instagram accounts, posts and logs.
- **Programs** with a cron expression, IANA timezone, target account, idea collection and `preview` / `publish` mode.
- **Database migrations** with Alembic.
- **Health check** at `/health` that also pings the database.

## API

Interactive docs are available at `/docs` (Swagger UI) once the server is running.

| Prefix | Endpoints |
|---|---|
| `/auth` | `GET /google/login`, `GET /google/callback`, `GET /me`, `POST /logout` |
| `/idea-collections` | list, get, create, update, delete |
| `/ideas` | list (filter by collection), get, create, update, delete |
| `/programs` | list, get, create, update, delete |
| `/instagram-accounts` | `GET /oauth/login`, `GET /oauth/callback`, list, get, delete |
| `/posts`, `/logs` | list, get, create, update, delete *(implemented, not registered in `main.py` yet)* |
| `/health` | service and database status |

## Tech stack

| Area | Choice |
|---|---|
| Language | Python 3.14, managed with [uv](https://docs.astral.sh/uv/) |
| Web | FastAPI, Uvicorn, Starlette sessions |
| Data | PostgreSQL (psycopg 3), SQLAlchemy 2 (typed `Mapped` models), Alembic |
| Auth | Authlib (Google OAuth), PyJWT, cryptography (Fernet) |
| Integrations | httpx2 for Google and the Instagram Graph API, Claude for content generation |
| Scheduling | APScheduler |
| Config | pydantic-settings (`.env`) |

## Getting started

**Requirements:** Python 3.14, [uv](https://docs.astral.sh/uv/), PostgreSQL, a Google OAuth client and, optionally, an Instagram app on Meta for Developers.

```bash
git clone https://github.com/WiktorVerga/autopost_backend.git
cd autopost_backend
uv sync
cp .env.example .env
```

Start a PostgreSQL instance that matches `DATABASE_URL` in `.env` (the default expects port 5433), for example with Docker:

```bash
docker run -d --name autopost-db -p 5433:5432 \
  -e POSTGRES_USER=autopost -e POSTGRES_PASSWORD=autopost -e POSTGRES_DB=autopost \
  postgres:17
```

Fill in the secrets in `.env` (the file explains each one), then apply the migrations and start the API:

```bash
uv run alembic upgrade head
uv run uvicorn autopost_server.main:app --reload
```

The API is now on <http://localhost:8000> and the docs on <http://localhost:8000/docs>.

### Environment variables

| Variable | Required | Notes |
|---|---|---|
| `DATABASE_URL` | yes | SQLAlchemy URL, e.g. `postgresql+psycopg://autopost:autopost@localhost:5433/autopost` |
| `TOKEN_ENCRYPTION_KEY` | yes | Fernet key used to encrypt Instagram tokens |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` | yes | Google OAuth "Web application" client |
| `SESSION_SECRET_KEY`, `JWT_SECRET_KEY`, `JWT_EXPIRE_MINUTES` | yes | Session and JWT signing |
| `INSTAGRAM_APP_ID`, `INSTAGRAM_APP_SECRET`, `INSTAGRAM_REDIRECT_URI` | no | Without them, linking an Instagram account returns 503 |
| `AUTH_COOKIE_SECURE` | no | `true` in production (HTTPS only) |
| `FRONTEND_URL` | no | Redirect after login and allowed CORS origin |

## Project structure

```
src/autopost_server/
├─ main.py            FastAPI app, middleware, routers, /health
├─ config.py          Settings from .env
├─ db.py              Engine and session dependency
├─ api/routes/        One router per resource
├─ models/            SQLAlchemy models, enums, encrypted column type
├─ schemas/           Pydantic request and response models
├─ services/          Auth, Instagram linking, logs, generation, pipeline
└─ integrations/      Google OAuth client, Instagram API client
alembic/              Migrations
public/template/      HTML template used to render carousel slides
```

## Status and roadmap

The API, authentication and Instagram linking work end to end. The automation part is being built:

- [x] Google login, JWT cookie, user-scoped CRUD
- [x] Instagram OAuth and long-lived tokens, encrypted at rest
- [x] Post pipeline state machine (idea selection, statuses, error logs)
- [ ] Claude integration for `carousel.json` generation
- [ ] Slide rendering from `public/template/carousel.html`
- [ ] Scheduler that runs active programs on their cron
- [ ] Register the `/posts` and `/logs` routers and expose `/contents` for the dashboard
- [ ] Automatic refresh of expiring Instagram tokens

## Author

**Wiktor Verga** · [GitHub](https://github.com/WiktorVerga) · [LinkedIn](https://linkedin.com/in/wiktor-verga)
