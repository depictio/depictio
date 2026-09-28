"""``depictio mcp``: connect MCP clients (Claude Code, Claude Desktop, agents) to Depictio.

The API serves MCP over streamable HTTP at ``/depictio/api/v1/mcp``. Most desktop
clients speak stdio, so ``depictio mcp serve`` is a small stdio server that forwards
every tools/resources/prompts request to that endpoint with the resolved Bearer token.

Where the API URL and token come from, first match wins per field:

1. ``--config`` (a CLI config YAML), then ``--api-url`` / ``--token`` on top of it;
2. environment: ``DEPICTIO_MCP_API_URL`` / ``DEPICTIO_CLI_API_BASE_URL`` and
   ``DEPICTIO_MCP_TOKEN`` / ``DEPICTIO_CLI_TOKEN``;
3. a running ``depictio local up`` server. Its admin token is never handed to the
   agent: a scoped ``mcp-local`` token (read, annotate, report) is minted once with it
   and cached in the local home;
4. the default CLI config (``DEPICTIO_CLI_CONFIG_PATH`` or ``~/.depictio/CLI.yaml``).

``serve`` writes nothing to stdout but the protocol; diagnostics go to stderr.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

import httpx
import typer
import yaml

from depictio.cli.cli_logging import logger

API_PREFIX = "/depictio/api/v1"
MCP_PATH = f"{API_PREFIX}/mcp"
STATUS_PATH = f"{API_PREFIX}/utils/status"
TOKENS_PATH = f"{API_PREFIX}/auth/me/tokens"
LIST_TOKENS_PATH = f"{API_PREFIX}/auth/list_tokens"

LOCAL_TOKEN_NAME = "mcp-local"
LOCAL_TOKEN_SCOPES = ["read", "annotate", "report"]
DEFAULT_CLI_CONFIG = "~/.depictio/CLI.yaml"
SERVER_NAME = "depictio"

app = typer.Typer(
    help="Connect MCP clients (Claude Code, Claude Desktop, agents) to Depictio.",
    no_args_is_help=True,
)
token_app = typer.Typer(help="Scoped API tokens for MCP clients.", no_args_is_help=True)
app.add_typer(token_app, name="token")


class MCPConfigError(RuntimeError):
    """The API URL or token could not be resolved, or the API refused a token call."""


@dataclass(frozen=True)
class MCPTarget:
    api_url: str
    token: str
    source: str

    @property
    def mcp_url(self) -> str:
        return f"{self.api_url}{MCP_PATH}"


# ---------------------------------------------------------------------------
# Config resolution
# ---------------------------------------------------------------------------


def _stderr(msg: str) -> None:
    typer.echo(msg, err=True)


def _read_config_file(path: str | Path) -> tuple[str | None, str | None]:
    """API URL and access token from a CLI config YAML, without validating the rest.

    ``load_depictio_config`` prints progress to stdout and requires the full user
    block; ``serve`` can afford neither, and a token-only snippet is a valid input.
    """
    expanded = Path(path).expanduser()
    if not expanded.is_file():
        raise MCPConfigError(f"Config file not found: {expanded}")
    data = yaml.safe_load(expanded.read_text()) or {}
    url = data.get("api_base_url") or data.get("base_url")
    token = ((data.get("user") or {}).get("token") or {}).get("access_token")
    token = token or (data.get("token") or {}).get("access_token")
    return (url.rstrip("/") if url else None), token


def _env_first(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None


def _running_local_instance() -> tuple[Any, str] | None:
    """The ``depictio local up`` home paths and API URL, when its API process is alive."""
    from depictio.cli.cli.local_stack import Paths, load_state, local_home, running_status

    paths = Paths(local_home())
    state = load_state(paths)
    if not state.get("url") or not paths.cli_config.is_file():
        return None
    if not running_status(paths).get("api"):
        return None
    return paths, state["url"].rstrip("/")


def _local_token_cache(paths: Any) -> Path:
    # Under cli/ so `depictio local wipe` removes it with the admin config.
    return paths.home / "cli" / "mcp_token.json"


def _write_private(path: Path, content: str) -> None:
    """Write a file readable by its owner only, never world-readable even briefly."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(content)
    os.chmod(path, 0o600)


