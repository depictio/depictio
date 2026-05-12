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
