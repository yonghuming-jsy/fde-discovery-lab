# Knowledge Wiki SaaS

An MVP multi-tenant knowledge platform based on the latest whiteboard requirements: FastAPI, an AI Harness, RAG, LLM Wiki/knowledge graph, and layered SaaS permissions. Ollama provides local chat and embedding inference.

## Features

- SaaS platform administrator creates tenants and their initial administrators.
- Tenant administrators manage users, roles, and organization-unit trees.
- Unit administrators are limited to their unit and descendants.
- Knowledge bases are tenant- or unit-scoped; all API access is checked server-side.
- Import Markdown or UTF-8 text, chunk it, and index it with Ollama embeddings.
- Ask questions with tenant-scoped retrieval and document/chunk citations.
- Generate a source-linked Wiki graph; drafts remain unpublished until an administrator approves them.
- AI Harness centralizes authorization context, retrieval, Ollama calls, output checks, citations, audit events, and basic quality metrics.

The earlier whiteboard mentioned examcoo.com. This MVP treats it only as a possible public reference/source; it does not crawl or reproduce that service.

## Run with Docker

1. Copy `.env.example` to `.env`. Set `POSTGRES_PASSWORD` to a fresh hexadecimal value (for example, `openssl rand -hex 24`), set a unique `JWT_SECRET`, bootstrap admin email, and a password of at least 12 characters.
2. Start the database and API:

   docker compose up --build

3. Open http://localhost:8000. Sign in with the bootstrap administrator.
4. Create a tenant and initial tenant admin in the Platform Admin panel.
5. Start Ollama when AI indexing and answers are needed:

   docker compose --profile ai up -d ollama

6. Pull the configured models:

   docker compose exec ollama ollama pull qwen3:8b
   docker compose exec ollama ollama pull nomic-embed-text

The model names in those commands are examples. Set OLLAMA_CHAT_MODEL and OLLAMA_EMBED_MODEL in .env to models supported by your machine, then restart the API.

## Local development

Use Python 3.11+, a PostgreSQL database, and a local Ollama service. Install dependencies with `pip install -r requirements.txt`, copy `.env.example` to `.env`, set `POSTGRES_HOST=localhost`, then run:

- alembic upgrade head
- python -m app.seed
- uvicorn app.main:app --reload

Interactive API documentation is available at /docs; health status is at /healthz.

## Deploy a public demo on Render

The repository includes a Render Blueprint in `render.yaml`. Connect this GitHub repository to Render and deploy the Blueprint in Singapore. The API uses Render's free web service and an external PostgreSQL database; Neon is a suitable free-tier option.

During setup, provide `DATABASE_URL` from the database provider, the bootstrap administrator email, and a unique password of at least 12 characters. Render generates `JWT_SECRET` automatically. Keep database credentials and passwords in the hosting dashboard, never in Git.

Render's free web service sleeps after 15 minutes without traffic and can take about a minute to wake. The free Render Postgres database expires after 30 days, so this Blueprint does not create one. A free database provider still has storage and compute quotas; export or back up important data.

RAG indexing, AI answers, and Wiki graph generation require an Ollama endpoint reachable from Render. `localhost` and the Docker Compose-only hostname `ollama` are not reachable from the hosted service. Add `OLLAMA_BASE_URL`, `OLLAMA_CHAT_MODEL`, and `OLLAMA_EMBED_MODEL` in Render after providing a reachable Ollama host. The API and account console can run without those AI settings.

## Roles and scope

| Role | Scope |
| --- | --- |
| Platform admin | Create and list tenants; does not automatically read tenant knowledge |
| Tenant admin | Manage all users, units, and knowledge bases in one tenant |
| Unit admin | Manage their unit and descendants |
| Member | Read tenant-shared knowledge bases and knowledge bases assigned to their unit |

Members can ask questions and read published Wiki pages. Only tenant and in-scope unit administrators can create knowledge bases, import or reindex documents, generate Wiki drafts, and publish them. A unit administrator cannot create or modify tenant-wide knowledge bases.

## Current MVP limits

- Imports accept text pasted in the console or UTF-8 Markdown/plain-text content. PDF and Office extraction are not included.
- Embeddings are stored as JSON arrays and ranked in application memory. This is intended for small MVP datasets; use pgvector or a dedicated vector service before scaling.
- The graph extractor is LLM-based. Sources are preserved, and new results remain drafts until an administrator publishes them.
- Harness is implemented as an internal replaceable layer because the whiteboard did not name a specific product or Python package.
- This is a knowledge-base/Wiki MVP, not an online examination system.

No real credentials or model data are committed to the repository.
