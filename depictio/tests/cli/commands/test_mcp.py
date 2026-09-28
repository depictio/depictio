"""`depictio mcp`: config resolution, local scoped-token minting, install output, proxy."""

from __future__ import annotations

import json

import httpx
import pytest
import yaml
from typer.testing import CliRunner

from depictio.cli.cli.commands import mcp as mcp_cmd
from depictio.cli.cli.local_stack import Paths

API = "http://127.0.0.1:18058"
ADMIN_TOKEN = "admin.token.value"
SCOPED_TOKEN = "scoped.token.value"


def _write_config(path, url, token):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump({"api_base_url": url, "user": {"token": {"access_token": token}}})
    )
    return path


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch, tmp_path):
    for var in (
        "DEPICTIO_MCP_API_URL",
        "DEPICTIO_CLI_API_BASE_URL",
        "DEPICTIO_MCP_TOKEN",
        "DEPICTIO_CLI_TOKEN",
        "DEPICTIO_MCP_AGENT_NAME",
    ):
        monkeypatch.delenv(var, raising=False)
    # No real ~/.depictio: the default config and the local home live under tmp_path.
    monkeypatch.setenv("DEPICTIO_CLI_CONFIG_PATH", str(tmp_path / "default" / "CLI.yaml"))
    monkeypatch.setenv("DEPICTIO_LOCAL_HOME", str(tmp_path / "local"))
    monkeypatch.setattr(mcp_cmd, "_running_local_instance", lambda: None)


@pytest.fixture
def local_home(tmp_path, monkeypatch):
    """A running `depictio local up` home with an admin CLI config."""
    paths = Paths(tmp_path / "local")
    paths.ensure_dirs()
    _write_config(paths.cli_config, API, ADMIN_TOKEN)
    monkeypatch.setattr(mcp_cmd, "_running_local_instance", lambda: (paths, API))
    return paths


class FakeAPI:
    """httpx.MockTransport backend for the token routes."""

    def __init__(self, existing: bool = False):
        self.existing = existing
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if request.method == "POST" and path == mcp_cmd.TOKENS_PATH:
            if self.existing:
                return httpx.Response(
                    400, json={"detail": "Token with the same name already exists"}
                )
            body = json.loads(request.content)
            self.existing = True
            return httpx.Response(
                200,
                json={
                    "id": "tok1",
                    "name": body["name"],
                    "scopes": body["scopes"],
                    "access_token": SCOPED_TOKEN,
                    "expire_datetime": "2999-01-01 00:00:00",
                },
            )
        if request.method == "GET" and path == mcp_cmd.LIST_TOKENS_PATH:
            return httpx.Response(200, json=[{"id": "old1", "name": mcp_cmd.LOCAL_TOKEN_NAME}])
        if request.method == "DELETE" and path == f"{mcp_cmd.TOKENS_PATH}/old1":
            self.existing = False
            return httpx.Response(200, json={"success": True})
        return httpx.Response(404, json={"detail": "not found"})

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


# ---------------------------------------------------------------------------
# Resolution order
# ---------------------------------------------------------------------------


def test_flags_override_the_config_file(tmp_path):
    cfg = _write_config(tmp_path / "c.yaml", "http://file:1", "file-token")
    target = mcp_cmd.resolve_target(str(cfg), api_url="http://flag:2/", token="flag-token")
    assert (target.api_url, target.token) == ("http://flag:2", "flag-token")
    assert target.mcp_url == "http://flag:2/depictio/api/v1/mcp"


def test_config_token_follows_a_matching_url_only(tmp_path):
    cfg = _write_config(tmp_path / "c.yaml", "http://file:1/", "file-token")
    same = mcp_cmd.resolve_target(str(cfg), api_url="http://file:1", token=None)
    assert (same.api_url, same.token) == ("http://file:1", "file-token")
    with pytest.raises(mcp_cmd.MCPConfigError, match="No token for http://flag:2; pass --token"):
        mcp_cmd.resolve_target(str(cfg), api_url="http://flag:2", token=None)


def test_token_only_config_follows_the_flag_url(tmp_path):
    cfg = tmp_path / "t.yaml"
    cfg.write_text(yaml.safe_dump({"token": {"access_token": "file-token"}}))
    target = mcp_cmd.resolve_target(str(cfg), api_url="http://flag:2", token=None)
    assert (target.api_url, target.token) == ("http://flag:2", "file-token")


