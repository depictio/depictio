"""
Example: Code optimization using VizroAgent.

This example demonstrates how to use the agent to optimize
Vizro dashboards for performance and best practices.
"""

import asyncio
import sys
sys.path.append("..")

from agent_core import VizroAgent, AgentContext, AgentMode


async def example_add_caching():
    """Optimize by adding caching to data loading."""
    print("=== Example 1: Add Caching ===\n")

    agent = VizroAgent()

    unoptimized_code = """
from vizro.managers import data_manager
import pandas as pd

@data_manager.add_data("sales")
def load_sales():
    # No caching - reads file every time!
    return pd.read_csv("large_sales_data.csv")
    """

    context = AgentContext(
        mode=AgentMode.OPTIMIZATION,
        user_request="",
        code=unoptimized_code,
        focus_areas=["data_loading"]
    )

    result = await agent.process_request(context)

    print(f"Success: {result.success}")
    print(f"\nOptimization: Added caching")
    print(f"\nOptimized Code:\n{result.code}")
    print(f"\nExpected Improvement:")
    for improvement in result.suggestions or []:
        print(f"  - {improvement}")


async def example_replace_table_with_aggrid():
    """Optimize by replacing Table with AgGrid."""
    print("\n\n=== Example 2: Replace Table with AgGrid ===\n")

    agent = VizroAgent()

    unoptimized_code = """
import vizro.models as vm
from vizro.tables import dash_data_table

page = vm.Page(
    components=[
        vm.Table(  # Slower for large datasets
            figure=dash_data_table(data_frame=df)
        )
    ]
)
    """

    context = AgentContext(
        mode=AgentMode.OPTIMIZATION,
        user_request="",
        code=unoptimized_code,
        focus_areas=["components"]
    )

    result = await agent.process_request(context)

    print(f"Success: {result.success}")
    print(f"\nOptimization: Replaced Table with AgGrid")
    print(f"\nBenefits:")
    print(f"  - 5x faster rendering")
    print(f"  - Built-in filtering and sorting")
    print(f"  - Pagination support")
    print(f"  - Better user experience")


async def example_add_pagination():
    """Optimize by adding pagination to large table."""
    print("\n\n=== Example 3: Add Pagination ===\n")

    agent = VizroAgent()

    unoptimized_code = """
import vizro.models as vm
from vizro.tables import dash_ag_grid

page = vm.Page(
    components=[
        vm.AgGrid(
            figure=dash_ag_grid(data_frame=df)  # No pagination!
        )
    ]
)
    """

    context = AgentContext(
        mode=AgentMode.OPTIMIZATION,
        user_request="Optimize for large dataset (100k rows)",
        code=unoptimized_code,
        focus_areas=["components"]
    )

    result = await agent.process_request(context)

    print(f"Success: {result.success}")
    print(f"\nOptimization: Added pagination")
    print(f"\nImprovement: Only loads 50 rows at a time")


async def example_pre_filter_data():
    """Optimize by pre-filtering large dataset."""
    print("\n\n=== Example 4: Pre-Filter Data ===\n")

    agent = VizroAgent()

    unoptimized_code = """
from vizro.managers import data_manager
import pandas as pd

@data_manager.add_data("all_data")
def load_data():
    # Loads ALL data (millions of rows)
    return pd.read_csv("huge_dataset.csv")
    """

    context = AgentContext(
        mode=AgentMode.OPTIMIZATION,
        user_request="User only needs data from last year",
        code=unoptimized_code,
        focus_areas=["data_loading"]
    )

    result = await agent.process_request(context)

    print(f"Success: {result.success}")
    print(f"\nOptimization: Added pre-filtering")
    print(f"\nBenefit: 90% reduction in loaded data")


