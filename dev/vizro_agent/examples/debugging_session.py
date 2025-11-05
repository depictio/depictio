"""
Example: Debugging Vizro code using VizroAgent.

This example demonstrates how to use the agent to identify
and fix common Vizro issues.
"""

import asyncio
import sys
sys.path.append("..")

from agent_core import VizroAgent, AgentContext, AgentMode


async def example_missing_field_error():
    """Debug missing required field error."""
    print("=== Example 1: Missing Required Field ===\n")

    agent = VizroAgent()

    buggy_code = """
import vizro.models as vm

page = vm.Page(title="My Dashboard")
    """

    error = "ValidationError: 1 validation error for Page\ncomponents\n  field required"

    context = AgentContext(
        mode=AgentMode.DEBUGGING,
        user_request="",
        code=buggy_code,
        error_message=error
    )

    result = await agent.process_request(context)

    print(f"Success: {result.success}")
    print(f"\nError Classification: Missing required field")
    print(f"\nFixed Code:\n{result.code}")
    print(f"\nExplanation:\n{result.explanation}")
    print(f"\nPrevention Tips:")
    for tip in result.suggestions or []:
        print(f"  - {tip}")


async def example_duplicate_id_error():
    """Debug duplicate component ID error."""
    print("\n\n=== Example 2: Duplicate Component IDs ===\n")

    agent = VizroAgent()

    buggy_code = """
import vizro.models as vm
import vizro.plotly.express as px

page = vm.Page(
    title="Dashboard",
    components=[
        vm.Graph(id="chart", figure=px.scatter(...)),
        vm.Graph(id="chart", figure=px.line(...))  # Duplicate!
    ]
)
    """

    error = "Duplicate callback outputs for id='chart'"

    context = AgentContext(
        mode=AgentMode.DEBUGGING,
        user_request="",
        code=buggy_code,
        error_message=error
    )

    result = await agent.process_request(context)

    print(f"Success: {result.success}")
    print(f"\nIssue: Duplicate component IDs causing callback conflicts")
    print(f"\nFixed Code:\n{result.code}")
    print(f"\nExplanation: {result.explanation}")


async def example_data_not_found_error():
    """Debug data reference error."""
    print("\n\n=== Example 3: Data Not Found ===\n")

    agent = VizroAgent()

    buggy_code = """
import vizro.models as vm
import vizro.plotly.express as px

# Note: data not registered in data_manager!

page = vm.Page(
    title="Dashboard",
    components=[
        vm.Graph(figure=px.scatter(data_frame="my_data", x="x", y="y"))
    ]
)
    """

    error = "KeyError: 'my_data' not found in data_manager"

    context = AgentContext(
        mode=AgentMode.DEBUGGING,
        user_request="",
        code=buggy_code,
        error_message=error
    )

    result = await agent.process_request(context)

    print(f"Success: {result.success}")
    print(f"\nIssue: Referenced data not registered")
    print(f"\nFixed Code:\n{result.code}")
    print(f"\nKey Fix: Register data before referencing")


async def example_type_mismatch_error():
    """Debug type mismatch error."""
    print("\n\n=== Example 4: Type Mismatch ===\n")

    agent = VizroAgent()

    buggy_code = """
import vizro.models as vm

page = vm.Page(
    title="Dashboard",
    components=[
        vm.Graph(figure="my_chart")  # String instead of Figure!
    ]
)
    """

    error = "ValidationError: value is not a valid dict (type=type_error.dict)"

    context = AgentContext(
        mode=AgentMode.DEBUGGING,
        user_request="",
        code=buggy_code,
        error_message=error
    )

    result = await agent.process_request(context)

    print(f"Success: {result.success}")
    print(f"\nIssue: Wrong parameter type")
    print(f"\nFixed Code:\n{result.code}")
    print(f"\nExplanation: {result.explanation}")


