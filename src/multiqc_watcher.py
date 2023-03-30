import os
import json
import threading
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import requests
from datetime import datetime
import config, models


class MultiQCFileHandler(FileSystemEventHandler):
    def __init__(self):
        pass

    def parse_multiqc_file(self, file_path):
        # Parse the MultiQC JSON file and extract the relevant metadata
        with open(file_path) as f:
            data = json.load(f)
        metadata = dict()
        wf_name = file_path.split("/")[-3]
        run_name = file_path.split("/")[-2]
        sample_list = list(sorted((data.get("report_general_stats_data", {})[0].keys())))
        ctime = os.path.getctime(file_path)
        mtime = os.path.getmtime(file_path)
        multiqc_file = models.MultiQCFile(
            file_path=file_path,
            run_name=run_name,
            wf_name=wf_name,
            sample_list=sample_list,
            metadata=metadata,
            # date_creation=str(datetime.fromtimestamp(ctime)),
            # date_last_modification=str(datetime.fromtimestamp(mtime)),
            created_by=None,
            # updated_by=None,
            # is_active=True,
        )
        return multiqc_file


def observe_multiqc_files(config):
    # Set up a watchdog observer to monitor the specified directory for changes
    event_handler = MultiQCFileHandler()
    observer = Observer()
    observer.schedule(event_handler, config.multiqc_directory, recursive=True)
    observer.start()

    # Set up a scheduled task to periodically update the database with new MultiQC files
    def task():
        while True:
            for workflow in os.listdir(config.multiqc_directory):
                workflow_path = os.path.join(config.multiqc_directory, workflow)
                if os.path.isdir(workflow_path):
                    for run in os.listdir(workflow_path):
                        run_path = os.path.join(workflow_path, run)
                        if os.path.isdir(run_path):
                            for file_name in os.listdir(run_path):
                                file_path = os.path.join(run_path, file_name)
                                if file_name.endswith(".json"):
                                    print("Processing file: ", file_path)
                                    multiqc_file = event_handler.parse_multiqc_file(file_path)
                                    from pprint import pprint

                                    pprint(multiqc_file)
                                    try:
                                        print("Success for file : {f}".format(f=file_path))
                                        response = requests.post(
                                            "{api_host}:{api_port}/multiqc_files/".format(
                                                api_host=config.api_host, api_port=config.api_port
                                            ),
                                            json=multiqc_file.dict(),
                                        )
                                        response.raise_for_status()
                                        print(f"Response status code: {response.status_code}")

                                    except Exception as e:
                                        print(f"Error uploading MultiQC file to server: {str(e)}")
            time.sleep((5))

    thread = threading.Thread(target=task)
    thread.start()


if __name__ == "__main__":
    settings = config.Settings.from_yaml("config.yaml")
    print(settings)
    observe_multiqc_files(settings)