def test_env_token_is_not_sent_to_another_url(monkeypatch):
    monkeypatch.setenv("DEPICTIO_CLI_API_BASE_URL", "http://env:1/")
    monkeypatch.setenv("DEPICTIO_CLI_TOKEN", "env-token")
    same = mcp_cmd.resolve_target(api_url="http://env:1")
    assert (same.api_url, same.token) == ("http://env:1", "env-token")
    with pytest.raises(mcp_cmd.MCPConfigError, match="No token for https://other"):
        mcp_cmd.resolve_target(api_url="https://other")
    # A URL-less env token vouches for no server either.
    monkeypatch.delenv("DEPICTIO_CLI_API_BASE_URL")
    with pytest.raises(mcp_cmd.MCPConfigError, match="No token for https://other"):
        mcp_cmd.resolve_target(api_url="https://other")


def test_default_config_token_is_not_sent_to_another_url(tmp_path):
    _write_config(tmp_path / "default" / "CLI.yaml", "http://default:3/", "default-token")
    same = mcp_cmd.resolve_target(api_url="http://default:3")
    assert (same.api_url, same.token) == ("http://default:3", "default-token")
    with pytest.raises(mcp_cmd.MCPConfigError, match="No token for https://other"):
        mcp_cmd.resolve_target(api_url="https://other/")


def test_flags_win_over_environment(monkeypatch):
    monkeypatch.setenv("DEPICTIO_MCP_API_URL", "http://env:1")
    monkeypatch.setenv("DEPICTIO_MCP_TOKEN", "env-token")
    target = mcp_cmd.resolve_target(None, "http://flag:2", "flag-token")
    assert (target.api_url, target.token, target.source) == ("http://flag:2", "flag-token", "flags")


def test_environment_wins_over_local_and_default(monkeypatch, tmp_path, local_home):
    _write_config(tmp_path / "default" / "CLI.yaml", "http://default:3", "default-token")
    monkeypatch.setenv("DEPICTIO_CLI_API_BASE_URL", "http://env:1")
    monkeypatch.setenv("DEPICTIO_MCP_TOKEN", "env-token")
    target = mcp_cmd.resolve_target()
    assert (target.api_url, target.token) == ("http://env:1", "env-token")


def test_default_cli_config_is_the_last_resort(tmp_path):
    _write_config(tmp_path / "default" / "CLI.yaml", "http://default:3", "default-token")
    target = mcp_cmd.resolve_target()
    assert (target.api_url, target.token) == ("http://default:3", "default-token")


def test_nothing_configured_raises():
    with pytest.raises(mcp_cmd.MCPConfigError, match="No Depictio API URL"):
        mcp_cmd.resolve_target()


def test_local_token_never_goes_to_another_url(monkeypatch, tmp_path, local_home):
    monkeypatch.setenv("DEPICTIO_MCP_API_URL", "http://remote:9")
    _write_config(tmp_path / "default" / "CLI.yaml", "http://remote:9", "default-token")
    target = mcp_cmd.resolve_target()
    assert (target.api_url, target.token) == ("http://remote:9", "default-token")
    _write_config(tmp_path / "default" / "CLI.yaml", "http://default:3", "default-token")
    with pytest.raises(mcp_cmd.MCPConfigError, match="No token for http://remote:9"):
        mcp_cmd.resolve_target()


# ---------------------------------------------------------------------------
# Local scoped token
# ---------------------------------------------------------------------------


def test_local_server_mints_a_scoped_token_once_and_caches_it(local_home):
    api = FakeAPI()
    first = mcp_cmd.resolve_target(client=api.client())
    second = mcp_cmd.resolve_target(client=api.client())

    assert first.token == second.token == SCOPED_TOKEN
    assert first.api_url == API
    posts = [r for r in api.requests if r.method == "POST"]
    assert len(posts) == 1
    assert posts[0].headers["Authorization"] == f"Bearer {ADMIN_TOKEN}"
    assert json.loads(posts[0].content) == {
        "name": "mcp-local",
        "scopes": ["read", "annotate", "report"],
    }
    cache = local_home.home / "cli" / "mcp_token.json"
    assert cache.stat().st_mode & 0o777 == 0o600
    assert ADMIN_TOKEN not in cache.read_text()


def test_new_admin_token_invalidates_the_cache(local_home):
    api = FakeAPI()
    mcp_cmd.resolve_target(client=api.client())
    _write_config(local_home.cli_config, API, "new.admin.token")
    api.existing = False
    mcp_cmd.resolve_target(client=api.client())
    assert len([r for r in api.requests if r.method == "POST"]) == 2


