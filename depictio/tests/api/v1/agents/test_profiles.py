"""Agent-team profiles: the packaged YAML validates and references real tools and catalog ids."""

from pathlib import Path

import pytest

from depictio.api.v1.agents import registry
from depictio.api.v1.agents.profiles import (
    FALLBACK_TOPIC,
    PROFILES_DIR,
    ROLE_IDS,
    ProfileError,
    agent_id,
    load_profiles,
    parse_agent_id,
)

CATALOG_DIR = Path(__file__).resolve().parents[4] / "catalog"


def test_packaged_profiles_load():
    profiles = load_profiles()
    assert set(ROLE_IDS) <= set(profiles.roles)
    assert {
        FALLBACK_TOPIC,
        "qc_multiqc",
        "differential_expression",
        "microbiome",
        "variants",
    } <= set(profiles.topics)
    assert profiles.topic(FALLBACK_TOPIC).applies_to.is_empty()
    assert load_profiles() is profiles  # cached


def test_role_tools_exist_and_fit_scopes():
    registry.ensure_tools_loaded()
    for profile in load_profiles().all():
        for name in profile.tools:
            spec = registry.REGISTRY.get(name)
            assert spec is not None, f"{profile.id}: unknown tool {name}"
            if profile.kind == "role":
                assert spec.scope in profile.scopes, f"{profile.id}: {name} needs {spec.scope}"


def test_read_only_roles():
    profiles = load_profiles()
    assert profiles.role("analyst").scopes == ["read"]
    assert profiles.role("skeptic").scopes == ["read"]
    assert set(profiles.role("annotator").scopes) == {"read", "annotate"}
    assert set(profiles.role("questioner").scopes) == {"read", "annotate"}
    assert set(profiles.role("reporter").scopes) == {"read", "report"}


def test_topic_catalog_modules_exist():
    for topic in load_profiles().topics.values():
        for ref in topic.applies_to.catalog_modules:
            tool = ref.split("/", 1)[0]
            assert (CATALOG_DIR / tool).is_dir(), f"{topic.id}: no catalog module {tool}"


def test_agent_ids():
    profiles = load_profiles()
    aid = agent_id(profiles.role("analyst"), profiles.topic("microbiome"))
    assert aid == "analyst/microbiome@1"
    assert parse_agent_id(aid) == ("analyst", "microbiome")
    assert parse_agent_id("skeptic/general") == ("skeptic", "general")
    with pytest.raises(ProfileError):
        parse_agent_id("analyst")


def _copy_profiles(tmp_path: Path) -> Path:
    for kind in ("roles", "topics"):
        (tmp_path / kind).mkdir()
        for path in (PROFILES_DIR / kind).glob("*.yaml"):
            (tmp_path / kind / path.name).write_text(path.read_text())
    return tmp_path


def test_invalid_profile_is_refused(tmp_path):
    root = _copy_profiles(tmp_path)
    (root / "topics" / "broken.yaml").write_text(
        "id: broken\nkind: topic\nname: B\nversion: 0\ndescription: d\ncontext_md: c\n"
    )
    with pytest.raises(ProfileError, match="broken.yaml"):
        load_profiles(root)


def test_id_must_match_file_and_roles_are_required(tmp_path):
    root = _copy_profiles(tmp_path)
    (root / "topics" / "other.yaml").write_text(
        "id: renamed\nkind: topic\nname: B\nversion: 1\ndescription: d\ncontext_md: c\n"
    )
    with pytest.raises(ProfileError, match="does not match"):
        load_profiles(root)
    (root / "topics" / "other.yaml").unlink()
    (root / "roles" / "skeptic.yaml").unlink()
    with pytest.raises(ProfileError, match="skeptic"):
        load_profiles(root)
