# Deploying docpipe to Railway

Five services: `frontend`, `backend`, `worker`, Postgres, Redis. Uploaded PDFs
live in Cloudflare R2, not on a disk.

Everything below was run against a real deployment. The gotchas at the end are
things that actually bit, not precautions.

## Why R2 and not a volume

Under docker-compose the API and the worker share `./data` as a bind mount, so
the API writes an upload and the worker reads it back off the filesystem. That
stops working the moment they become separate services: **Railway attaches a
volume to exactly one service** (Render is the same), so a shared disk is not
available at any price. Every worker read would be a `FileNotFoundError`.

So the deploy sets `STORAGE_BACKEND=s3` and both services talk to the same R2
bucket. R2's free tier covers this comfortably — 10 GB stored, 1M writes, 10M
reads per month, no egress charge.

Local development is unaffected: `STORAGE_BACKEND` defaults to `local` and
`make up` still works with no cloud account.

## Config as Code is dead — don't reach for railway.json

Railway deprecated `railway.json` / `railway.toml`. Existing files keep working
until 2026-12-01, but **services created after 2026-08-28 cannot opt in at all**.
The dashboard will happily accept a path in the Config File Path field and then
ignore it, which is a slow way to learn this.

Its replacement, Infrastructure as Code (`.railway/railway.ts`), cannot set
`rootDirectory` — the one setting a monorepo like this one most needs.

What works is the GraphQL API via `railway api`. Step 4 uses it, and it handles
`rootDirectory` too, so no dashboard clicking is required.

## 1. Create the R2 bucket

Cloudflare dashboard → R2:

1. Create a bucket, e.g. `docpipe`.
2. Create an **R2 API token** with *Object Read & Write* scoped to that bucket.
3. Note the **Access Key ID**, **Secret Access Key**, and your **Account ID**.

The S3 endpoint is `https://<account-id>.r2.cloudflarestorage.com`. R2 addresses
the bucket in the path, so the bucket name is not part of the hostname. Strip
the angle brackets when substituting the account ID — a literal `<` in the
hostname surfaces as a *recoverable* `StorageError`, so every document burns all
four retry attempts before failing and it looks like a flaky network.

## 2. Create the project and datastores

```bash
npm i -g @railway/cli
railway login
railway init --name docpipe
railway add --database postgres
railway add --database redis
```

## 3. Create the three app services

```bash
railway add --repo <owner>/docpipe --branch main --service backend
railway add --repo <owner>/docpipe --branch main --service worker
railway add --repo <owner>/docpipe --branch main --service frontend
```

`backend` and `worker` build the *same image* from `/backend` and differ only in
start command — the API runs uvicorn, the worker runs Celery. That is the point
of the architecture, and why they are two services rather than one container
running both.

**Name the backend service exactly `backend`** — the frontend reaches it as
`backend.railway.internal`.

These first builds fail. They build from the repo root, which has no Dockerfile,
until step 4 sets the root directories. That is expected.

## 4. Configure the services (GraphQL)

Collect the environment ID from `railway status` and the service IDs from the
JSON each `railway add` printed, then apply settings with `serviceInstanceUpdate`:

```bash
railway api -f mutation.graphql --variables @vars.json
```

`mutation.graphql`:

```graphql
mutation SetServiceConfig($sid: String!, $eid: String, $input: ServiceInstanceUpdateInput!) {
  serviceInstanceUpdate(serviceId: $sid, environmentId: $eid, input: $input)
}
```

`vars.json` is `{"sid": ..., "eid": ..., "input": {...}}`, with `input` per service:

| Service | rootDirectory | startCommand | other |
| --- | --- | --- | --- |
| `backend` | `/backend` | *(unset — image CMD)* | `healthcheckPath: /health`, `preDeployCommand: ["alembic upgrade head"]`, `restartPolicyType: ON_FAILURE` |
| `worker` | `/backend` | `celery -A app.celery_app worker --loglevel=info --concurrency=4` | `restartPolicyType: ALWAYS` |
| `frontend` | `/frontend` | *(unset — image CMD)* | `healthcheckPath: /`, `restartPolicyType: ON_FAILURE` |

Leave `startCommand` unset for `backend` and `frontend` so the Dockerfile `CMD`
handles `$PORT`. Only the worker needs an override, because it shares the
backend's image.

Ignore the `builder` field. Its enum has no `DOCKERFILE` value; Railway detects
the Dockerfile at the root directory on its own.

Read the settings back afterwards. A `true` return means the mutation was
accepted, not that it did what you meant.

## 5. Environment variables

Set with `railway variable set KEY=value --service <svc> --skip-deploys`.
`--skip-deploys` matters: without it every variable triggers a rebuild.

For secrets, pipe rather than paste, so values stay out of shell history:

```bash
printf '%s' "$SECRET" | railway variable set ANTHROPIC_API_KEY --stdin --service worker --skip-deploys
```

### backend and worker (both)

```
DATABASE_URL          = postgresql+psycopg://${{Postgres.PGUSER}}:${{Postgres.PGPASSWORD}}@${{Postgres.RAILWAY_PRIVATE_DOMAIN}}:5432/${{Postgres.PGDATABASE}}
CELERY_BROKER_URL     = ${{Redis.REDIS_URL}}/0
CELERY_RESULT_BACKEND = ${{Redis.REDIS_URL}}/1
STORAGE_BACKEND       = s3
S3_ENDPOINT_URL       = https://<account-id>.r2.cloudflarestorage.com
S3_BUCKET             = docpipe
S3_ACCESS_KEY_ID      = <R2 access key id>
S3_SECRET_ACCESS_KEY  = <R2 secret access key>
S3_REGION             = auto
```

