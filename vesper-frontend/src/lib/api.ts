import axios from "axios";

export const api = axios.create({ baseURL: "/api", withCredentials: true });

let refreshing: Promise<void> | null = null;

api.interceptors.response.use(
  (r) => r,
  async (error) => {
    const original = error.config;
    if (original?.url?.includes("/auth/refresh")) {
      return Promise.reject(error);
    }
    if (error.response?.status === 401 && !original._retry) {
      original._retry = true;
      refreshing ??= api
        .post("/auth/refresh")
        .then(() => undefined)
        .finally(() => {
          refreshing = null;
        });
      await refreshing;
      return api(original);
    }
    return Promise.reject(error);
  },
);
