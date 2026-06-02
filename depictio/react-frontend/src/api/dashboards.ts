import { apiClient, API_PREFIX } from "./client";
import type { Dashboard } from "./types";

export async function listDashboards(): Promise<Dashboard[]> {
  const { data } = await apiClient.get<Dashboard[]>(
    `${API_PREFIX}/dashboards/list`,
  );
  return data;
}
