import json
import sys
from collections import defaultdict
from io import StringIO
from typing import Optional

import polars as pl
from pydantic import validate_call
from rich import box, print, print_json
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from depictio.models.models.workflows import Workflow, WorkflowRun

console = Console(force_terminal=True)


@validate_call
def handle_error(message: str, exit: bool = False):
    """Print an error message and raise a ValueError."""
    print(f"• [bold red]:x: {message}[/bold red]")
    if exit:
        sys.exit()


@validate_call
def rich_print_command_usage(command: str):
    """
    Print the command usage in a styled panel.
    """
    console.print(
        Panel.fit(
            f"[bold magenta]{command}[/]",
            title="[cyan]Command Used[/]",
            border_style="bright_blue",
            title_align="center",
        )
    )


@validate_call
def rich_print_section_separator(title: str):
    """
    Print a section separator.
    """
    # get number of characters in title to determine length of separator
    console.print(
        Panel.fit(
            f"[bold magenta]{title}[/]",
            # title="[cyan]Section Separator[/]",
            border_style="bright_blue",
            title_align="center",
        )
    )


@validate_call
# json can be a dict or a list of dicts
def rich_print_json(statement: str, json_obj: dict | list[dict]):
    """
    Pretty print JSON object.
    """
    print(f"• [bold magenta]{statement}[/]")
    print_json(json.dumps(json_obj, indent=4))


@validate_call
def rich_print_checked_statement(statement: str, mode: str, exit: bool = False):
    """
    Print a statement with a check mark or cross.
    """
    if mode not in ["loading", "success", "error", "info", "warning"]:
        handle_error(f"Invalid mode: {mode}", exit=exit)
    if mode == "loading":
        print(f"• [bold yellow]:hourglass: {statement}[/bold yellow]")
    elif mode == "success":
        print(f"• [bold green]:white_check_mark: {statement}[/bold green]")
    elif mode == "error":
        print(f"• [bold red]:x: {statement}[/bold red]")
    elif mode == "info":
        print(f"• [bold blue]:blue_book: {statement}[/bold blue]")
    elif mode == "warning":
        print(f"• [bold orange1]:warning: {statement}[/bold orange1]")


def print_polars_with_rich(
    df: pl.DataFrame,
    title: Optional[str] = None,
    max_rows: int = 20,
    max_cols: int = 10,
    show_dtypes: bool = True,
    console: Optional[Console] = None,
) -> None:
    """
    Pretty print a Polars DataFrame using Rich.

    Args:
        df: Polars DataFrame to display
        title: Optional title for the table
        max_rows: Maximum number of rows to display
        max_cols: Maximum number of columns to display
        show_dtypes: Whether to show data types in column headers
        console: Rich Console instance (creates new one if None)
    """
    if console is None:
        console = Console()

    print("\n")

    # Limit rows and columns for display
    display_df = df.head(max_rows)
    if len(df.columns) > max_cols:
        display_df = display_df.select(df.columns[:max_cols])
        truncated_cols = True
    else:
        truncated_cols = False

    # Create Rich table
    table = Table(
        title=title or f"Polars DataFrame ({df.shape[0]} rows × {df.shape[1]} columns)",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold magenta",
        show_lines=True,
    )

    # Add columns with optional dtype information
    for col_name in display_df.columns:
        dtype = str(df[col_name].dtype)
        if show_dtypes:
            header = f"{col_name}\n[dim]({dtype})[/dim]"
        else:
            header = col_name
        table.add_column(header, justify="left", style="cyan", no_wrap=False)

    # Add truncated columns indicator
    if truncated_cols:
        table.add_column("...", style="dim", justify="center")

    # Add rows
    for row in display_df.iter_rows():
        # Convert each value to string, handling None values
        str_row = []
        for val in row:
            if val is None:
                str_row.append("[dim]null[/dim]")
            elif isinstance(val, float):
                str_row.append(f"{val:.4f}" if not (val != val) else "[dim]NaN[/dim]")  # Handle NaN
            else:
                str_row.append(str(val))

        if truncated_cols:
            str_row.append("...")

        table.add_row(*str_row)

    # Add truncated rows indicator
    if len(df) > max_rows:
        truncated_row = ["..." for _ in range(len(display_df.columns))]
        if truncated_cols:
            truncated_row.append("...")
        table.add_row(*truncated_row, style="dim")

    console.print(table)

    # Print summary info
    if len(df) > max_rows or truncated_cols:
        summary = f"Showing {min(max_rows, len(df))} of {len(df)} rows"
        if truncated_cols:
            summary += f", {max_cols} of {len(df.columns)} columns"
        console.print(f"\n[dim]{summary}[/dim]\n")