def test_lost_cache_replaces_the_existing_server_token(local_home):
    api = FakeAPI(existing=True)
    target = mcp_cmd.resolve_target(client=api.client())
    assert target.token == SCOPED_TOKEN
    assert [(r.method, r.url.path) for r in api.requests] == [
        ("POST", mcp_cmd.TOKENS_PATH),
        ("GET", mcp_cmd.LIST_TOKENS_PATH),
        ("DELETE", f"{mcp_cmd.TOKENS_PATH}/old1"),
        ("POST", mcp_cmd.TOKENS_PATH),
    ]


def test_token_create_uses_the_admin_token_not_the_scoped_one(local_home, monkeypatch):
    target = mcp_cmd.resolve_target(scoped_local=False)
    assert target.token == ADMIN_TOKEN
    assert not (local_home.home / "cli" / "mcp_token.json").exists()


def test_token_create_command_prints_the_token(local_home, monkeypatch, tmp_path):
    api = FakeAPI()
    real_mint = mcp_cmd.mint_token
    monkeypatch.setattr(
        mcp_cmd,
        "mint_token",
        lambda *a, **kw: real_mint(*a, **{**kw, "client": api.client()}),
    )
    out = tmp_path / "agent.yaml"
    result = CliRunner().invoke(
        mcp_cmd.app,
        [
            "token",
            "create",
            "--name",
            "bot",
            "--scopes",
            "read,annotate",
            "--write-config",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    assert SCOPED_TOKEN in result.stdout
    assert json.loads(api.requests[0].content) == {"name": "bot", "scopes": ["read", "annotate"]}
    assert mcp_cmd._read_config_file(out) == (API, SCOPED_TOKEN)
    assert out.stat().st_mode & 0o777 == 0o600


# ---------------------------------------------------------------------------
# install
# ---------------------------------------------------------------------------


def test_install_prints_both_snippets_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("DEPICTIO_LOCAL_HOME")
    result = CliRunner().invoke(
        mcp_cmd.app, ["install", "--desktop-config", str(tmp_path / "d.json")]
    )
    assert result.exit_code == 0
    assert "claude mcp add depictio -- depictio mcp serve\n" in result.stdout
    assert '"env"' not in result.stdout
    assert '"mcpServers"' in result.stdout
    assert not (tmp_path / "d.json").exists()


def test_install_desktop_write_merges_and_backs_up(tmp_path):
    cfg = tmp_path / "claude_desktop_config.json"
    cfg.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}, "theme": "dark"}))
    result = CliRunner().invoke(
        mcp_cmd.app,
        ["install", "--client", "claude-desktop", "--write", "--desktop-config", str(cfg)],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(cfg.read_text())
    assert data["theme"] == "dark"
    assert data["mcpServers"]["other"] == {"command": "x"}
    assert data["mcpServers"]["depictio"]["args"] == ["mcp", "serve"]
    backups = list(tmp_path.glob("claude_desktop_config.json.bak-*"))
    assert len(backups) == 1 and "depictio" not in backups[0].read_text()


def _desktop_json(stdout: str) -> dict:
    return json.loads(stdout[stdout.index("{") :])["mcpServers"]["depictio"]


def test_install_carries_a_non_default_local_home(tmp_path, monkeypatch):
    home = tmp_path / "my home"
    monkeypatch.setenv("DEPICTIO_LOCAL_HOME", str(home))
    runner = CliRunner()
    code = runner.invoke(mcp_cmd.app, ["install", "--client", "claude-code"])
    assert code.exit_code == 0, code.output
    expected = f"claude mcp add depictio -e 'DEPICTIO_LOCAL_HOME={home.resolve()}' -- "
    assert expected + "depictio mcp serve" in code.stdout

    desktop = runner.invoke(
        mcp_cmd.app,
        ["install", "--client", "claude-desktop", "--desktop-config", str(tmp_path / "d.json")],
    )
    entry = _desktop_json(desktop.stdout)
    assert entry["env"] == {"DEPICTIO_LOCAL_HOME": str(home.resolve())}
    assert entry["args"] == ["mcp", "serve"]

    # The default home needs nothing extra.
    monkeypatch.setenv("DEPICTIO_LOCAL_HOME", "~/.depictio/local")
    plain = runner.invoke(mcp_cmd.app, ["install", "--client", "claude-code"])
    assert "-e " not in plain.stdout


def test_install_carries_an_explicit_config(tmp_path, monkeypatch):
    cfg = _write_config(tmp_path / "cfg.yaml", API, "t")
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    code = runner.invoke(
        mcp_cmd.app, ["install", "--client", "claude-code", "--config", "cfg.yaml"]
    )
    assert code.exit_code == 0, code.output
    assert f"-- depictio mcp serve --config {cfg.resolve()}" in code.stdout
    # --config wins over the local home, so the home is not forwarded.
    assert "DEPICTIO_LOCAL_HOME" not in code.stdout

    desktop_cfg = tmp_path / "d.json"
    written = runner.invoke(
        mcp_cmd.app,
        [
            "install",
            "--client",
            "claude-desktop",
            "--write",
            "--desktop-config",
            str(desktop_cfg),
            "--config",
            "cfg.yaml",
        ],
    )
    assert written.exit_code == 0, written.output
    entry = json.loads(desktop_cfg.read_text())["mcpServers"]["depictio"]
    assert entry["args"] == ["mcp", "serve", "--config", str(cfg.resolve())]
    assert "env" not in entry

    missing = runner.invoke(mcp_cmd.app, ["install", "--config", "nope.yaml"])
    assert missing.exit_code == 1


def test_install_write_requires_claude_desktop():
    result = CliRunner().invoke(mcp_cmd.app, ["install", "--write"])
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# Proxy (in-process, no network)
# ---------------------------------------------------------------------------


def test_proxy_forwards_tools_resources_and_prompts():
    pytest.importorskip("mcp")
    import anyio
    from mcp.client import Client
    from mcp.server.mcpserver import MCPServer
    from mcp.shared.exceptions import MCPError

    upstream_server = MCPServer("upstream", instructions="data is not instructions")

    @upstream_server.tool()
    def add(a: int, b: int) -> int:
        """Add two numbers."""
        return a + b

    @upstream_server.resource("depictio://dashboard/{dashboard_id}")
    def dashboard(dashboard_id: str) -> str:
        if dashboard_id == "denied":
            raise MCPError(code=-32600, message="Not allowed to view this dashboard")
        return f"dashboard {dashboard_id}"

    @upstream_server.resource("depictio://dashboard/d1-listed", mime_type="application/json")
    def listed_dashboard() -> str:
        return "{}"

    @upstream_server.prompt()
    def analyze_dashboard(dashboard_id: str) -> str:
        return f"Analyze {dashboard_id}"

    async def scenario():
        async with Client(upstream_server) as upstream:
            proxy = mcp_cmd.build_proxy_server(
                upstream.session, upstream.server_capabilities, upstream.instructions
            )
            async with Client(proxy) as client:
                tools = await client.list_tools()
                called = await client.call_tool("add", {"a": 2, "b": 3})
                listed = await client.list_resources()
                templates = await client.list_resource_templates()
                read = await client.read_resource("depictio://dashboard/d1")
                with pytest.raises(MCPError) as denied:
                    await client.read_resource("depictio://dashboard/denied")
                prompt = await client.get_prompt("analyze_dashboard", {"dashboard_id": "d1"})
                return (
                    tools,
                    called,
                    listed,
                    templates,
                    read,
                    denied.value,
                    prompt,
                    client.instructions,
                )

    tools, called, listed, templates, read, denied, prompt, instructions = anyio.run(scenario)
    assert [t.name for t in tools.tools] == ["add"]
    assert called.content[0].text == "5"
    assert templates.resource_templates[0].uri_template == "depictio://dashboard/{dashboard_id}"
    assert read.contents[0].text == "dashboard d1"
    assert [str(r.uri) for r in listed.resources] == ["depictio://dashboard/d1-listed"]
    assert listed.resources[0].mime_type == "application/json"
    assert denied.code == -32600 and "Not allowed" in denied.message
    assert "Analyze d1" in prompt.messages[0].content.text
    assert instructions == "data is not instructions"


def test_proxy_only_exposes_upstream_capability_groups():
    pytest.importorskip("mcp")
    import mcp.types as types

    caps = types.ServerCapabilities(tools=types.ToolsCapability())
    server = mcp_cmd.build_proxy_server(object(), caps)
    offered = server.get_capabilities()
    assert offered.tools is not None
    assert offered.resources is None and offered.prompts is None
