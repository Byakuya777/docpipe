from celery import Celery

from app.config import settings

celery_app = Celery(
    "docpipe",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Recycle a child once its RSS passes this (KiB). Python does not hand
    # freed memory back to the OS eagerly, so a long-lived prefork child
    # creeps upward across documents; this turns that creep into a tidy
    # restart between tasks instead of an OOM kill mid-document.
    worker_max_memory_per_child=400_000,  # ~400 MB
    # Ack only after the task finishes. By default Celery acks on delivery, so
    # a child killed mid-document loses the message outright and the document
    # is stranded at 'processing' forever (§15) — which is exactly what an OOM
    # kill produced in M4 testing. Redelivery is safe here because the task
    # checks status before reprocessing.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # acks_late alone is not enough on Redis. An un-acked message sits in
    # Redis's `unacked` set and is only redelivered after visibility_timeout,
    # which defaults to 3600s — so a killed worker stranded a document for an
    # hour. This must stay comfortably ABOVE the longest task runtime (and the
    # longest retry countdown, retry_backoff_max), or a still-running task gets
    # redelivered and processed twice.
    broker_transport_options={"visibility_timeout": 300},
)
