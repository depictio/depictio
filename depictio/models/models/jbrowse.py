from typing import Any

from pydantic import BaseModel


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
    parentRegion: dict[str, Any]
    regionNumber: int
    isLeftEndOfDisplayedRegion: bool
    isRightEndOfDisplayedRegion: bool
    key: str


class Track(BaseModel):
    class Config:
        extra = "forbid"  # Reject unexpected fields

    viewId: str
    tracks: list[str]


class LogData(BaseModel):
    class Config:
        extra = "forbid"  # Reject unexpected fields

    assemblyNames: list[str]
    coarseDynamicBlocks: list[list[Block]]
    selectedTracks: list[Track]
