import os
import uuid
from fastapi import FastAPI
from celery import Celery
from pydantic import BaseModel
import json

app = FastAPI()

# Celery configuration
celery_app = Celery(
    "tasks",
    broker="pyamqp://guest@localhost//",  # RabbitMQ broker URL
    backend="rpc://",
)


class Job(BaseModel):
    job_id: str
    status: str
    result: str


# Load the jobs_history from the JSON file
def load_jobs_history():
    if not os.path.exists("jobs.json"):
        with open("jobs.json", "w") as f:
            json.dump([], f)
    with open("jobs.json", "r") as f:
        return [Job(**job) for job in json.load(f)]


jobs_history = load_jobs_history()


def save_jobs_history():
    with open("jobs.json", "w") as f:
        json.dump([job.dict() for job in jobs_history], f)


@celery_app.task(bind=True)
def process_job(self, job_id: str):
    import time

    time.sleep(3)
    result = f"Job {job_id} completed"
    # Update the job status in the jobs_history list
    for job in jobs_history:
        if job.job_id == job_id:
            job.status = "SUCCESS"
            job.result = result
            break
    # Save the jobs_history to the JSON file
    save_jobs_history()
    return result


@app.post("/create_job/")
def create_job():
    job_id = str(uuid.uuid4())  # Generate a unique job ID
    job = process_job.apply_async(args=[job_id], task_id=job_id)
    jobs_history.append(Job(job_id=job.id, status="PENDING", result=""))
    save_jobs_history()
    return {"job_id": job.id}


@app.get("/job_status/{job_id}")
def job_status(job_id: str):
    job = celery_app.AsyncResult(job_id)
    # Update the job in jobs_history if the status has changed
    for job_record in jobs_history:
        if job_record.job_id == job_id:
            if job_record.status != job.state:
                job_record.status = job.state
                job_record.result = job.result
                save_jobs_history()
            break
    return {"job_id": job_id, "status": job.state, "result": job.result}


@app.get("/jobs_history/")
def get_jobs_history():
    # Update the job statuses before returning
    for job in jobs_history:
        celery_job = celery_app.AsyncResult(job.job_id)
        if job.status != celery_job.state:
            job.status = celery_job.state
            job.result = celery_job.result
    save_jobs_history()  # Save the latest statuses back to the JSON file
    return jobs_history
