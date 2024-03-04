from typing import List
from pydantic import (
    BaseModel,
)
from depictio.api.v1.endpoints.workflow_endpoints.models import Workflow


class RootConfig(BaseModel):
    workflows: List[Workflow]
