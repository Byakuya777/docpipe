# Deploying docpipe to Railway

Five services: `frontend`, `backend`, `worker`, Postgres, Redis. Uploaded PDFs
live in Cloudflare R2, not on a disk.

## Why R2 and not a volume

Under docker-compose the API and the worker share `./data` as a bind mount, so
the API can write an upload and the worker can read it back off the filesystem.
That stops working the moment they become separate services: **Railway attaches
a volume to exactly one service** (Render is the same), so a shared disk is not
available at any price. Every worker read would be a `FileNotFoundError`.

So the deploy sets `STORAGE_BACKEND=s3` and both services talk to the same R2
bucket. R2's free tier covers this comfortably — 10 GB stored, 1M writes, 10M
reads per month, and no egress charge, so the worker pulling files back costs
nothing.

Local development is unaffected: `STORAGE_BACKEND` defaults to `local` and
`make up` still works with no cloud account.

## 1. Create the R2 bucket

In the Cloudflare dashboard → R2:

1. Create a bucket, e.g. `docpipe`.
2. Create an **R2 API token** with *Object Read & Write* scoped to that bucket.
3. Note the **Access Key ID**, **Secret Access Key**, and your **Account ID**.

The S3 endpoint is `https://<account-id>.r2.cloudflarestorage.com`. R2 addresses
the bucket in the path, so the bucket name is *not* part of the hostname.

## 2. Create the Railway project

New project → deploy from this GitHub repo. Then add the two datastores from
the dashboard: **Postgres** and **Redis**. Both expose reference variables the
app services consume, so no connection strings get typed by hand.

## 3. Create the three app services

Each service points at this same repo with a different root directory and
config file. Set **Root Directory** and **Config-as-code path** in each
service's Settings.

| Service    | Root directory | Config file            |
| ---------- | -------------- | ---------------------- |
| `backend`  | `/backend`     | `railway.json`         |
| `worker`   | `/backend`     | `railway.worker.json`  |
| `frontend` | `/frontend`    | `railway.json`         |

`backend` and `worker` build the *same image* from `/backend` and differ only in
start command — the API runs uvicorn, the worker runs Celery. That is the whole
point of the architecture, and it is why they are two services rather than one
container running both.

If the config-as-code path does not resolve, set the start command directly in
the service's Settings instead; the commands are the `startCommand` values in
those JSON files.

**Name the backend service exactly `backend`** — the frontend reaches it as
`backend.railway.internal`.

Only `frontend` needs a public domain (Settings → Networking → Generate
Domain). The backend is reached privately by the frontend's `/api/*` rewrite,
so it needs no public URL.

## 4. Environment variables

### backend

```
DATABASE_URL          = ${{Postgres.DATABASE_URL}}
CELERY_BROKER_URL     = ${{Redis.REDIS_URL}}/0
CELERY_RESULT_BACKEND = ${{Redis.REDIS_URL}}/1
STORAGE_BACKEND       = s3
S3_ENDPOINT_URL       = https://<account-id>.r2.cloudflarestorage.com
S3_BUCKET             = docpipe
S3_ACCESS_KEY_ID      = <R2 access key id>
S3_SECRET_ACCESS_KEY  = <R2 secret access key>
S3_REGION             = auto
PORT                  = 8000
```

`PORT` is set explicitly so the frontend can name a fixed port in `API_URL`.
`S3_REGION=auto` is required: R2 has no regions, but botocore refuses to sign a
request without one.

The backend does **not** get `ANTHROPIC_API_KEY`. It never calls the LLM — only
the worker does, and keeping the key off the internet-facing service is free.

### worker

Same `DATABASE_URL`, `CELERY_*`, and `S3_*` values as the backend, plus:

```
ANTHROPIC_API_KEY     = <your key>
LLM_PROVIDER          = anthropic
LLM_MODEL             = claude-haiku-4-5
```

No `PORT` — the worker serves no HTTP. That is exactly why Railway suits this
project: a service with no port is ordinary here, where Render would bill it as
a paid-only Background Worker.

### frontend

```
API_URL = http://backend.railway.internal:8000
```

Equivalently `http://${{backend.RAILWAY_PRIVATE_DOMAIN}}:8000`. The browser only
ever talks to the Next server; `next.config.ts` proxies `/api/*` onward, so
there is no CORS configuration anywhere and the backend stays private.

## 5. Migrations

`backend/railway.json` runs `alembic upgrade head` as `preDeployCommand`, so
migrations apply once before the new version starts, and the worker never races
them. This mirrors the compose comment: the API owns schema migration.

## 6. Verify

1. `GET https://<frontend-domain>/` loads the upload form.
2. Upload two or three PDFs from `data/test/`.
3. The progress view climbs and the batch reaches `completed`.
4. The R2 bucket shows one object per document under `uploads/`.
5. Worker logs show `document <id> done in <n> ms`.

## Gotchas

**Bind `0.0.0.0`, not `::`.** Railway's edge proxy expects `0.0.0.0` and the
injected `PORT`. `--host ::` is *not* a dual-stack shortcut: asyncio sets
`IPV6_V6ONLY` on the listening socket regardless of `net.ipv6.bindv6only`, so a
`::` bind refuses IPv4 outright — verified in this image, which answered on
`[::1]` and refused `127.0.0.1`.

**The exception is a legacy environment.** Railway environments created before
2025-10-16 have IPv6-only private networking. If the frontend gets connection
errors reaching `backend.railway.internal`, change the backend's start command
to `--host ::`. Note that this is genuinely either/or with one uvicorn bind — a
`::` backend cannot also serve a public domain over IPv4. Private-only, which is
how this deploy is set up, is fine.

**Redis database indices.** `${{Redis.REDIS_URL}}/0` and `/1` keep the broker
and the result backend separate, as compose does. If Railway's `REDIS_URL`
already carries a database index or a trailing slash, drop the suffix.

**Cost.** Railway is $5/mo (Hobby) plus metered usage at $20/vCPU/mo and
$10/GB RAM/mo. There is no scale-to-zero — idle services bill for resident
memory. Five services here sit around 1.5–2 GB resident, dominated by the
Celery worker's four prefork children, so expect roughly **$20–30/mo** running
continuously. Stopped services cost nothing, so stopping the stack between
demos drops it near the $5 floor. Lowering `--concurrency` in
`railway.worker.json` is the other lever, at the cost of the parallelism the
project exists to demonstrate.
