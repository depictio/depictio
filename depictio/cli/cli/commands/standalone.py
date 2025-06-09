from importlib.metadata import PackageNotFoundError, version

import typer


def register_standalone_commands(app: typer.Typer):
    @app.command("version")
    def version_cmd():
        """Show version information"""
        try:
            package_version = version("depictio-cli")  # Replace with your actual package name
            typer.echo(f"Depictio CLI version: {package_version}")
        except PackageNotFoundError:
            typer.echo("Depictio CLI version: unknown (not installed)")
