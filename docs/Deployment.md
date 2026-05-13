# Deployment Guide

## Option 1 — Self-Hosted via Docker Compose (Recommended)

```bash
git clone https://github.com/your-org/maudesignal.git
cd maudesignal
cp .env.example .env
# Edit .env with your API keys and settings
docker compose up -d
```

Dashboard: http://localhost:8501
API: http://localhost:8000

**Requirements:**
- Docker + Docker Compose v2
- 8 GB RAM minimum (16 GB recommended for local LLM)
- GPU optional but recommended for Ollama local inference
- 20 GB disk space

---

## Option 2 — Local Development

```bash
# Always use python3.12 on this laptop (not bare python)
python3.12 -m pip install -e .
python3.12 -m streamlit run src/maudesignal/dashboard/app.py
```

---

## Option 3 — Air-Gapped (No Internet)

1. Install Ollama and pull a model: `ollama pull llama3.3`
2. Set `LLM_PROVIDER=ollama` in `.env`
3. Run without internet — all analysis stays on-premise

---

## Environment Variables

```bash
# LLM Provider (groq | gemini | anthropic | openai | ollama | pool)
LLM_PROVIDER=groq
GROQ_API_KEY=gsk_...

# Optional cloud providers
GEMINI_API_KEY=...
ANTHROPIC_API_KEY=...
OPENAI_API_KEY=...

# Multi-provider pool (optional)
PROVIDER_FALLBACK_ORDER=gemini,groq,anthropic

# Database
DATABASE_URL=sqlite:///./maudesignal.db
# For PostgreSQL: postgresql://user:pass@host:5432/maudesignal

# Auth
OAUTH2_CLIENT_ID=...
OAUTH2_CLIENT_SECRET=...
OAUTH2_DISCOVERY_URL=https://your-idp/.well-known/openid-configuration
JWT_SECRET_KEY=...

# Multi-tenancy
TENANT_MODE=multi   # or single
```

---

## Docker Compose Services

| Service | Port | Description |
|---|---|---|
| `app` | 8501 | Streamlit dashboard |
| `api` | 8000 | FastAPI backend (Phase 2) |
| `db` | 5432 | PostgreSQL (multi-tenant) |
| `ollama` | 11434 | Local LLM server (optional) |

---

## Production Checklist

- [ ] Set strong `JWT_SECRET_KEY` (min 32 chars random)
- [ ] Enable TLS (nginx reverse proxy with Let's Encrypt)
- [ ] Configure PostgreSQL with per-tenant schemas
- [ ] Set up regular DB backups (`pg_dump` cron)
- [ ] Configure OAuth2 IdP (Keycloak recommended for self-hosted)
- [ ] Run `pip-audit` to check for vulnerable dependencies
- [ ] Review and sign off Validation Package (IQ/OQ/PQ)

---

## Upgrading

```bash
git pull
docker compose down
docker compose build
docker compose up -d
```

Migrations run automatically on startup via Alembic.