async def example_filter_column_not_found():
    """Debug filter column error."""
    print("\n\n=== Example 5: Filter Column Not Found ===\n")

    agent = VizroAgent()

    buggy_code = """
import vizro.models as vm
import vizro.plotly.express as px

df = px.data.iris()

page = vm.Page(
    title="Dashboard",
    components=[vm.Graph(figure=px.scatter(df, x="sepal_length", y="petal_width"))],
    controls=[
        vm.Filter(column="speciess")  # Typo! Should be "species"
    ]
)
    """

    error = "KeyError: 'speciess' not found in DataFrame columns"

    context = AgentContext(
        mode=AgentMode.DEBUGGING,
        user_request="",
        code=buggy_code,
        error_message=error
    )

    result = await agent.process_request(context)

    print(f"Success: {result.success}")
    print(f"\nIssue: Column name typo")
    print(f"\nFixed Code:\n{result.code}")
    print(f"\nTip: Verify column names with df.columns")


async def example_target_not_found():
    """Debug target component not found error."""
    print("\n\n=== Example 6: Target Component Not Found ===\n")

    agent = VizroAgent()

    buggy_code = """
import vizro.models as vm
import vizro.plotly.express as px

df = px.data.iris()

page = vm.Page(
    title="Dashboard",
    components=[
        vm.Graph(id="scatter_plot", figure=px.scatter(df, x="x", y="y"))
    ],
    controls=[
        vm.Filter(
            column="species",
            targets=["bar_chart"]  # This component doesn't exist!
        )
    ]
)
    """

    error = "ValueError: Target 'bar_chart' not found in page components"

    context = AgentContext(
        mode=AgentMode.DEBUGGING,
        user_request="",
        code=buggy_code,
        error_message=error
    )

    result = await agent.process_request(context)

    print(f"Success: {result.success}")
    print(f"\nIssue: Filter targeting non-existent component")
    print(f"\nFixed Code:\n{result.code}")
    print(f"\nSolution: Remove targets or fix component ID")


async def example_custom_chart_not_decorated():
    """Debug custom chart without @capture decorator."""
    print("\n\n=== Example 7: Custom Chart Missing Decorator ===\n")

    agent = VizroAgent()

    buggy_code = """
import vizro.models as vm
import plotly.graph_objects as go

# Missing @capture decorator!
def custom_chart(data_frame, x, y):
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=data_frame[x], y=data_frame[y]))
    return fig

page = vm.Page(
    title="Dashboard",
    components=[
        vm.Graph(figure=custom_chart(data_frame=df, x="x", y="y"))
    ]
)
    """

    error = "TypeError: Figure must be a plotly.graph_objects.Figure or captured function"

    context = AgentContext(
        mode=AgentMode.DEBUGGING,
        user_request="",
        code=buggy_code,
        error_message=error
    )

    result = await agent.process_request(context)

    print(f"Success: {result.success}")
    print(f"\nIssue: Custom function not decorated")
    print(f"\nFixed Code:\n{result.code}")
    print(f"\nKey: Add @capture('graph') decorator")


async def run_all_examples():
    """Run all debugging examples."""
    await example_missing_field_error()
    await example_duplicate_id_error()
    await example_data_not_found_error()
    await example_type_mismatch_error()
    await example_filter_column_not_found()
    await example_target_not_found()
    await example_custom_chart_not_decorated()


if __name__ == "__main__":
    print("Vizro Agent - Debugging Examples")
    print("=" * 50)
    print()

    # Run all examples
    asyncio.run(run_all_examples())

    print("\n" + "=" * 50)
    print("Debugging examples completed!")
    print("\nCommon Error Categories:")
    print("1. Missing required fields → Add with defaults")
    print("2. Type mismatches → Use correct types")
    print("3. Reference errors → Register/verify references")
    print("4. Callback conflicts → Use unique IDs")
    print("5. Configuration errors → Validate against schemas")
    print("\nThe agent provides:")
    print("- Root cause analysis")
    print("- Specific fixes")
    print("- Prevention tips")
    print("- Validated solutions")
