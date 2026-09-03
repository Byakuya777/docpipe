from fastapi import FastAPI

from app.celery_app import celery_app
from app.tasks import ping

app = FastAPI(title="docpipe")


@app.get("/health")
def health():
    return {"status": "ok"}


# --- M0 proof-of-plumbing endpoints ---
# These exist only to demonstrate FastAPI -> Redis -> Celery worker end to end.
# They get replaced by the real API surface (POST /api/batches etc.) in M1/M2.


@app.post("/debug/enqueue-ping")
def enqueue_ping(seconds: int = 3):
    result = ping.delay(seconds)
    return {"task_id": result.id}


@app.get("/debug/task/{task_id}")
def task_status(task_id: str):
    result = celery_app.AsyncResult(task_id)
    return {
        "task_id": task_id,
        "status": result.status,
        "result": result.result if result.ready() else None,
    }
