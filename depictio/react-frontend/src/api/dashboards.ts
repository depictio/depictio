import { apiClient, API_PREFIX } from "./client";
import type { Dashboard, Project, User } from "./types";

export async function listDashboards(): Promise<Dashboard[]> {
  const { data } = await apiClient.get<Dashboard[]>(
    `${API_PREFIX}/dashboards/list`,
  );
  return data;
}

export async function listProjects(): Promise<Project[]> {
  const { data } = await apiClient.get<Project[]>(
    `${API_PREFIX}/projects/get/all`,
  );
  return data;
}

/**
 * Generate a MongoDB-style ObjectId (24 hex chars) client-side, mirroring the
 * Dash create-dashboard flow which generates the id then POSTs to /save/{id}.
 */
function generateObjectId(): string {
  const timestamp = Math.floor(Date.now() / 1000).toString(16).padStart(8, "0");
  const random = Array.from({ length: 16 }, () =>
    Math.floor(Math.random() * 16).toString(16),
  ).join("");
  return (timestamp + random).slice(0, 24);
}

export interface CreateDashboardInput {
  title: string;
  subtitle?: string;
  projectId: string;
}

export async function createDashboard(
  input: CreateDashboardInput,
  user: User,
): Promise<string> {
  const dashboardId = generateObjectId();
  const payload = {
    id: dashboardId,
    dashboard_id: dashboardId,
    title: input.title,
    subtitle: input.subtitle ?? "",
    icon: "mdi:view-dashboard",
    icon_color: "orange",
    icon_variant: "filled",
    workflow_system: "none",
    project_id: input.projectId,
    permissions: {
      owners: [{ id: user.id, email: user.email, is_admin: user.is_admin }],
      editors: [],
      viewers: [],
    },
    version: 1,
    last_saved_ts: new Date().toISOString().replace("T", " ").slice(0, 19),
  };

  await apiClient.post(`${API_PREFIX}/dashboards/save/${dashboardId}`, payload);
  return dashboardId;
}

export async function deleteDashboard(dashboardId: string): Promise<void> {
  await apiClient.delete(`${API_PREFIX}/dashboards/delete/${dashboardId}`);
}
