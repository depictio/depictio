from fastapi import FastAPI
from celery import Celery
import os

app = FastAPI()

# Define Celery app
celery_app = Celery("tasks", broker="pyamqp://guest@localhost//")


# Define Celery task to launch watcher
@celery_app.task
def launch_watcher():
    os.system("python watcher.py")


# Define FastAPI endpoint to launch watcher task
@app.post("/watcher")
async def watcher():
    task = launch_watcher.delay()
    return {"status": "success", "task_id": task.id}
