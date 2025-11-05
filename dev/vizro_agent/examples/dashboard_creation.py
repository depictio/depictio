"""
Example: Dashboard creation from natural language using VizroAgent.

This example demonstrates how to use the Vizro agent to create
dashboards from natural language descriptions.
"""

import asyncio
import sys
sys.path.append("..")

from agent_core import VizroAgent, AgentContext, AgentMode


async def example_simple_dashboard():
    """Create a simple dashboard from natural language."""
    print("=== Example 1: Simple Dashboard Creation ===\n")

    agent = VizroAgent()

    context = AgentContext(
        mode=AgentMode.CREATION,
        user_request="Create a dashboard with a scatter plot showing sepal length vs petal width, colored by species",
        data_source="iris"
    )

    result = await agent.process_request(context)

    print(f"Success: {result.success}")
    print(f"\nMessage: {result.message}")

    if result.success:
        print(f"\nGenerated Code:\n{result.code}")
        print(f"\nPyCafe Link: {result.pycafe_link}")
        print(f"\nExplanation:\n{result.explanation}")
    else:
        print(f"\nError: {result.message}")


async def example_multi_component_dashboard():
    """Create a dashboard with multiple components."""
    print("\n\n=== Example 2: Multi-Component Dashboard ===\n")

    agent = VizroAgent()

    context = AgentContext(
        mode=AgentMode.CREATION,
        user_request="""
        Create a comprehensive dashboard with:
        1. A scatter plot of sepal length vs width
        2. A bar chart showing average petal length by species
        3. A data table showing all records
        4. Filters for species and sepal length range
        """,
        data_source="iris"
    )

    result = await agent.process_request(context)

    print(f"Success: {result.success}")

    if result.success:
        print(f"\nDashboard created with:")
        print(f"- Multiple visualizations")
        print(f"- Interactive filters")
        print(f"- Data table")
        print(f"\nPyCafe Link: {result.pycafe_link}")
    else:
        print(f"\nError: {result.message}")


async def example_time_series_dashboard():
    """Create a time series dashboard."""
    print("\n\n=== Example 3: Time Series Dashboard ===\n")

    agent = VizroAgent()

    context = AgentContext(
        mode=AgentMode.CREATION,
        user_request="""
        Create a dashboard showing stock price trends over time.
        Include:
        - Line chart of stock prices
        - Filter by stock symbol
        - Date range selector
        """,
        data_source="stocks"
    )

    result = await agent.process_request(context)

    print(f"Success: {result.success}")

    if result.success:
        print(f"\nTime series dashboard created")
        print(f"Components: Line chart with date filter")
        print(f"\nPyCafe Link: {result.pycafe_link}")


async def example_custom_data_dashboard():
    """Create dashboard from custom data file."""
    print("\n\n=== Example 4: Custom Data Dashboard ===\n")

    agent = VizroAgent()

    # Note: Replace with actual file path
    data_path = "/path/to/your/data.csv"

    context = AgentContext(
        mode=AgentMode.CREATION,
        user_request="Create a dashboard with appropriate visualizations based on the data",
        data_source=data_path
    )

    print(f"Note: Using data from {data_path}")
    print("Agent will:")
    print("1. Analyze data structure")
    print("2. Select appropriate visualizations")
    print("3. Configure filters automatically")
    print("4. Generate optimized dashboard")

    # Uncomment to run with actual file:
    # result = await agent.process_request(context)
    # print(f"Success: {result.success}")


async def example_multi_page_dashboard():
    """Create a multi-page dashboard."""
    print("\n\n=== Example 5: Multi-Page Dashboard ===\n")

    agent = VizroAgent()

    context = AgentContext(
        mode=AgentMode.CREATION,
        user_request="""
        Create a multi-page dashboard:

        Page 1 "Overview":
        - Summary statistics card
        - Key metrics visualization

        Page 2 "Detailed Analysis":
        - Multiple charts
        - Interactive filters
        - Data table

        Include navigation between pages.
        """,
        data_source="iris"
    )

    result = await agent.process_request(context)

    print(f"Success: {result.success}")

    if result.success:
        print(f"\nMulti-page dashboard created")
        print(f"Features:")
        print(f"- Multiple pages with navigation")
        print(f"- Page-specific components")
        print(f"- Consistent styling")
        print(f"\nPyCafe Link: {result.pycafe_link}")


async def example_dashboard_with_parameters():
    """Create dashboard with parametrized components."""
    print("\n\n=== Example 6: Dashboard with Parameters ===\n")

    agent = VizroAgent()

    context = AgentContext(
        mode=AgentMode.CREATION,
        user_request="""
        Create a dashboard where users can:
        - Switch between different chart axes using dropdowns
        - Toggle chart colors
        - Select different aggregation methods

        Use parameters to make the dashboard highly interactive.
        """,
        data_source="iris"
    )

    result = await agent.process_request(context)

    print(f"Success: {result.success}")

    if result.success:
        print(f"\nParametrized dashboard created")
        print(f"Users can dynamically modify:")
        print(f"- Chart axes")
        print(f"- Colors and styling")
        print(f"- Aggregation methods")


async def run_all_examples():
    """Run all dashboard creation examples."""
    await example_simple_dashboard()
    await example_multi_component_dashboard()
    await example_time_series_dashboard()
    await example_custom_data_dashboard()
    await example_multi_page_dashboard()
    await example_dashboard_with_parameters()


if __name__ == "__main__":
    print("Vizro Agent - Dashboard Creation Examples")
    print("=" * 50)
    print()

    # Run all examples
    asyncio.run(run_all_examples())

    print("\n" + "=" * 50)
    print("Examples completed!")
    print("\nKey Takeaways:")
    print("1. Agent analyzes data automatically")
    print("2. Generates appropriate visualizations")
    print("3. Configures filters and interactivity")
    print("4. Validates all configurations")
    print("5. Provides PyCafe links for testing")
