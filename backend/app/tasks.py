import logging
import time

from app.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.ping")
def ping(seconds: int = 3) -> str:
    """Trivial task to prove the FastAPI -> Redis -> Celery worker chain works end to end."""
    logger.info("ping task started: sleeping %s seconds", seconds)
    time.sleep(seconds)
    logger.info("ping task finished")
    return f"slept {seconds}s"