def print_polars_info_with_rich(
    df: pl.DataFrame, extended: bool = False, console: Optional[Console] = None
) -> None:
    """
    Print DataFrame info (like df.describe()) using Rich.
    """
    if console is None:
        console = Console()

    # Create info table
    info_table = Table(box=box.SIMPLE, show_header=True, header_style="bold blue")

    info_table.add_column("Property", style="cyan")
    info_table.add_column("Value", style="green")

    info_table.add_row("Shape", f"{df.shape[0]} rows × {df.shape[1]} columns")
    info_table.add_row("Memory Usage", f"{df.estimated_size('mb'):.2f} MB")
    info_table.add_row("Columns", ", ".join(df.columns))

    console.print(info_table)

    if extended:
        # Create dtypes table
        dtype_table = Table(
            title="Column Data Types", box=box.SIMPLE, show_header=True, header_style="bold blue"
        )

        dtype_table.add_column("Column", style="cyan")
        dtype_table.add_column("Data Type", style="green")
        dtype_table.add_column("Null Count", style="yellow")

        for col in df.columns:
            null_count = df[col].null_count()
            dtype_table.add_row(col, str(df[col].dtype), str(null_count))

        console.print(dtype_table)


def print_polars_describe_with_rich(df: pl.DataFrame, console: Optional[Console] = None) -> None:
    """
    Print DataFrame description statistics using Rich.
    """
    if console is None:
        console = Console()

    try:
        print("\n")
        desc_df = df.describe()
        print_polars_with_rich(
            desc_df, title="Descriptive Statistics", max_rows=50, show_dtypes=False, console=console
        )
    except Exception as e:
        console.print(f"[red]Error generating describe: {e}[/red]")


def print_polars_head_tail_with_rich(
    df: pl.DataFrame, n: int = 5, console: Optional[Console] = None
) -> None:
    """
    Print head and tail of DataFrame side by side using Rich.
    """
    if console is None:
        console = Console()

    # Create layout with panels
    head_df = df.head(n)
    tail_df = df.tail(n)

    # Capture head table
    head_console = Console(file=StringIO(), width=60)
    print_polars_with_rich(
        head_df, title=f"Head ({n} rows)", console=head_console, show_dtypes=False
    )
    head_output = head_console.file.getvalue()  # type: ignore[unresolved-attribute]

    # Capture tail table
    tail_console = Console(file=StringIO(), width=60)
    print_polars_with_rich(
        tail_df, title=f"Tail ({n} rows)", console=tail_console, show_dtypes=False
    )
    tail_output = tail_console.file.getvalue()  # type: ignore[unresolved-attribute]

    # Print side by side using columns
    from rich.columns import Columns

    console.print(Columns([Panel(head_output, title="Head"), Panel(tail_output, title="Tail")]))


# Convenience function - monkey patch Polars DataFrame
def add_rich_display_to_polars():
    """
    Add rich display methods to Polars DataFrame.
    Call this once to enable df.rich_print() methods.
    """

    def rich_print(self, title=None, max_rows=20, max_cols=10, show_dtypes=True, console=None):
        print_polars_with_rich(
            self,
            title=title,
            max_rows=max_rows,
            max_cols=max_cols,
            show_dtypes=show_dtypes,
            console=console,
        )

    def rich_info(self, extended=False, console=None):
        print_polars_info_with_rich(self, extended=extended, console=console)

    def rich_describe(self, console=None):
        print_polars_describe_with_rich(self, console=console)

    def rich_head_tail(self, n=5, console=None):
        print_polars_head_tail_with_rich(self, n=n, console=console)

    # Add methods to Polars DataFrame
    pl.DataFrame.rich_print = rich_print  # type: ignore[unresolved-attribute]
    pl.DataFrame.rich_info = rich_info  # type: ignore[unresolved-attribute]
    pl.DataFrame.rich_describe = rich_describe  # type: ignore[unresolved-attribute]
    pl.DataFrame.rich_head_tail = rich_head_tail  # type: ignore[unresolved-attribute]