def _expired(expire_datetime: str | None) -> bool:
    if not expire_datetime:
        return False
    try:
        return datetime.fromisoformat(str(expire_datetime)) <= datetime.now()
    except ValueError:
        return False


def _fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()[:16]


def local_scoped_token(paths: Any, api_url: str, client: httpx.Client | None = None) -> str:
    """The cached ``mcp-local`` token for the local server, minted on first use.

    The cache is keyed on a fingerprint of the admin token: a wiped and re-seeded
    instance issues a new admin token, which invalidates a token minted against the
    previous database.
    """
    _admin_url, admin_token = _read_config_file(paths.cli_config)
    if not admin_token:
        raise MCPConfigError(f"No admin token in {paths.cli_config}")
    fingerprint = _fingerprint(admin_token)

    cache = _local_token_cache(paths)
    if cache.is_file():
        try:
            cached = json.loads(cache.read_text())
        except ValueError:
            cached = {}
        if (
            cached.get("admin_fingerprint") == fingerprint
            and cached.get("access_token")
            and not _expired(cached.get("expire_datetime"))
        ):
            return cached["access_token"]

    logger.info(f"Minting the scoped '{LOCAL_TOKEN_NAME}' token on {api_url}")
    minted = mint_token(
        api_url,
        admin_token,
        LOCAL_TOKEN_NAME,
        LOCAL_TOKEN_SCOPES,
        replace_existing=True,
        client=client,
    )
    _write_private(
        cache,
        json.dumps(
            {
                "api_url": api_url,
                "name": LOCAL_TOKEN_NAME,
                "scopes": LOCAL_TOKEN_SCOPES,
                "access_token": minted["access_token"],
                "expire_datetime": minted.get("expire_datetime"),
                "admin_fingerprint": fingerprint,
            },
            indent=2,
        ),
    )
    return minted["access_token"]


def resolve_target(
    config_path: str | None = None,
    api_url: str | None = None,
    token: str | None = None,
    *,
    scoped_local: bool = True,
    client: httpx.Client | None = None,
) -> MCPTarget:
    """Resolve the API URL and token (see the module docstring for the order).

    ``scoped_local=False`` returns the local admin token itself, for ``token create``,
    which needs a token allowed to mint others.
    """
    url = api_url.rstrip("/") if api_url else None
    source = "flags"
    if config_path:
        file_url, file_token = _read_config_file(config_path)
        url, token = url or file_url, token or file_token
        source = str(config_path)
    if url and token:
        return MCPTarget(url, token, source)

    env_url = _env_first("DEPICTIO_MCP_API_URL", "DEPICTIO_CLI_API_BASE_URL")
    env_token = _env_first("DEPICTIO_MCP_TOKEN", "DEPICTIO_CLI_TOKEN")
    url, token = url or (env_url.rstrip("/") if env_url else None), token or env_token
    if url and token:
        return MCPTarget(url, token, "environment")

    local = _running_local_instance()
    # A local token only ever goes to the local server, never to a URL set elsewhere.
    if local is not None and (url is None or url == local[1]):
        paths, local_url = local
        url = url or local_url
        if token is None:
            if scoped_local:
                token = local_scoped_token(paths, local_url, client=client)
            else:
                token = _read_config_file(paths.cli_config)[1]
        if url and token:
            return MCPTarget(url, token, f"local server ({paths.home})")

    default_path = os.environ.get("DEPICTIO_CLI_CONFIG_PATH") or DEFAULT_CLI_CONFIG
    if Path(default_path).expanduser().is_file():
        file_url, file_token = _read_config_file(default_path)
        url, token = url or file_url, token or file_token
        if url and token:
            return MCPTarget(url, token, default_path)

    raise MCPConfigError(
        "No Depictio API URL and token found. Pass --config or --api-url/--token, set "
        "DEPICTIO_MCP_API_URL and DEPICTIO_MCP_TOKEN, start a local server with "
        f"`depictio local up`, or create {DEFAULT_CLI_CONFIG}."
    )


# ---------------------------------------------------------------------------
# API calls
# ---------------------------------------------------------------------------


def _detail(response: httpx.Response) -> str:
    try:
        return str(response.json().get("detail", response.text))
    except ValueError:
        return response.text


