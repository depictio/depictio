"""`depictio config set-admin-credentials`: name a single-user server's admin."""

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from depictio.cli.cli.commands import config as config_cmd

MODULE = "depictio.cli.cli.commands.config"


def _run(args, response, stdin="new-pass-123\nnew-pass-123\n"):
    cli_config = MagicMock(api_base_url="http://depictio.test")
    with (
        patch(f"{MODULE}.resolve_server", return_value="cli.yaml"),
        patch(f"{MODULE}.load_depictio_config", return_value=cli_config),
        patch(f"{MODULE}.generate_api_headers", return_value={"Authorization": "Bearer t"}),
        patch(f"{MODULE}.httpx.post", return_value=response) as post,
    ):
        result = CliRunner().invoke(config_cmd.app, ["set-admin-credentials", *args], input=stdin)
    return result, post


def _response(status, body):
    response = MagicMock(status_code=status)
    response.json.return_value = body
    return response


def test_sends_the_prompted_password_never_an_argument():
    result, post = _run(
        ["--email", "me@lab.org"], _response(200, {"email": "me@lab.org", "success": True})
    )
    assert result.exit_code == 0, result.output
    assert (
        post.call_args.args[0] == "http://depictio.test/depictio/api/v1/auth/me/admin_credentials"
    )
    assert post.call_args.kwargs["json"] == {
        "email": "me@lab.org",
        "new_password": "new-pass-123",
        "current_password": None,
    }


def test_ask_current_sends_the_current_password():
    result, post = _run(
        ["--email", "me@lab.org", "--ask-current"],
        _response(200, {"email": "me@lab.org"}),
        stdin="old-pass-123\nnew-pass-123\nnew-pass-123\n",
    )
    assert result.exit_code == 0, result.output
    assert post.call_args.kwargs["json"]["current_password"] == "old-pass-123"


def test_a_refusal_exits_non_zero():
    result, _ = _run(
        ["--email", "me@lab.org"], _response(400, {"detail": "Current password is incorrect."})
    )
    assert result.exit_code == 1
