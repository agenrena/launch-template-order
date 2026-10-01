import { QueryClient, useQuery } from "@tanstack/react-query";
export const client = new QueryClient({
  defaultOptions: { queries: { retry: false, staleTime: 15000 } },
});
let csrf = "";
export async function api<T>(
  path: string,
  method = "GET",
  data?: unknown,
): Promise<T> {
  const response = await fetch(`/api/console/${path}`, {
    method,
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
    body: data === undefined ? undefined : JSON.stringify(data),
  });
  const body =
    response.status === 204 ? {} : await response.json().catch(() => ({}));
  if (body.csrf_token) csrf = body.csrf_token;
  if (!response.ok) {
    if (response.status === 403 || response.status === 401)
      void client.invalidateQueries({ queryKey: ["session/"] });
    throw new Error(
      body.details
        ? typeof body.details === "string"
          ? body.details
          : JSON.stringify(body.details)
        : `請求失敗 (${response.status})`,
    );
  }
  return body as T;
}
export function useData<T>(path: string, enabled = true) {
  return useQuery({ queryKey: [path], queryFn: () => api<T>(path), enabled });
}
export async function change<T>(path: string, method: string, data?: unknown) {
  const result = await api<T>(path, method, data);
  await client.invalidateQueries();
  return result;
}
export interface User {
  id: number;
  username: string;
  name: string;
  role: "owner" | "admin";
  is_active: boolean;
  permissions: string[];
}
export interface Business {
  software_name: string;
  name: string;
  about: string;
  address: string;
  phone: string;
  timezone: string;
}
export interface Page<T> {
  results: T[];
  page: number;
  pages: number;
  count: number;
}
export interface AgentRole {
  code: string;
  label: string;
  permissions: { code: string; label: string; scope: string }[];
}
export interface AgentKey {
  id: string;
  label: string;
  role_id: string;
  prefix: string;
  revoked_at: string | null;
  created_at: string;
}
export type McpInfo =
  | { transport: "http"; url: string }
  | {
      transport: "stdio";
      name: string;
      command: string;
      args: string[];
      env: Record<string, string>;
      key_env: string;
    };
export interface AgenrenaState {
  configured: boolean;
  status: "none" | "pending" | "connected" | "revoked" | "expired";
  business_name?: string;
  connected_at?: string | null;
  expires_at?: string;
}
export interface Audit {
  id: string;
  created_at: string;
  actor_type: string;
  actor_label: string;
  action: string;
  target_type: string;
  target_id: string;
  customer_id: string | null;
  detail: { fields?: string[]; role?: string; error?: string };
}