**Do not use `${{Postgres.DATABASE_URL}}` directly.** Railway hands it out as
`postgresql://`, which makes SQLAlchemy reach for psycopg2 — not installed here,
so both services crash on startup. The composed form above pins the `+psycopg`
driver and still resolves over the private network.

`S3_REGION=auto` is required: R2 has no regions, but botocore refuses to sign a
request without one.

### backend only

```
PORT = 8000
```

Set explicitly so the frontend can name a fixed port in `API_URL`. The backend
gets no `ANTHROPIC_API_KEY` — it never calls the LLM, and keeping the key off
the internet-facing service is free.

### worker only

```
ANTHROPIC_API_KEY      = <your key>
ANTHROPIC_WORKSPACE_ID = <only for identity-linked keys>
LLM_PROVIDER           = anthropic
LLM_MODEL              = claude-haiku-4-5
```

No `PORT` — the worker serves no HTTP. That is why Railway suits this project: a
portless service is ordinary here, where Render bills it as a paid-only
Background Worker.

### frontend

```
API_URL = http://backend.railway.internal:8000
```

Consumed at **build** time, not runtime — see the gotcha below.

## 6. Deploy

```bash
railway redeploy --service backend  --from-source -y   # first: runs migrations
railway redeploy --service worker   --from-source -y
railway redeploy --service frontend --from-source -y
railway domain --service frontend                      # public URL
```

`--from-source` pulls the latest commit and rebuilds. Plain `redeploy` reruns the
existing (failed) deployment, which is not what you want after step 4.

## 7. Verify

Don't trust status fields; check the evidence.

1. `GET https://<frontend-domain>/` returns 200.
2. `POST /api/batches` with two or three PDFs from `data/test/` returns a batch id.
3. Polling the batch reaches `completed`.
4. Backend logs show alembic `0001 -> 0002 -> 0003` and `GET /health 200`.
5. Worker logs show `downloaded s3://…` lines from *different* `ForkPoolWorker-N`
   processes — that is parallelism and R2 both, in one line.
6. `GET /api/documents/<id>` returns a real summary and `model: claude-haiku-4-5`.

On Railway the API and worker share no disk, so a document reaching `done` is
itself proof the R2 round trip worked.

## 8. Stopping and restarting

**`railway down` does not work.** It exits 0, prints nothing, ignores
`--service`, and only ever acts on the linked service. `deploymentStop` is worse:
it returns `true` and changes nothing. Neither is safe to rely on.

What works is `deploymentRemove`. Find the active deployment, then remove it:

```bash
EID=<environment id>

railway api 'query($e:String!,$s:String!){ serviceInstance(environmentId:$e, serviceId:$s){ activeDeployments{ id status } } }' \
  --raw-var e=$EID --raw-var s=<SERVICE_ID>

railway api 'mutation($id:String!){ deploymentRemove(id:$id) }' --raw-var id=<DEPLOYMENT_ID>
```

Verify by re-running the query: **an empty `activeDeployments` list is the only
trustworthy signal.** `railway service status` reports `SUCCESS` for services
that have no active deployment at all, so it cannot confirm a stop.

Stop `frontend`, `backend`, and `worker`. Leave Postgres and Redis running —
together they are about 200 MB (~$2/mo), the smallest slice of the bill, and it
sidesteps any question about what removing a database deployment does to its
volume.

To restart, backend first so migrations run before the worker starts:

```bash
railway redeploy --service backend  --from-source -y
railway redeploy --service worker   --from-source -y
railway redeploy --service frontend --from-source -y
```

The public domain survives a stop; the URL 404s while down and returns when the
frontend is back.

## Gotchas

**`API_URL` is baked in at build time.** The rewrite destination in
`next.config.ts` is resolved during `next build` and written into
`.next/routes-manifest.json`; it is not re-read per request. A runtime-only
`API_URL` leaves `http://localhost:8000` compiled in, and every `/api/*` call
dies with `ECONNREFUSED ::1:8000`. Railway injects service variables into a
Dockerfile build only for names declared with `ARG`, in the stage that needs
them — hence `ARG API_URL` in the frontend's build stage. compose hides this,
because `next dev` re-evaluates the config at startup.

**Bind `0.0.0.0`, not `::`.** Railway's edge proxy expects `0.0.0.0` and the
injected `PORT`. `--host ::` is not a dual-stack shortcut: asyncio sets
`IPV6_V6ONLY` on the listening socket regardless of `net.ipv6.bindv6only`, so a
`::` bind refuses IPv4 outright — measured in this image, which answered on
`[::1]` and refused `127.0.0.1`. The exception is a Railway environment created
before 2025-10-16, which has IPv6-only private networking and does need `::`.
That is genuinely either/or with one uvicorn bind, and private-only is fine here
since the backend has no public domain.

**Redis database indices.** `${{Redis.REDIS_URL}}/0` and `/1` append cleanly and
keep the broker and result backend separate, as compose does.

**Cost.** Railway is $5/mo (Hobby) plus metered usage at $20/vCPU/mo and
$10/GB RAM/mo, with no scale-to-zero — idle services bill for resident memory.
All five sit around 1.5–2 GB, dominated by the Celery worker's four prefork
children, so expect roughly **$20–30/mo** running continuously. Deploying,
testing, and recording is well under a dollar; the plan fee dominates. Stopping
the three app services between demos drops it to about $2/mo for the datastores.
Lowering `--concurrency` is the other lever, at the cost of the parallelism the
project exists to demonstrate.
