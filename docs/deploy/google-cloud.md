# Deploy to Google Cloud from scratch — Cloud Run + self-hosted Postgres

Target architecture (cheap and boring on purpose):

- **Streamlit app → Cloud Run** (serverless containers, scale-to-near-zero,
  you already know it). No server to patch.
- **Postgres → one small GCE VM** (e2-small + 20 GB balanced disk) running
  stock Postgres in Docker. Cloud SQL/AlloyDB would bill hundreds/month for
  idle capacity you don't need at 10-20 users; a VM costs single digits.
- **Backups → GCS bucket** (nightly `pg_dump`, pennies/GB).
- **Secrets → Secret Manager.** **Private link** Cloud Run ↔ VM via a
  Serverless VPC Access connector (Postgres never gets a public IP).

```
users → Cloud Run (spectrum app) ──VPC connector──▶ GCE VM (postgres:5432, internal IP only)
                        │                                     │
                        └─ Secret Manager (keys)              └─ nightly pg_dump → GCS bucket
```

> Regional note: put project, VM, connector, bucket, and Cloud Run in the
> **same region** (e.g. `asia-south1` if users are in India — check current
> Cloud Run/GCE availability). Cross-region traffic adds latency and egress cost.

---

## Phase 0 — Project, billing, APIs

**Purpose:** a clean billing boundary and the service endpoints everything below calls.

1. Create a project (e.g. `spectrum-news-prod`) and attach billing.
2. Enable these APIs (**purpose** in brackets). Console: *APIs & Services →
   Enable*, or via CLI:
   ```bash
   gcloud services enable run.googleapis.com \
     artifactregistry.googleapis.com cloudbuild.googleapis.com \
     secretmanager.googleapis.com vpcaccess.googleapis.com \
     compute.googleapis.com storage.googleapis.com \
     monitoring.googleapis.com logging.googleapis.com
   ```
   - `run` — Cloud Run itself. `artifactregistry` — private container images.
   - `cloudbuild` — builds the image from the repo (no local Docker needed).
   - `secretmanager` — API keys outside the image/env files.
   - `vpcaccess` — the private connector (Phase 3).
   - `compute` — the Postgres VM. `storage` — backup bucket.
   - `monitoring`/`logging` — uptime checks, log-based alerts (Phase 6).
3. `gcloud auth login && gcloud config set project <id> && gcloud config set run/region <region>`.

## Phase 1 — Backup bucket (first, so it exists before data does)

**Purpose:** a place for DB dumps that survives even if the VM's disk dies.

```bash
gcloud storage buckets create gs://spectrum-news-backups \
  --location=<region> --default-storage-class=NEARLINE --uniform-bucket-level-access
gcloud storage buckets update gs://spectrum-news-backups --lifecycle-file=- <<'EOF'
{"rule":[{"action":{"type":"Delete"},"condition":{"age":30}}]}
EOF
```
**What this does:** Nearline matches nightly-write/rare-read; the lifecycle rule auto-deletes dumps older than 30 days so storage can't grow forever.

## Phase 2 — Postgres VM (your "managed instance")

**Purpose:** a $5-15/mo database server you fully control.

1. Create it:
   ```bash
   gcloud compute instances create spectrum-db \
     --zone=<region>-a --machine-type=e2-small \
     --image-family=debian-12 --image-project=debian-cloud \
     --boot-disk-size=20GB --boot-disk-type=pd-balanced \
     --tags=spectrum-db --no-address
   ```
   **What this does:** Debian 12 box, 20 GB disk (separate data growth from the
   boot disk later if needed). `--no-address` = no public IP at all.
2. Install Docker on it (`ssh`, then the standard Docker CE install), and run
   **only Postgres** (the app lives on Cloud Run):
   ```yaml
   # /opt/spectrum/db-compose.yml on the VM
   services:
     db:
       image: postgres:16-alpine
       restart: unless-stopped
       environment:
         POSTGRES_USER: spectrum
         POSTGRES_DB: spectrum
         POSTGRES_PASSWORD: <long-random>   # also stored in Secret Manager, Phase 4
         TZ: UTC
       ports: ["127.0.0.1:5432:5432"]        # localhost only; Cloud Run arrives via VPC
       volumes: [pgdata:/var/lib/postgresql/data]
   volumes: { pgdata: {} }
   ```
3. Allow Cloud Run in: firewall rule permitting TCP 5432 **only from the VPC
   connector's subnet** (created Phase 3) to targets tagged `spectrum-db`.
   **What this does:** Postgres is unreachable from the internet; only your
   Cloud Run service can open connections.
