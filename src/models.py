from pydantic import BaseModel
from typing import List, Optional


class MultiQCFile(BaseModel):
    file_path: str
    wf_name: str
    run_name: str
    sample_name: Optional[str]
    sample_list: List
    metadata: dict
    date_creation: Optional[str]
    date_last_modification: Optional[str]
    created_by: Optional[str]
    # updated_by: Optional[str]
    # is_active: bool = True