# # Example usage
# if __name__ == "__main__":
#     # Create sample data
#     df = pl.DataFrame({
#         "name": ["Alice", "Bob", "Charlie", "Diana", "Eve"],
#         "age": [25, 30, 35, 28, 32],
#         "salary": [50000.0, 60000.0, 70000.0, 55000.0, 65000.0],
#         "department": ["Engineering", "Marketing", "Engineering", "HR", "Marketing"],
#         "is_remote": [True, False, True, False, True]
#     })

#     console = Console()

#     # Method 1: Direct function calls
#     console.print("\n[bold blue]Method 1: Direct function calls[/bold blue]")
#     print_polars_with_rich(df, title="Employee Data")

#     console.print("\n" + "="*50 + "\n")
#     print_polars_info_with_rich(df)

#     console.print("\n" + "="*50 + "\n")
#     print_polars_describe_with_rich(df)

#     # Method 2: Monkey patched methods
#     console.print("\n[bold blue]Method 2: Monkey patched methods[/bold blue]")
#     add_rich_display_to_polars()

#     df.rich_print(title="Using Monkey Patch", max_rows=3)

#     console.print("\n" + "="*50 + "\n")
#     df.rich_info()

#     # Create larger dataset for demonstration
#     large_df = pl.DataFrame({
#         f"col_{i}": range(i, i + 100) for i in range(15)
#     })

#     console.print("\n[bold blue]Large DataFrame (truncated display)[/bold blue]")
#     large_df.rich_print(title="Large Dataset", max_rows=5, max_cols=5)


