from celery import shared_task


@shared_task(name="core.celery_ping")
def celery_ping():
    return {
        "status": "ok",
        "task": "core.celery_ping",
    }