def mint_token(
    api_url: str,
    bearer: str,
    name: str,
    scopes: list[str],
    *,
    replace_existing: bool = False,
    client: httpx.Client | None = None,
) -> dict:
    """Create a scoped long-lived token for the bearer's user and return the token document.

    ``replace_existing`` deletes a token of the same name first when the API reports
    one: used for the local token, whose previous value is lost with its cache.
    """
    owns_client = client is None
    client = client or httpx.Client(timeout=15)
    headers = {"Authorization": f"Bearer {bearer}"}
    body = {"name": name, "scopes": scopes}
    try:
        response = client.post(f"{api_url}{TOKENS_PATH}", json=body, headers=headers)
        if (
            response.status_code == 400
            and "already exists" in _detail(response)
            and replace_existing
        ):
            listed = client.get(
                f"{api_url}{LIST_TOKENS_PATH}",
                params={"token_lifetime": "long-lived"},
                headers=headers,
            )
            listed.raise_for_status()
            for doc in listed.json():
                if doc.get("name") == name:
                    token_id = doc.get("id") or doc.get("_id")
                    client.delete(
                        f"{api_url}{TOKENS_PATH}/{token_id}", headers=headers
                    ).raise_for_status()
            response = client.post(f"{api_url}{TOKENS_PATH}", json=body, headers=headers)
        if response.status_code >= 400:
            raise MCPConfigError(
                f"Token creation refused by {api_url} ({response.status_code}): {_detail(response)}"
            )
        return response.json()
    except httpx.HTTPError as exc:
        raise MCPConfigError(f"Token creation failed on {api_url}: {exc}") from exc
    finally:
        if owns_client:
            client.close()


def mcp_enabled(api_url: str, client: httpx.Client | None = None) -> bool | None:
    """``features.mcp`` from the public status route, or None when it cannot be read."""
    owns_client = client is None
    client = client or httpx.Client(timeout=10)
    try:
        response = client.get(f"{api_url}{STATUS_PATH}")
        response.raise_for_status()
        return bool(response.json().get("features", {}).get("mcp", False))
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning(f"Could not read {api_url}{STATUS_PATH}: {exc}")
        return None
    finally:
        if owns_client:
            client.close()


# ---------------------------------------------------------------------------
# stdio proxy
# ---------------------------------------------------------------------------


def _strip_meta(params: Any) -> Any:
    # The downstream `_meta` belongs to that session (progress tokens, protocol
    # envelope keys); the upstream session stamps its own.
    if params is not None and getattr(params, "meta", None) is not None:
        return params.model_copy(update={"meta": None})
    return params


def build_proxy_server(
    upstream: Any,
    capabilities: Any = None,
    instructions: str | None = None,
    version: str = "",
) -> Any:
    """A low-level MCP server that forwards tools, resources and prompts to ``upstream``.

    ``upstream`` is a connected ``ClientSession``: requests go through its
    ``send_request`` unchanged, so pagination cursors, structured tool output and
    ``isError`` results reach the client as the API produced them. Only the
    capability groups the upstream advertises are exposed (all when unknown).
    """
    import mcp.types as types
    from mcp.server.lowlevel import Server

    def forward(request_cls: Any, result_cls: Any):
        async def handler(_ctx: Any, params: Any) -> Any:
            return await upstream.send_request(request_cls(params=_strip_meta(params)), result_cls)

        return handler

    def offers(group: str) -> bool:
        return capabilities is None or getattr(capabilities, group, None) is not None

    handlers: dict[str, Any] = {}
    if offers("tools"):
        handlers["on_list_tools"] = forward(types.ListToolsRequest, types.ListToolsResult)
        handlers["on_call_tool"] = forward(types.CallToolRequest, types.CallToolResult)
    if offers("resources"):
        handlers["on_list_resources"] = forward(
            types.ListResourcesRequest, types.ListResourcesResult
        )
        handlers["on_list_resource_templates"] = forward(
            types.ListResourceTemplatesRequest, types.ListResourceTemplatesResult
        )
        handlers["on_read_resource"] = forward(types.ReadResourceRequest, types.ReadResourceResult)
    if offers("prompts"):
        handlers["on_list_prompts"] = forward(types.ListPromptsRequest, types.ListPromptsResult)
        handlers["on_get_prompt"] = forward(types.GetPromptRequest, types.GetPromptResult)

    return Server(SERVER_NAME, version=version, instructions=instructions, **handlers)


