from datetime import datetime
from fastapi import HTTPException, Depends, APIRouter
from depictio.api.v1.endpoints.jbrowse_endpoints.models import LogData

jbrowse_endpoints_router = APIRouter()


def construct_jbrowse_url(base_url, config_url, block, tracks):
    assembly_name = block.assemblyName
    ref_name = block.refName
    start = int(block.start)
    end = int(block.end)
    track_list = ','.join(tracks)

    url = (
        f"{base_url}?config={config_url}&assembly={assembly_name}&"
        f"loc={ref_name}:{start}..{end}&tracks={track_list}"
    )
    return url


# TODO: fix in config
@jbrowse_endpoints_router.post("/log")
async def log_message(log_data: LogData):
    print(datetime.now(), log_data)  # Or store it in a database/file

    # Example values for base_url and config_url
    base_url = "http://localhost:3000"
    config_url = "http://localhost:9010/jbrowse2_bak/config.json"

    if log_data.coarseDynamicBlocks and log_data.selectedTracks:
        # Extract the first block and tracks
        block = log_data.coarseDynamicBlocks[0][0]  # Assuming the first block of the first array
        tracks = [t for track in log_data.selectedTracks for t in track.tracks]  # Flatten track list

        jbrowse_url = construct_jbrowse_url(base_url, config_url, block, tracks)
        print("JBrowse URL:", jbrowse_url)

    return {"jbrowse_url": jbrowse_url}
