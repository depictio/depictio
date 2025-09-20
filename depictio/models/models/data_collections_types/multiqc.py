from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class DCMultiQC(BaseModel):
    # Auto-populated by MultiQC module using parse_logs()
    samples: List[str] = []
    modules: List[str] = []
    plots: Dict[str, Any] = {}

    # Processing and storage metadata (populated during CLI processing)
    s3_location: Optional[str] = None
    processed_files: Optional[int] = None
    file_size_bytes: Optional[int] = None

    class Config:
        extra = "forbid"  # Reject unexpected fields