def _cli_version() -> str:
    try:
        from depictio.cli.cli.utils.telemetry import cli_version

        return cli_version()
    except Exception:
        return ""


async def run_proxy(target: MCPTarget, agent_name: str | None, run_id: str) -> None:
    """Connect upstream over streamable HTTP, then serve the proxy on stdio."""
    from mcp.client import Client
    from mcp.client.streamable_http import streamable_http_client
    from mcp.server.stdio import stdio_server
    from mcp.shared._httpx_utils import create_mcp_http_client

    headers = {"Authorization": f"Bearer {target.token}", "X-Depictio-Run-Id": run_id}
    if agent_name:
        headers["X-Depictio-Agent"] = agent_name
    http_client = create_mcp_http_client(headers=headers)
    async with http_client:
        transport = streamable_http_client(target.mcp_url, http_client=http_client)
        # No client-side response cache: a proxy must show the API's current state.
        async with Client(transport, cache=None) as upstream:
            server = build_proxy_server(
                upstream.session,
                upstream.server_capabilities,
                upstream.instructions,
                version=_cli_version(),
            )
            logger.info(f"Proxying MCP stdio to {target.mcp_url} (token from {target.source})")
            async with stdio_server() as (read_stream, write_stream):
                await server.run(read_stream, write_stream, server.create_initialization_options())


def _require_mcp_sdk() -> None:
    try:
        import mcp  # noqa: F401
    except ImportError:
        _stderr(
            "The MCP SDK is not installed. Install the server package (pip install depictio) "
            "or add `mcp` to this environment."
        )
        raise typer.Exit(code=1)


@app.command()
def serve(
    config: Annotated[
        str | None, typer.Option("--config", help="CLI config YAML with the API URL and token")
    ] = None,
    api_url: Annotated[str | None, typer.Option("--api-url", help="Depictio API base URL")] = None,
    token: Annotated[
        str | None, typer.Option("--token", help="Bearer token (prefer a scoped one)")
    ] = None,
    agent_name: Annotated[
        str | None,
        typer.Option(
            "--agent-name",
            envvar="DEPICTIO_MCP_AGENT_NAME",
            help="Agent label recorded with each action (X-Depictio-Agent)",
        ),
    ] = None,
    run_id: Annotated[
        str | None,
        typer.Option(
            "--run-id",
            help="Groups this session's actions server-side (X-Depictio-Run-Id); random by default",
        ),
    ] = None,
):
    """Run a stdio MCP server that forwards to the Depictio API (for Claude Code / Desktop)."""
    _require_mcp_sdk()
    import anyio

    try:
        target = resolve_target(config, api_url, token)
    except MCPConfigError as exc:
        _stderr(f"depictio mcp serve: {exc}")
        raise typer.Exit(code=1)

    if mcp_enabled(target.api_url) is False:
        _stderr(
            f"MCP is disabled on {target.api_url}. Enable it on the server with "
            "DEPICTIO_MCP_ENABLED=true."
        )
        raise typer.Exit(code=1)

    try:
        anyio.run(run_proxy, target, agent_name, run_id or uuid.uuid4().hex)
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        _stderr(f"depictio mcp serve ({target.mcp_url}): {_root_cause(exc)}")
        raise typer.Exit(code=1)


def _root_cause(exc: BaseException) -> BaseException:
    # anyio task groups wrap the transport error; the leaf is the useful message.
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return exc


# ---------------------------------------------------------------------------
# token create
# ---------------------------------------------------------------------------


