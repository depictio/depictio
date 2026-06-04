import axios, { AxiosError } from "axios";
import { useAuthStore } from "../store/auth";

export const API_PREFIX = "/depictio/api/v1";

export const apiClient = axios.create({
  baseURL: "",
  headers: { "Content-Type": "application/json" },
});

apiClient.interceptors.request.use((config) => {
  const token = useAuthStore.getState().accessToken;
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

apiClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    if (error.response?.status === 401) {
      const { clear } = useAuthStore.getState();
      clear();
    }
    return Promise.reject(error);
  },
);
