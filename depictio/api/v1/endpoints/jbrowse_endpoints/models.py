from pydantic import BaseModel
from typing import List, Any, Dict

class Block(BaseModel):
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
    viewId: str
    tracks: List[str]

class LogData(BaseModel):
    assemblyNames: List[str]
    coarseDynamicBlocks: List[List[Block]]
    selectedTracks: List[Track]
