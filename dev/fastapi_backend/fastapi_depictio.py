import os
import re
from fastapi import FastAPI, HTTPException, Depends
from pydantic import ValidationError
import yaml

from pydantic_models import Config

app = FastAPI()

# Load and validate the YAML configuration
try:
    with open("config.yaml", "r") as stream:
        data = yaml.safe_load(stream)
        print(data)
        validated_config = Config(**data)
        print(validated_config)
        print(list(validated_config.workflows.keys()))
except yaml.YAMLError:
    raise Exception("Failed to load YAML configuration.")
except ValidationError as e:
    raise Exception(f"Invalid config structure: {e}")


@app.get("/workflows")
async def get_workflows():
    print(validated_config.workflows)
    return {"workflows": list(validated_config.workflows.keys())}


@app.get("/locations/{workflow_name}")
async def get_file_locations(workflow_name: str):
    if workflow_name not in validated_config.workflows:
        raise HTTPException(
            status_code=404, detail=f"Workflow {workflow_name} not found"
        )

    workflow_config = validated_config.workflows[workflow_name]
    locations = {}

    for file_type, file_config in workflow_config.files.items():
        regex_pattern = file_config.regex

        # Search for files matching the regex pattern within the specified parent directory
        matched_files = []
        for root, dirs, files in os.walk(workflow_config.location):
            for file in files:
                if re.match(regex_pattern, file):
                    matched_files.append(os.path.join(root, file))

        # Augment the file list with the metadata
        locations[file_type] = {
            "matched_files": matched_files,
            "metadata": {
                "regex": file_config.regex,
                "format": file_config.format,
                "pandas_kwargs": file_config.pandas_kwargs,
                "keep_columns": file_config.keep_columns,
            },
        }

    return {"workflow": workflow_name, "files": locations}


# class NewFile(BaseModel):
#     workflow_name: str
#     file_type: str
#     content: str  # Assuming the file content will be sent as a string.

# @app.post("/add-file/")
# async def add_file(new_file: NewFile):
#     # ... (keep the logic, but use validated_config instead of config)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="localhost", port=8058)
