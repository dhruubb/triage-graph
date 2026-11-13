# Deploying TriageGraph on Render (API) + Vercel (UI)

```
Browser ──► Vercel (React UI, static)  ──fetch/SSE──►  Render (FastAPI + LangGraph, Docker)
                                                          ├─► Groq (LLMs)
                                                          └─► Qdrant Cloud (runbook vectors)
```

The UI calls the API directly using `VITE_API_URL`, so the long SSE triage streams go straight to Render and are never cut off by a proxy timeout. The API allows the Vercel origin through `CORS_ORIGINS` / `CORS_ORIGIN_REGEX`.

The Render service also serves the UI at its own URL (the Docker image builds it), so `https://<render-url>/` works on its own as a fallback.

Time: about 30–40 minutes the first time.

---

## 0. Before you start

| What | Where | You need |
|---|---|---|
| Groq | console.groq.com → API Keys | `GROQ_API_KEY` |
| Qdrant Cloud | cloud.qdrant.io → free 1 GB cluster. Pick an **Asia (e.g. Singapore/Mumbai)** region to sit near Render Singapore. | URL `https://….cloud.qdrant.io:6333` + API key |
| Render | render.com, sign in with GitHub | — |
| Vercel | vercel.com, sign in with GitHub | — |

Qdrant Cloud is strongly recommended: without it, the API uses an in-memory Qdrant, which re-indexes on every boot and uses more of Render's 512 MB.

## 1. Push the changes

```bash
cd ~/Desktop/triage-graph
git status                       # .env must NOT be listed
git add -A
git commit -m "Prepare for Render + Vercel deployment"
git push origin main
```

CI (`.github/workflows/ci.yml`) still runs lint, tests and the UI build. The GHCR image job is only needed for the Azure path; it's harmless to keep.

## 2. Backend on Render

**Option A, Blueprint (uses `render.yaml`):**

1. Render dashboard → **New** → **Blueprint** → choose `dhruubb/triage-graph` → **Apply**.
2. It asks for the `sync: false` values:
   - `GROQ_API_KEY`
   - `QDRANT_URL`: must include `:6333`
   - `QDRANT_API_KEY`
   - `CORS_ORIGINS`: put `http://localhost:5173` for now. You'll update it after step 3.
3. Wait for the first build (5–10 min: it builds the UI, installs Python deps and bakes in the embedding model).

**Option B, manual:** New → **Web Service** → the repo → Language **Docker** → Region **Singapore** → Instance **Free** → Health check path `/api/health` → add the same env vars as in `render.yaml`.

Check it: open `https://triagegraph-api.onrender.com/api/health` (your URL may differ). Expect:

```json
{"status":"ok","llm":{"provider":"groq",...},"vector_store":{"backend":"qdrant-cloud","chunks":75,...},"incidents":160}
```

## 3. Frontend on Vercel

1. Vercel → **Add New… → Project** → import `dhruubb/triage-graph`.
2. **Root Directory: `frontend`** (click Edit next to it). Framework preset: Vite (auto-detected; `frontend/vercel.json` pins it).
3. **Environment Variables** → add `VITE_API_URL` = your Render URL, e.g. `https://triagegraph-api.onrender.com` (no trailing slash, no `/api`). Tick Production and Preview.
4. **Deploy.** You get something like `https://triage-graph.vercel.app`.

`VITE_*` variables are baked in at build time. If you change `VITE_API_URL` later, redeploy on Vercel.

## 4. Connect the two

On Render → `triagegraph-api` → **Environment**:

- `CORS_ORIGINS` = `https://triage-graph.vercel.app` (your real Vercel domain; comma-separate several, e.g. add `http://localhost:5173`)
- `CORS_ORIGIN_REGEX` is pre-set to allow `triage-graph-*.vercel.app` preview URLs. If your Vercel project has a different name, change `triage-graph` in the regex.

Save → Render redeploys. Then open the Vercel URL: the header chip should say **groq · qdrant-cloud**. Run the first example ticket, approve it, and check that the report appears.

## Things to know about the free tiers

| Issue | What happens | What to do |
|---|---|---|
| Render free sleeps after 15 min idle | First request takes ~1 min; the chip shows "Connecting…" meanwhile | Open `/api/health` a minute before a demo, or switch the plan to **Starter** ($7/mo, always on) |
| Paused runs are in memory | If Render sleeps or redeploys while a run waits for approval, Approve returns "Unknown run" | Start the run again. Long-term fix: LangGraph Postgres checkpointer |
| 512 MB RAM | The embedding model + LangChain fit, but it's tight | If logs show "Out of memory", set `EMBEDDINGS=hash` (lower retrieval quality) or move to **Standard** (2 GB) |
| 0.1 CPU on free | Startup embeds 75 runbook chunks; boot takes longer | Fine for demos; Starter gives 0.5 CPU |
| Groq free limits | "rate limit" errors under load | Wait a minute; `RATE_LIMIT_PER_HOUR` caps per-IP runs |

## Troubleshooting

| Symptom | Fix |
|---|---|
| Chip says **Backend unreachable** | Wrong `VITE_API_URL` (check for trailing slash / missing https) or Render still waking. Redeploy Vercel after fixing. |
| Browser console: **CORS error** | The Vercel origin isn't in `CORS_ORIGINS` exactly (scheme + host, no path, no trailing slash) and doesn't match `CORS_ORIGIN_REGEX`. |
| Render: **No open ports detected** | Make sure the deployed Dockerfile uses `--port ${PORT:-8000}` (it does after this change). |
| `/api/health` shows `"provider": "not configured"` | `GROQ_API_KEY` missing on Render. |
| Render boot crash mentioning Qdrant | `QDRANT_URL` must be `https://…cloud.qdrant.io:6333`, and the key must be a database key. |
| Evaluation tab: "No evaluation results yet" | Run `python -m eval.run` locally, commit `eval/results/latest.json`, push; Render redeploys. |
