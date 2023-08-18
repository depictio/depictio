import datetime
import logging
import os
import subprocess
from fastapi import Body, FastAPI
from fastapi.responses import FileResponse
import pika
import json
import uvicorn
from config import load_config
import os, sys
import yaml


config = load_config()

app = FastAPI()


def load_from_json(filename: str):
    """Load the data from the JSON file."""
    try:
        with open(filename, "r") as file:
            data = json.load(file)
        return data
    except (FileNotFoundError, json.JSONDecodeError):
        # If the file does not exist or there's an error in reading it,
        # return an empty dictionary or other default value
        return {}


def consume_last_message_from_rabbitmq(json_backup_filename=str, queue=str):
    connection = pika.BlockingConnection(pika.ConnectionParameters("localhost"))
    channel = connection.channel()

    # Fetch the message without auto acknowledgment
    method_frame, header_frame, body = channel.basic_get(queue=queue, auto_ack=False)

    if method_frame:
        # Extract the timestamp from the header frame
        if header_frame.timestamp:
            timestamp = header_frame.timestamp
            human_readable_timestamp = datetime.datetime.fromtimestamp(
                timestamp / 1000.0
            ).strftime("%Y-%m-%d %H:%M:%S")

        else:
            timestamp = None
        # Convert timestamp to human-readable format if necessary

        # # Acknowledge the message after processing
        # channel.basic_ack(delivery_tag=method_frame.delivery_tag)
        connection.close()
        data = json.loads(body.decode("utf-8"))
        if data == {} and os.path.exists(json_backup_filename):
            print("RabbitMQ queue NOT empty but message is")
            print("Loading from JSON file...")
            data_json = load_from_json(filename=json_backup_filename)
            file_timestamp = os.path.getmtime(json_backup_filename)
            file_timestamp = datetime.datetime.fromtimestamp(file_timestamp).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            return data_json, file_timestamp
        else:
            print("RabbitMQ queue NOT empty and message is NOT empty")
            return data, human_readable_timestamp

    else:
        if os.path.exists(json_backup_filename):
            connection.close()
            print("No message available, RabbitMQ queue is empty")
            print("Loading from JSON file...")
            data_json = load_from_json(filename=json_backup_filename)
            file_timestamp = os.path.getmtime(json_backup_filename)
            file_timestamp = datetime.datetime.fromtimestamp(file_timestamp).strftime(
                "%Y-%m-%d %H:%M:%S"
            )

            return data_json, file_timestamp
        else:
            current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            return {"workflows": []}, current_time


@app.get("/get-progress")
async def get_progress():
    data, timestamp = consume_last_message_from_rabbitmq(
        json_backup_filename=config["panoptes"]["json_status_backup"],
        queue=config["panoptes"]["rabbitmq"]["queue"],
    )

    print(data, timestamp)
    if data == {}:
        data = {"workflows": []}
    return data, timestamp
