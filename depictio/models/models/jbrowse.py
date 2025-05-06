from pydantic import BaseModel
from typing import List, Any, Dict


class Block(BaseModel):
    class Config:
        extra = "forbid"  # Reject unexpected fields

    widthPx: float
    assemblyName: str
    refName: str
    start: float
    end: float
    reversed: bool
    offsetPx: int
    parentRegion: Dict[str, Any]
    regionNumber: int
    isLeftEndOfDisplayedRegion: bool
    isRightEndOfDisplayedRegion: bool
    key: str


class Track(BaseModel):
    class Config:
        extra = "forbid"  # Reject unexpected fields

    viewId: str
    tracks: List[str]


class LogData(BaseModel):
    class Config:
        extra = "forbid"  # Reject unexpected fields

    assemblyNames: List[str]
    coarseDynamicBlocks: List[List[Block]]
    selectedTracks: List[Track]
