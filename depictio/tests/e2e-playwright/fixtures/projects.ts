/**
 * Seeded reference project used by dashboard-management specs.
 *
 * The viewer (depictio/viewer/) uses only p.name as the Select label.
 * The legacy react-frontend scaffold appended the ID: "Name (id)".
 *
 * Static ID comes from depictio/api/v1/db_init.py (Iris init project).
 */
export const IRIS_PROJECT_ID = "646b0f3c1e4a2d7f8e5b8c9a";
export const IRIS_PROJECT_NAME = "Iris Dataset Project Data Analysis";
export const IRIS_PROJECT_LABEL = IRIS_PROJECT_NAME;

/** Seeded iris dashboard ("Iris Dataset Analysis"), owned by the bootstrap
 *  admin. Static ID comes from the .db_seeds JSON loaded by db_init.py. */
export const IRIS_DASHBOARD_ID = "6824cb3b89d2b72169309737";
