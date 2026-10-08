# Deploying TriageGraph

Order of work: **accounts → local check → GitHub (CI builds the image) → Azure Container Apps**. It takes about 60–90 minutes the first time.

Why not `az containerapp up --source .`? It builds the image with ACR Tasks, which Azure blocks on free and student subscriptions (`TasksOperationsNotAllowed`). GitHub Actions builds the image for free and pushes it to GitHub Container Registry (GHCR), and Azure pulls it from there. This also avoids paying for a container registry.

---

## 1. Accounts and keys (15 min)

| What | Where | You need |
|---|---|---|
| Groq | console.groq.com → API Keys → Create | `GROQ_API_KEY` |
| Qdrant Cloud | cloud.qdrant.io → Create free cluster (1 GB). Pick the region closest to your Azure region. | Cluster URL (`https://….cloud.qdrant.io:6333`) and a database API key |
| Azure for Students | azure.microsoft.com/free/students → sign up with your college email (no card) | A subscription with student credit |
| GitHub | a public repository named `triagegraph` | — |

Check your Groq limits at console.groq.com/settings/limits. The app uses `openai/gpt-oss-20b` for routing, intake, tool calling and judging, and `openai/gpt-oss-120b` for planning. You can change both in `.env`. (Groq retired the Llama 3.1 8B and 3.3 70B models on free tiers in August 2026.)

## 2. Run it locally (10 min)

```bash
cp .env.example .env          # fill GROQ_API_KEY, QDRANT_URL, QDRANT_API_KEY
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
pytest -q                     # should print 44 passed
uvicorn app.main:app --port 8000
```

Open http://localhost:8000/api/health. It should show `"vector_store": {"backend": "qdrant-cloud", "chunks": 75, ...}`. The first start downloads the embedding model (about 70 MB) and ingests the runbooks into Qdrant Cloud.

For the UI in dev mode, run `cd frontend && npm install && npm run dev` and open http://localhost:5173. Try the first example ticket end to end, including approving it.

## 3. Push to GitHub and let CI build the image (10 min)

```bash
git init -b main
git add .
git commit -m "TriageGraph: multi-agent incident triage copilot"
git remote add origin https://github.com/<your-user>/triagegraph.git
git push -u origin main
```

On the **Actions** tab, the `ci` workflow runs lint, tests and the UI build, then builds the Docker image and pushes it to `ghcr.io/<your-user>/triagegraph` with two tags: `latest` and the short commit SHA.

Then make the image public so Azure can pull it without credentials: GitHub → your profile → **Packages** → `triagegraph` → **Package settings** → **Change visibility** → Public.

## 4. Azure Container Apps (20–30 min)

Install the Azure CLI (`brew install azure-cli` on macOS), then:

```bash
az login
az extension add --name containerapp --upgrade
az provider register --namespace Microsoft.App
az provider register --namespace Microsoft.OperationalInsights

RG=rg-triagegraph
LOC=centralindia          # if a policy blocks this region, try southindia, eastus or southeastasia
IMAGE=ghcr.io/<your-user>/triagegraph:latest

az group create --name $RG --location $LOC
az containerapp env create --name env-triagegraph --resource-group $RG --location $LOC

az containerapp create \
  --name triagegraph \
  --resource-group $RG \
  --environment env-triagegraph \
  --image $IMAGE \
  --target-port 8000 --ingress external \
  --cpu 1.0 --memory 2.0Gi \
  --min-replicas 0 --max-replicas 1 \
  --secrets groq-key=<GROQ_API_KEY> qdrant-key=<QDRANT_API_KEY> \
  --env-vars GROQ_API_KEY=secretref:groq-key QDRANT_API_KEY=secretref:qdrant-key QDRANT_URL=<QDRANT_URL> \
             LLM_MODEL_FAST=openai/gpt-oss-20b LLM_MODEL_SMART=openai/gpt-oss-120b \
  --query properties.configuration.ingress.fqdn -o tsv
```

The last line prints your URL, for example `triagegraph.<hash>.centralindia.azurecontainerapps.io`. Open `https://<that>/api/health` and then the site.

`--max-replicas 1` is deliberate: paused runs are held in memory, so all requests must reach the same replica.

### Deploy a new version

After each push to `main`, CI publishes a new image. Deploy it by its commit tag, so Azure creates a new revision:

```bash
az containerapp update -n triagegraph -g rg-triagegraph --image ghcr.io/<your-user>/triagegraph:<short-sha>
```

### Logs and monitoring

```bash
az containerapp logs show -n triagegraph -g rg-triagegraph --follow     # live JSON logs
```

The logs also go to Log Analytics. In the portal, open the container app → **Logs** and run:

```kusto
ContainerAppConsoleLogs_CL
| where ContainerAppName_s == "triagegraph"
| extend j = parse_json(Log_s)
| where j.msg == "node completed"
| summarize p95_ms = percentile(todouble(j.latency_ms), 95), runs = count() by tostring(j.node)
```

The app also exposes `/api/metrics` (run counts, approvals, per-node latency, tokens).

### Before a demo or interview

With `--min-replicas 0`, the app scales to zero when idle, and the first request after that takes 20–40 seconds while it starts. On the day you'll demo it, keep one replica warm (this uses a few dollars of student credit per day):

```bash
az containerapp update -n triagegraph -g rg-triagegraph --min-replicas 1
# afterwards
az containerapp update -n triagegraph -g rg-triagegraph --min-replicas 0
```

### Clean up

```bash
az group delete --name rg-triagegraph --yes
```

## 5. Run the evaluation and publish the numbers

```bash
python -m eval.run --retrieval-only        # quick, no LLM calls
python -m eval.run                         # about 20–30 min on the free tier (it waits 45 s between cases)
git add eval/results/latest.json && git commit -m "Add evaluation results" && git push
```

Deploy the new image tag, and the Evaluation tab shows the results. If Groq's daily limit stops the run, continue the next day with `python -m eval.run --resume`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `/api/health` shows `"provider": "not configured"` | `GROQ_API_KEY` is missing. Check the secret and the `secretref:` env var. |
| “The configured model isn't available” | Groq retired the model. Pick current ones from console.groq.com/docs/models and set `LLM_MODEL_FAST` / `LLM_MODEL_SMART`. |
| Runs fail with a rate-limit message | This is Groq's per-minute limit. Wait a minute. For heavier use, change `LLM_MODEL_FAST` or `LLM_MODEL_SMART`. |
| Container restarts at startup | Check the logs. A wrong `QDRANT_URL` or API key fails the ingest. The URL must include `:6333`. |
| `RequestDisallowedByPolicy` when creating resources | Your student subscription limits regions. Use one it allows. |
| Image pull fails | The GHCR package is still private. Make it public (step 3). |
| Approval button returns “Unknown run” | The app restarted or scaled to zero while the run was paused. Start the run again. |