4. Initialize schema once: `alembic upgrade head` with
   `DATABASE_URL=postgresql+psycopg://spectrum:<pw>@<vm-internal-ip>:5432/spectrum`
   (VM internal IP from `gcloud compute instances describe`), then import
   history: `uv run python scripts/import_sqlite.py --from data/spectrum.db --to <same-url>`.
5. Nightly dumps to GCS — cron on the VM (needs the `storage.objectCreator`
   role on its service account):
   ```cron
   0 2 * * * docker exec spectrum-db-db-1 pg_dump -U spectrum -Fc spectrum | \
     gcloud storage cp - gs://spectrum-news-backups/spectrum-$(date -u +\%F).dump
   ```
   **What this does:** one restorable snapshot/day, independent of the VM's disk.

## Phase 3 — Private networking (VPC, connector, firewall)

**Purpose:** lets Cloud Run talk to the VM's internal IP without exposing Postgres.

No hand-built subnets needed: every GCP project ships a `default` VPC in
auto mode (one subnet per region, pre-filled routes/firewall). You only add a
connector slice and one rule on top:

```bash
# 1. Reserve a /28 inside the default VPC for Cloud Run traffic.
gcloud compute networks vpc-access connectors create spectrum-conn \
  --region=<region> --network=default --range=10.8.0.0/28
# Check 10.8.0.0/28 doesn't overlap your region's default subnet first:
#   gcloud compute networks subnets list --network=default --filter="region:(<region>)"
# If it overlaps, pick another RFC 1918 /28 (e.g. 10.9.0.0/28) and use it below too.

# 2. Read back the connector's actual range (use THIS in the firewall rule).
gcloud compute networks vpc-access connectors describe spectrum-conn \
  --region=<region> --format='value(ipCidrRange)'

# 3. Admit Postgres traffic ONLY from that range, ONLY to the DB VM.
gcloud compute firewall-rules create spectrum-db-from-run \
  --network=default --direction=INGRESS --action=ALLOW --rules=tcp:5432 \
  --source-ranges=10.8.0.0/28 --target-tags=spectrum-db
```
**What this does:** (1) carves a tiny subnet whose traffic originates inside
your VPC; (2) confirms the exact CIDR; (3) punches a single pinhole —
TCP 5432 from the connector range to VMs tagged `spectrum-db` (set in
Phase 2). Postgres stays unreachable from the internet. The VM's own internal
IP (for `DATABASE_URL`) comes from the region's default subnet:
`gcloud compute instances describe spectrum-db --zone=<region>-a
--format='value(networkInterfaces[0].networkIP)'`.

## Phase 4 — Secrets

**Purpose:** keys live in Google's vault, mounted as env vars; never in the image.

```bash
printf '%s' '<openrouter-key>' | gcloud secrets create openrouter-api-key --data-file=-
printf '%s' '<postgres-pw>'   | gcloud secrets create postgres-password --data-file=-
printf '%s' 'postgresql+psycopg://spectrum:<pw>@<vm-internal-ip>:5432/spectrum' \
  | gcloud secrets create database-url --data-file=-
```
Grant the Cloud Run runtime identity `roles/secretmanager.secretAccessor` on all three.
**What this does:** the service reads secrets at boot; rotation = new version, no redeploy.

## Phase 5 — Build + deploy the app to Cloud Run

**Purpose:** ship the Streamlit container where users reach it.

```bash
# repo root has the Dockerfile already
gcloud builds submit --tag <region>-docker.pkg.dev/<project>/spectrum/app:v1
gcloud run deploy spectrum \
  --image <region>-docker.pkg.dev/<project>/spectrum/app:v1 \
  --region <region> --port 8501 --allow-unauthenticated \
  --cpu 2 --memory 2Gi --concurrency 20 --min-instances 1 --max-instances 3 \
  --vpc-connector spectrum-conn \
  --set-secrets OPENROUTER_API_KEY=openrouter-api-key:latest,DATABASE_URL=database-url:latest \
  --set-env-vars RATING_MODEL=google/gemini-2.5-flash-lite,SEARCH_MODEL=deepseek/deepseek-v4-flash
```
Flag rationale: `--min-instances 1` avoids Streamlit cold starts for your small
user base (one warm instance ≈ the main fixed cost); `--concurrency 20` matches
one instance per user peak; `--max-instances 3` caps the bill; `--port 8501`
is Streamlit's listen port (already in the Dockerfile CMD).

Verify: open the service URL, run a default topic, confirm history persists
across two revisits (= Postgres round-trip works).

## Phase 6 — Ops: alerts, budgets, domain (optional)