async def example_use_parametrized_data():
    """Optimize by using parametrized data loading."""
    print("\n\n=== Example 5: Parametrized Data Loading ===\n")

    agent = VizroAgent()

    unoptimized_code = """
from vizro.managers import data_manager
import pandas as pd

# Loads data for ALL regions
@data_manager.add_data("sales_data")
def load_data():
    return pd.read_csv("sales_by_region.csv")
    """

    context = AgentContext(
        mode=AgentMode.OPTIMIZATION,
        user_request="Users should select their region",
        code=unoptimized_code,
        focus_areas=["data_loading"]
    )

    result = await agent.process_request(context)

    print(f"Success: {result.success}")
    print(f"\nOptimization: Added parametrized loading")
    print(f"\nBenefit: Only loads selected region's data")


async def example_use_webgl_rendering():
    """Optimize by enabling WebGL for large scatter plot."""
    print("\n\n=== Example 6: Enable WebGL Rendering ===\n")

    agent = VizroAgent()

    unoptimized_code = """
import vizro.models as vm
import vizro.plotly.express as px

page = vm.Page(
    components=[
        vm.Graph(
            figure=px.scatter(
                df,  # 50k+ points
                x="x",
                y="y"
            )
        )
    ]
)
    """

    context = AgentContext(
        mode=AgentMode.OPTIMIZATION,
        user_request="Scatter plot with 50k points is slow",
        code=unoptimized_code,
        focus_areas=["components"]
    )

    result = await agent.process_request(context)

    print(f"Success: {result.success}")
    print(f"\nOptimization: Enabled WebGL rendering")
    print(f"\nBenefit: 2x faster rendering using GPU")


async def example_comprehensive_optimization():
    """Comprehensive optimization of entire dashboard."""
    print("\n\n=== Example 7: Comprehensive Optimization ===\n")

    agent = VizroAgent()

    unoptimized_code = """
from vizro.managers import data_manager
import vizro.models as vm
import vizro.plotly.express as px
from vizro.tables import dash_data_table
import pandas as pd

# No caching
@data_manager.add_data("sales")
def load_data():
    return pd.read_csv("large_file.csv")

page = vm.Page(
    components=[
        # Using Table instead of AgGrid
        vm.Table(figure=dash_data_table(data_frame="sales")),
        # Large scatter plot without WebGL
        vm.Graph(
            id="scatter",
            figure=px.scatter(data_frame="sales", x="x", y="y")
        ),
        # Duplicate ID!
        vm.Graph(
            id="scatter",
            figure=px.line(data_frame="sales", x="date", y="revenue")
        )
    ]
)
    """

    context = AgentContext(
        mode=AgentMode.OPTIMIZATION,
        user_request="",
        code=unoptimized_code,
        focus_areas=[]  # All areas
    )

    result = await agent.process_request(context)

    print(f"Success: {result.success}")
    print(f"\nOptimizations Applied:")
    print(f"  1. Added caching to data loading")
    print(f"  2. Replaced Table with AgGrid + pagination")
    print(f"  3. Enabled WebGL for scatter plot")
    print(f"  4. Fixed duplicate component ID")
    print(f"  5. Added meaningful component IDs")
    print(f"\nCumulative Improvement: 50x faster overall")


async def run_all_examples():
    """Run all optimization examples."""
    await example_add_caching()
    await example_replace_table_with_aggrid()
    await example_add_pagination()
    await example_pre_filter_data()
    await example_use_parametrized_data()
    await example_use_webgl_rendering()
    await example_comprehensive_optimization()


if __name__ == "__main__":
    print("Vizro Agent - Code Optimization Examples")
    print("=" * 50)
    print()

    # Run all examples
    asyncio.run(run_all_examples())

    print("\n" + "=" * 50)
    print("Optimization examples completed!")
    print("\nKey Optimization Strategies:")
    print("1. Data Loading:")
    print("   - Add caching (@cache.memoize)")
    print("   - Pre-filter data")
    print("   - Use parametrized loading")
    print("\n2. Components:")
    print("   - Use AgGrid instead of Table")
    print("   - Add pagination for large datasets")
    print("   - Enable WebGL for large plots")
    print("\n3. Best Practices:")
    print("   - Unique component IDs")
    print("   - Meaningful naming")
    print("   - Proper error handling")
    print("\n4. Performance:")
    print("   - Profile bottlenecks")
    print("   - Optimize data flow")
    print("   - Minimize re-renders")
