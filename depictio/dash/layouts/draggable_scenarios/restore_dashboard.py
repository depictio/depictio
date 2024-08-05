from depictio.dash.modules.card_component.utils import build_card
from depictio.dash.modules.figure_component.utils import build_figure
from depictio.api.v1.db import dashboards_collection
from dash import html
from depictio.dash.layouts.header import enable_box_edit_mode
from depictio.api.v1.configs.logging import logger
from depictio.dash.modules.interactive_component.utils import build_interactive
from depictio.dash.modules.jbrowse_component.utils import build_jbrowse
from depictio.dash.modules.table_component.utils import build_table


def load_depictio_data(dashboard_id):
    build_functions = {
        "card": build_card,
        "figure": build_figure,
        "interactive": build_interactive,
        "table": build_table,
        "jbrowse": build_jbrowse,
    }

    dashboard_data = dashboards_collection.find_one({"dashboard_id": dashboard_id})
    logger.info(f"load_depictio_data : {dashboard_data}")
    # logger.info(f"dashboard_data : {dashboard_data}")

    if dashboard_data:
        children = list()
        if "stored_metadata" in dashboard_data:
            for child_metadata in dashboard_data["stored_metadata"]:
                child_metadata["build_frame"] = True
                logger.info(child_metadata)
                logger.info(f"type of child_metadata : {type(child_metadata)}")

                # Extract the type of the child (assuming there is a type key in the metadata)
                component_type = child_metadata.get("component_type", None)
                logger.info(f"component_type : {component_type}")
                if component_type not in build_functions:
                    logger.warning(f"Unsupported child type: {component_type}")
                    raise ValueError(f"Unsupported child type: {component_type}")

                # Get the build function based on the type
                build_function = build_functions[component_type]
                logger.info(f"build_function : {build_function.__name__}")

                # Build the child using the appropriate function and kwargs
                child = build_function(**child_metadata)
                logger.info(f"child : ")
                # logger.info(child)
                children.append(child)

            # if children:
            logger.info(f"BEFORE child :")

            # Convert children to their plotly JSON representation
            children = [enable_box_edit_mode(child.to_plotly_json(), switch_state=True) for child in children]
            # children = enable_box_edit_mode(children[0].to_plotly_json(), switch_state=True)
            # logger.info(f"AFTER child : {children}")

            dashboard_data["stored_children_data"] = children
            # logger.info(f"dashboard_data['stored_children_data'] : {dashboard_data['stored_children_data']}")
            logger.info(f"dashboard_data['stored_layout_data'] : {dashboard_data['stored_layout_data']}")

        return dashboard_data
    else:
        return None

    # if os.path.exists("/app/data/depictio_data.json"):
    #     with open("/app/data/depictio_data.json", "r") as file:
    #         data = json.load(file)
    #         # print(data.keys())
    #     return data
    return None
