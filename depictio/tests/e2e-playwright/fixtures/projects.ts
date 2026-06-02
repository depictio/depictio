/**
 * Seeded reference project used by dashboard-management specs.
 * The Select option label is rendered as `${name} (${id})` — see the React
 * DashboardsPage create modal and the Dash `load_projects` callback.
 *
 * Static ID comes from depictio/api/v1/db_init.py (Iris init project).
 */
export const IRIS_PROJECT_ID = "646b0f3c1e4a2d7f8e5b8c9a";
export const IRIS_PROJECT_NAME = "Iris Dataset Project Data Analysis";
export const IRIS_PROJECT_LABEL = `${IRIS_PROJECT_NAME} (${IRIS_PROJECT_ID})`;