**Purpose:** know before users tell you.

1. Uptime check on the Cloud Run URL (Cloud Monitoring, 5 min) → alert to email.
2. Log-based alert: `severity>=ERROR` rate spike in `resource.type="cloud_run_revision"`.
3. Billing budget alert at 50/100% of your expected monthly number.
4. Custom domain — see Phase 7 below (buy → verify → map → managed TLS).
5. Kill-the-box drill quarterly: delete VM, recreate from Phase 2, restore latest
   GCS dump (`gcloud storage cp … - | pg_restore`), redeploy = `gcloud run deploy` same flags.

## Phase 7 — Custom domain (buy → verify → map → TLS)

**Purpose:** `news.yourdomain.com` instead of the `*.run.app` URL, with
Google-managed TLS (no certbot, no renewals).

1. **Buy** the domain at any registrar (Namecheap, Cloudflare, Squarespace —
   Google Domains shut down in 2023, so there is no first-party registrar).
2. **Start the mapping** (use a subdomain like `news.` — apex/root mapping has
   extra DNS constraints):
   ```bash
   gcloud run domain-mappings create --service spectrum \
     --domain news.yourdomain.com --region <region>
   ```
   Console equivalent: Cloud Run → *Manage custom domains → Add mapping*.
   **What this does:** asks Google to serve your service on that hostname and
   prints the DNS records you must add (typically `A` + `AAAA`, or a `CNAME`
   for subdomains).
3. **Add those records at your registrar**, then **verify ownership** when
   prompted (a `TXT` record or Search Console flow, one-time per domain).
4. **Wait for the certificate**: status moves `Provisioning → Ready`
   (`gcloud run domain-mappings describe`). Usually minutes, can take up to
   ~24h on a fresh domain — TLS is fully managed after that.
5. Nothing in the app changes (no absolute URLs; Streamlit serves whatever
   `Host` arrives). Enforce HTTPS-only in the mapping settings.

## Cost shape (magnitudes, verify current pricing)

VM (e2-small + 20 GB) + one warm Cloud Run instance + GCS dumps ≈ low tens of
USD/month at 10-20 users; OpenRouter usage dominates only if cache is cold —
keep `CACHE_TTL_SECONDS` high and the nightly judge evals (ticket 04) will show
spend trends. If Cloud Run ever feels dear, the whole stack also runs as plain
`docker compose` on the VM (see README) — nothing here locks you in.

## Phase 8 — CI/CD, staging, rollback, go-live

**Purpose:** pushes become boring: build → stage → verify → promote, with a
one-command way back.

1. **CI on every push** (GitHub Actions, `.github/workflows/ci.yml`):
   `uv sync` → `uv run python -m unittest discover -s tests` (the 42 hermetic
   ones; integration file self-skips without keys). **What this does:** a red
   main is impossible to deploy by accident.
2. **Build on tag, not on push.** Cloud Build trigger on `v*` tags builds
   `:vX.Y` images; pushes to `master` only run CI. **What this does:** every
   prod image maps to a reviewed tag, and `:latest` never moves under you.
3. **Staging service** = second Cloud Run service (`spectrum-staging`,
   `--min-instances 0`, same VPC connector, staging Postgres DB `spectrum_stg`
   on the same VM). Deploy tag there first, click through one default topic,
   then promote the identical image to prod. **What this does:** prod only ever
   runs images a human already exercised.
4. **Rollback** = instant traffic switch, no rebuild:
   ```bash
   gcloud run services update-traffic spectrum --to-revisions <prev-rev>=100 --region <region>
   ```
   **What this does:** Cloud Run keeps prior revisions warm-addressable; a bad
   deploy heals in seconds. DB migrations only ever add (never drop/rename),
   so old code keeps working against the migrated schema.
5. **Go-live checklist** (run once, keep ticked in the release notes):
   - [ ] Staging topic run renders spectrum + history persists (Postgres round-trip)
   - [ ] `tests/test_integration.py` green against staging
     (`TEST_POSTGRES_URL` → staging DB; `RUN_LIVE_LLM_TESTS=1` for model behavior)
   - [ ] Billing budget + uptime check + error-rate alert (Phase 6) firing to email
   - [ ] Latest GCS dump restorable (Phase 2 drill, quarterly cadence)
   - [ ] `OPENROUTER_API_KEY` spend cap / cache TTL reviewed for launch traffic
6. **Kill-switch (cost panic):** `gcloud run services update spectrum
   --min-instances 0 --max-instances 1` stops idle spend in one command while
   keeping the service reachable; the VM keeps Postgres + backups alive
   regardless.
