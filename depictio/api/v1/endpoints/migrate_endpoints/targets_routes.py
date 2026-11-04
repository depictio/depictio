"""Source side, admin only: the registry of instances this one may push to. (#1303)."""

from fastapi import APIRouter

targets_router = APIRouter()