@token_app.command("create")
def token_create(
    name: Annotated[str, typer.Option("--name", help="Token name, unique per user")],
    scopes: Annotated[
        str,
        typer.Option(
            "--scopes",
            help="Comma-separated scopes: read, annotate, report, edit_dashboard, ingest",
        ),
    ] = ",".join(LOCAL_TOKEN_SCOPES),
    lifetime: Annotated[
        str, typer.Option("--lifetime", help="Token lifetime (only long-lived is issued)")
    ] = "long-lived",
    config: Annotated[
        str | None,
        typer.Option("--config", help="CLI config YAML whose token creates the new one"),
    ] = None,
    api_url: Annotated[str | None, typer.Option("--api-url", help="Depictio API base URL")] = None,
    write_config: Annotated[
        Path | None,
        typer.Option(
            "--write-config",
            help="Also write a config usable with `depictio mcp serve --config` (mode 0600)",
        ),
    ] = None,
):
    """Create a scoped token for an MCP client and print it."""
    if lifetime != "long-lived":
        _stderr("Only long-lived tokens can be created for MCP clients.")
        raise typer.Exit(code=1)
    scope_list = [s.strip() for s in scopes.split(",") if s.strip()]
    if not scope_list:
        _stderr("--scopes needs at least one scope")
        raise typer.Exit(code=1)
    try:
        target = resolve_target(config, api_url, None, scoped_local=False)
        minted = mint_token(target.api_url, target.token, name, scope_list)
    except MCPConfigError as exc:
        _stderr(str(exc))
        raise typer.Exit(code=1)

    if write_config is not None:
        snippet = {
            "api_base_url": target.api_url,
            "user": {"token": {"name": name, "access_token": minted["access_token"]}},
        }
        _write_private(write_config.expanduser(), yaml.safe_dump(snippet, sort_keys=False))
        _stderr(f"Wrote {write_config} (use: depictio mcp serve --config {write_config})")
    _stderr(f"Token '{name}' with scopes {', '.join(scope_list)} on {target.api_url}:")
    typer.echo(minted["access_token"])


# ---------------------------------------------------------------------------
# install
# ---------------------------------------------------------------------------

CLAUDE_CODE_COMMAND = f"claude mcp add {SERVER_NAME} -- depictio mcp serve"


def claude_desktop_config_path() -> Path:
    if sys.platform == "darwin":
        return Path("~/Library/Application Support/Claude/claude_desktop_config.json").expanduser()
    if sys.platform == "win32":
        return (
            Path(os.environ.get("APPDATA", "~")).expanduser()
            / "Claude"
            / ("claude_desktop_config.json")
        )
    return Path("~/.config/Claude/claude_desktop_config.json").expanduser()


def claude_desktop_entry() -> dict:
    # Claude Desktop does not inherit the shell PATH, so point at the executable.
    command = shutil.which("depictio") or "depictio"
    return {"command": command, "args": ["mcp", "serve"]}


def merge_desktop_config(path: Path) -> Path | None:
    """Add the depictio server to a Claude Desktop config; returns the backup path."""
    backup = None
    data: dict = {}
    if path.exists():
        data = json.loads(path.read_text() or "{}")
        backup = path.with_name(f"{path.name}.bak-{datetime.now().strftime('%Y%m%d%H%M%S')}")
        shutil.copy2(path, backup)
    data.setdefault("mcpServers", {})[SERVER_NAME] = claude_desktop_entry()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")
    return backup


@app.command()
def install(
    client: Annotated[
        str,
        typer.Option("--client", help="claude-code, claude-desktop, or print (both snippets)"),
    ] = "print",
    write: Annotated[
        bool,
        typer.Option(
            "--write", help="With claude-desktop: merge into its config file (backed up first)"
        ),
    ] = False,
    desktop_config: Annotated[
        Path | None,
        typer.Option("--desktop-config", help="Claude Desktop config file (default per OS)"),
    ] = None,
):
    """Show how to register `depictio mcp serve` with Claude Code or Claude Desktop."""
    if client not in ("claude-code", "claude-desktop", "print"):
        _stderr("--client must be claude-code, claude-desktop or print")
        raise typer.Exit(code=1)
    if write and client != "claude-desktop":
        _stderr("--write only applies to --client claude-desktop")
        raise typer.Exit(code=1)

    if client in ("claude-code", "print"):
        typer.echo("Claude Code:")
        typer.echo(f"  {CLAUDE_CODE_COMMAND}")
    if client in ("claude-desktop", "print"):
        path = desktop_config or claude_desktop_config_path()
        if write:
            try:
                backup = merge_desktop_config(path)
            except ValueError as exc:
                _stderr(f"{path} is not valid JSON, left untouched: {exc}")
                raise typer.Exit(code=1)
            typer.echo(f"Added '{SERVER_NAME}' to {path}; restart Claude Desktop.")
            if backup:
                typer.echo(f"Previous config saved as {backup}")
            return
        if client == "print":
            typer.echo("")
        typer.echo(f"Claude Desktop ({path}):")
        typer.echo(json.dumps({"mcpServers": {SERVER_NAME: claude_desktop_entry()}}, indent=2))