def rich_print_summary_scan_table_enhanced(
    runs: list[WorkflowRun], workflow: Workflow, show_totals: bool = True
) -> None:
    from rich import box
    from rich.console import Console
    from rich.table import Table

    print("\n")
    console = Console()

    # Debug: Check what we received
    # console.print(f"[dim]Debug: Processing {len(runs)} runs[/dim]")

    # for run in runs:
    #     # console.print(
    #     #     f"[dim]Debug: Run {run.run_tag} has {len(run.scan_results)} scan results[/dim]"
    #     # )
    #     if run.scan_results:
    #         latest_scan = run.scan_results[-1]
    #         if hasattr(latest_scan, "dc_stats") and latest_scan.dc_stats:
    #             # console.print(
    #             #     f"[dim]Debug: Run {run.run_tag} has dc_stats: {list(latest_scan.dc_stats.keys())}[/dim]"
    #             # )
    #         else:
    #             console.print(f"[dim]Debug: Run {run.run_tag} has NO dc_stats or it's empty[/dim]")

    # Create the table
    table = Table(
        title="Workflow Runs Files Scan Results Stats Summary (by Data Collection)",
        box=box.ROUNDED,
        show_lines=True,
    )

    # Define columns
    table.add_column("Run Tag", style="cyan", justify="left", min_width=15)
    table.add_column("Data Collection", style="yellow", justify="left", min_width=18)
    table.add_column("Total", justify="center", min_width=7)
    table.add_column("Updated", justify="center", min_width=7)
    table.add_column("New", justify="center", min_width=7)
    table.add_column("Missing", justify="center", min_width=7)
    table.add_column("Deleted", justify="center", min_width=7)
    table.add_column("Skipped", justify="center", min_width=7)
    table.add_column("Other", justify="center", min_width=7)

    # Track totals
    grand_totals = {
        "total_files": 0,
        "updated_files": 0,
        "new_files": 0,
        "missing_files": 0,
        "deleted_files": 0,
        "skipped_files": 0,
        "other_failure_files": 0,
    }

    # Check if any runs have dc_stats data
    has_dc_stats = any(
        run.scan_results
        and hasattr(run.scan_results[-1], "dc_stats")
        and run.scan_results[-1].dc_stats
        and len(run.scan_results[-1].dc_stats) > 0
        for run in runs
    )

    # If no dc_stats found, create empty data for all data collections in workflow
    if not has_dc_stats and workflow and hasattr(workflow, "data_collections"):
        for dc in workflow.data_collections:
            table.add_row(
                "[dim]No scan data[/dim]",
                f"[yellow]{dc.data_collection_tag}[/yellow]",
                "0",
                "0",
                "0",
                "0",
                "0",
                "0",
                "0",
            )

        console.print(table)
        console.print(
            "[dim]No scan results found. Showing data collections with zero counts.[/dim]"
        )
        return

    # Populate table
    for run_idx, run in enumerate(runs):
        if not run.scan_results:
            continue

        scan_results = run.scan_results[-1]

        # Check if we have per-data-collection stats
        if (
            hasattr(scan_results, "dc_stats")
            and scan_results.dc_stats
            and len(scan_results.dc_stats) > 0
        ):
            # console.print(f"[dim]Debug: Displaying dc_stats for run {run.run_tag}[/dim]")

            # Show breakdown by data collection
            first_row = True
            run_totals = {key: 0 for key in grand_totals.keys()}

            for dc_tag, stats in scan_results.dc_stats.items():
                # Only show run tag in the first row for this run
                run_tag_display = f"[bold]{run.run_tag}[/bold]" if first_row else ""
                first_row = False

                table.add_row(
                    run_tag_display,
                    f"[yellow]{dc_tag}[/yellow]",
                    str(stats.get("total_files", 0)),
                    str(stats.get("updated_files", 0)),
                    str(stats.get("new_files", 0)),
                    str(stats.get("missing_files", 0)),
                    str(stats.get("deleted_files", 0)),
                    str(stats.get("skipped_files", 0)),
                    str(stats.get("other_failure_files", 0)),
                )

                # Update totals
                for key in run_totals.keys():
                    run_totals[key] += stats.get(key, 0)
                    grand_totals[key] += stats.get(key, 0)

            # Add run total if multiple data collections
            if show_totals and len(scan_results.dc_stats) > 1:
                table.add_row(
                    "",
                    "[dim italic]Run Total[/dim italic]",
                    f"[bold]{run_totals['total_files']}[/bold]",
                    f"[bold]{run_totals['updated_files']}[/bold]",
                    f"[bold]{run_totals['new_files']}[/bold]",
                    f"[bold]{run_totals['missing_files']}[/bold]",
                    f"[bold]{run_totals['deleted_files']}[/bold]",
                    f"[bold]{run_totals['skipped_files']}[/bold]",
                    f"[bold]{run_totals['other_failure_files']}[/bold]",
                    style="dim",
                )
        else:
            console.print(
                f"[dim]Debug: Using fallback aggregated stats for run {run.run_tag}[/dim]"
            )

            # Fallback to aggregated stats
            stats = scan_results.stats
            table.add_row(
                f"[bold]{run.run_tag}[/bold]",
                "[dim]aggregated[/dim]",
                str(stats.get("total_files", "")),
                str(stats.get("updated_files", "")),
                str(stats.get("new_files", "")),
                str(stats.get("missing_files", "")),
                str(stats.get("deleted_files", "")),
                str(stats.get("skipped_files", "")),
                str(stats.get("other_failure_files", "")),
            )

            # Update grand totals
            for key in grand_totals.keys():
                grand_totals[key] += stats.get(key, 0)

        # Add separator between runs
        if run_idx < len(runs) - 1:
            table.add_row("", "", "", "", "", "", "", "", "", style="dim", end_section=True)

    # Add grand total row
    if show_totals and len(runs) > 1:
        table.add_section()
        table.add_row(
            "[bold blue]TOTAL[/bold blue]",
            "[bold blue]All Collections[/bold blue]",
            f"[bold blue]{grand_totals['total_files']}[/bold blue]",
            f"[bold blue]{grand_totals['updated_files']}[/bold blue]",
            f"[bold blue]{grand_totals['new_files']}[/bold blue]",
            f"[bold blue]{grand_totals['missing_files']}[/bold blue]",
            f"[bold blue]{grand_totals['deleted_files']}[/bold blue]",
            f"[bold blue]{grand_totals['skipped_files']}[/bold blue]",
            f"[bold blue]{grand_totals['other_failure_files']}[/bold blue]",
        )

    console.print(table)


