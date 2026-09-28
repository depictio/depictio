"""Agent-team profiles: the roles a team is made of and the topics they know about.

A profile is a YAML file under ``depictio/agents/profiles/{roles,topics}/``.
A role (analyst, skeptic, annotator, questioner, reporter) says what an agent
does, which tools it may call and with which scopes; a topic (sequencing QC,
differential expression, ...) says what to look for and when it applies. A
team member is one role bound to one topic, named ``<role>/<topic>@<version>``.

Profiles are validated by :class:`AgentProfile` when loaded and cached per
directory; :func:`reload_profiles` drops the cache.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from depictio.models.models.users import TokenScope

PROFILES_DIR = Path(__file__).resolve().parents[3] / "agents" / "profiles"

ROLE_IDS: tuple[str, ...] = ("analyst", "skeptic", "annotator", "questioner", "reporter")
FALLBACK_TOPIC = "general"


class ProfileError(ValueError):
    """A profile file that does not load or does not validate."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AppliesTo(_Strict):
    """When a topic applies. Every entry is a case-insensitive glob (``*`` wildcards)."""

    template_ids: list[str] = Field(
        default_factory=list, description="Project template ids, e.g. 'nf-core/ampliseq*'."
    )
    catalog_modules: list[str] = Field(
        default_factory=list,
        description="Catalog tool ids or 'tool/output' refs used by the dashboard's components.",
    )
    columns: list[str] = Field(
        default_factory=list, description="Column names of the dashboard's data collections."
    )
    component_types: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(
        default_factory=list, description="Words or phrases of the question."
    )

    def is_empty(self) -> bool:
        return not (
            self.template_ids
            or self.catalog_modules
            or self.columns
            or self.component_types
            or self.keywords
        )

    def summary(self) -> str:
        parts = []
        for label, values in (
            ("templates", self.template_ids),
            ("catalog", self.catalog_modules),
            ("components", self.component_types),
            ("columns", self.columns),
            ("keywords", self.keywords),
        ):
            if values:
                shown = ", ".join(values[:4]) + (", ..." if len(values) > 4 else "")
                parts.append(f"{label}: {shown}")
        return "; ".join(parts) or "fallback when no other topic applies"


class ProfileBudget(_Strict):
    """Per-agent limits, inside the run's shared pool."""

    max_tool_calls: int = Field(default=10, ge=0, le=100)
    max_tokens: int = Field(default=60_000, ge=1_000)


class AgentProfile(_Strict):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,40}$")
    kind: Literal["role", "topic"]
    name: str = Field(min_length=1, max_length=80)
    version: int = Field(ge=1)
    description: str = Field(min_length=1, max_length=400)
    applies_to: AppliesTo = Field(default_factory=AppliesTo)
    context_md: str = Field(min_length=1, max_length=8_000)
    checks: list[str] = Field(default_factory=list)
    tools: list[str] = Field(
        default_factory=list,
        description="Tools the agent may call itself (topics may add read tools).",
    )
    scopes: list[TokenScope] = Field(default_factory=list)
    budget: ProfileBudget = Field(default_factory=ProfileBudget)

    @field_validator("tools")
    @classmethod
    def _unique_tools(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))

    def summary(self) -> dict[str, object]:
        """The public listing entry of ``GET /ai/agent-profiles``."""
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "applies_to_summary": self.applies_to.summary() if self.kind == "topic" else "",
        }


class ProfileSet(BaseModel):
    roles: dict[str, AgentProfile]
    topics: dict[str, AgentProfile]

    def role(self, role_id: str) -> AgentProfile:
        try:
            return self.roles[role_id]
        except KeyError:
            raise ProfileError(f"Unknown role profile: {role_id}") from None

    def topic(self, topic_id: str) -> AgentProfile:
        try:
            return self.topics[topic_id]
        except KeyError:
            raise ProfileError(f"Unknown topic profile: {topic_id}") from None

    def all(self) -> list[AgentProfile]:
        return [*self.roles.values(), *self.topics.values()]


def agent_id(role: AgentProfile, topic: AgentProfile) -> str:
    """``<role>/<topic>@<role version>``: the name an agent writes under."""
    return f"{role.id}/{topic.id}@{role.version}"


def parse_agent_id(value: str) -> tuple[str, str]:
    """``(role, topic)`` of ``role/topic`` or ``role/topic@version`` (version ignored)."""
    head = value.split("@", 1)[0].strip()
    role, sep, topic = head.partition("/")
    if not sep or not role or not topic:
        raise ProfileError(f"Agent id must look like 'role/topic@version': {value!r}")
    return role, topic


def _load_file(path: Path, kind: str) -> AgentProfile:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ProfileError(f"{path.name}: cannot read profile: {exc}") from exc
    if not isinstance(raw, dict):
        raise ProfileError(f"{path.name}: a profile is a mapping")
    try:
        profile = AgentProfile.model_validate(raw)
    except ValidationError as exc:
        raise ProfileError(f"{path.name}: {exc}") from exc
    if profile.kind != kind:
        raise ProfileError(f"{path.name}: kind {profile.kind!r} in the {kind}s directory")
    if profile.id != path.stem:
        raise ProfileError(f"{path.name}: id {profile.id!r} does not match the file name")
    return profile


def _load_dir(root: Path) -> ProfileSet:
    loaded: dict[str, dict[str, AgentProfile]] = {"role": {}, "topic": {}}
    for kind in ("role", "topic"):
        folder = root / f"{kind}s"
        for path in sorted(folder.glob("*.yaml")):
            profile = _load_file(path, kind)
            loaded[kind][profile.id] = profile
    missing = [r for r in ROLE_IDS if r not in loaded["role"]]
    if missing:
        raise ProfileError(f"Missing role profiles: {', '.join(missing)}")
    if FALLBACK_TOPIC not in loaded["topic"]:
        raise ProfileError(f"Missing the fallback topic profile '{FALLBACK_TOPIC}'")
    return ProfileSet(roles=loaded["role"], topics=loaded["topic"])


_cache: dict[Path, ProfileSet] = {}
_cache_lock = threading.Lock()


def load_profiles(root: Path | None = None) -> ProfileSet:
    """Every profile under ``root`` (default: the packaged profiles), cached."""
    root = (root or PROFILES_DIR).resolve()
    with _cache_lock:
        cached = _cache.get(root)
        if cached is None:
            cached = _cache[root] = _load_dir(root)
        return cached


def reload_profiles() -> None:
    with _cache_lock:
        _cache.clear()
