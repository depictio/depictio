import { apiClient, API_PREFIX } from "./client";
import type { LoginResponse, User } from "./types";

export async function login(
  email: string,
  password: string,
): Promise<LoginResponse> {
  const form = new URLSearchParams();
  form.set("username", email);
  form.set("password", password);

  const { data } = await apiClient.post<LoginResponse>(
    `${API_PREFIX}/auth/login`,
    form,
    { headers: { "Content-Type": "application/x-www-form-urlencoded" } },
  );
  return data;
}

export async function fetchMe(): Promise<User> {
  const { data } = await apiClient.get<User>(`${API_PREFIX}/auth/me`);
  return data;
}

export interface RegisterResult {
  success: boolean;
  message: string;
}

export async function register(
  email: string,
  password: string,
): Promise<RegisterResult> {
  // The backend returns HTTP 200 with { success: false, message } for
  // duplicate users, so callers must inspect `success`, not just the status.
  const { data } = await apiClient.post<RegisterResult>(
    `${API_PREFIX}/auth/register`,
    { email, password, is_admin: false },
  );
  return data;
}