def rich_print_summary_scan_table_by_dc(runs: list[WorkflowRun]) -> None:
    from rich import box
    from rich.console import Console
    from rich.table import Table

    print("\n")

    # Collect all data collections and their stats across runs
    dc_data: dict[str, list[tuple[str, dict]]] = defaultdict(list)

    for run in runs:
        if not run.scan_results:
            continue

        scan_results = run.scan_results[-1]

        if hasattr(scan_results, "dc_stats") and scan_results.dc_stats:
            for dc_tag, stats in scan_results.dc_stats.items():
                if dc_tag not in dc_data:
                    dc_data[dc_tag] = []
                dc_data[dc_tag].append((run.run_tag, stats))

    # Create table grouped by data collection
    table = Table(
        title="Workflow Runs Files Scan Results (Grouped by Data Collection)",
        box=box.ROUNDED,
        show_lines=True,
    )

    table.add_column("Data Collection", style="yellow", justify="left", min_width=18)
    table.add_column("Run Tag", style="cyan", justify="left", min_width=15)
    table.add_column("Total", justify="center")
    table.add_column("Updated", justify="center")
    table.add_column("New", justify="center")
    table.add_column("Missing", justify="center")
    table.add_column("Deleted", justify="center")
    table.add_column("Skipped", justify="center")
    table.add_column("Other", justify="center")

    for dc_idx, (dc_tag, run_data) in enumerate(dc_data.items()):
        first_row = True
        dc_totals = {
            key: 0
            for key in [
                "total_files",
                "updated_files",
                "new_files",
                "missing_files",
                "deleted_files",
                "skipped_files",
                "other_failure_files",
            ]
        }

        for run_tag, stats in run_data:
            # Only show DC tag in first row
            dc_display = f"[bold yellow]{dc_tag}[/bold yellow]" if first_row else ""
            first_row = False

            table.add_row(
                dc_display,
                run_tag,
                str(stats.get("total_files", 0)),
                str(stats.get("updated_files", 0)),
                str(stats.get("new_files", 0)),
                str(stats.get("missing_files", 0)),
                str(stats.get("deleted_files", 0)),
                str(stats.get("skipped_files", 0)),
                str(stats.get("other_failure_files", 0)),
            )

            # Update DC totals
            for key in dc_totals.keys():
                dc_totals[key] += stats.get(key, 0)

        # Add DC summary row
        if len(run_data) > 1:
            table.add_row(
                "",
                "[dim italic]DC Total[/dim italic]",
                f"[bold]{dc_totals['total_files']}[/bold]",
                f"[bold]{dc_totals['updated_files']}[/bold]",
                f"[bold]{dc_totals['new_files']}[/bold]",
                f"[bold]{dc_totals['missing_files']}[/bold]",
                f"[bold]{dc_totals['deleted_files']}[/bold]",
                f"[bold]{dc_totals['skipped_files']}[/bold]",
                f"[bold]{dc_totals['other_failure_files']}[/bold]",
                style="dim",
            )

        # Add separator between data collections
        if dc_idx < len(dc_data) - 1:
            table.add_section()

    console = Console()
    console.print(table)


def rich_print_data_collection_light(runs: list[WorkflowRun], workflow: Workflow) -> None:
    """
    Print both simple and detailed data collection summaries.

    Args:
        runs: List of WorkflowRun objects with dc_stats
    """

    console = Console()

    # Aggregate all stats by data collection
    dc_detailed: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "total_files": 0,
            "new_files": 0,
            "updated_files": 0,
            "skipped_files": 0,
            "other_failure_files": 0,
        }
    )

    for run in runs:
        if hasattr(run, "_dc_stats_for_display") and run._dc_stats_for_display:
            for dc_tag, stats in run._dc_stats_for_display.items():
                for key in dc_detailed[dc_tag].keys():
                    dc_detailed[dc_tag][key] += stats.get(key, 0)

    if not dc_detailed:
        # console.print("[yellow]No data collection statistics found[/yellow]")
        # return
        # Set a default empty state
        dc_detailed = {
            dc.data_collection_tag: {
                "total_files": 0,
                "new_files": 0,
                "updated_files": 0,
                "skipped_files": 0,
                "other_failure_files": 0,
            }
            for dc in workflow.data_collections
        }

    print("\n")

    # ============= SIMPLE SUMMARY TABLE =============
    simple_table = Table(
        title="Data Collection Files Summary",
        show_header=True,
        header_style="bold blue",
        border_style="blue",
    )

    simple_table.add_column("Data Collection", style="cyan", justify="left", min_width=20)
    simple_table.add_column("Total Files", style="green", justify="center", min_width=12)

    # Add data collection rows (sorted alphabetically)
    total_files = 0
    for dc_tag in sorted(dc_detailed.keys()):
        file_count = dc_detailed[dc_tag]["total_files"]
        total_files += file_count
        simple_table.add_row(dc_tag, str(file_count))

    # Add separator and total row
    if len(dc_detailed) > 1:
        simple_table.add_section()
        simple_table.add_row("[bold]TOTAL[/bold]", f"[bold]{total_files}[/bold]")

    console.print(simple_table)
    console.print(
        f"[dim]Summary: {len(dc_detailed)} data collections, {total_files} total files processed[/dim]"
    )

    print("\n")
