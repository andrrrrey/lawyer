import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";

export type UserRole = "owner" | "head" | "manager";

export interface AppUserRow {
  id: number;
  login: string;
  role: UserRole;
  employee_key: string;
  department_key: string;
  enabled: boolean;
}

export type AppUserPayload = Omit<AppUserRow, "id"> & { password: string };

export const useUsers = () => useQuery<AppUserRow[]>({
  queryKey: ["admin", "users"], queryFn: () => api.get("/admin/users"),
});

export function useSaveUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, payload }: { id?: number; payload: AppUserPayload }) =>
      id ? api.put<AppUserRow>(`/admin/users/${id}`, payload) : api.post<AppUserRow>("/admin/users", payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "users"] }),
  });
}

export function useDeleteUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.delete<{ ok: boolean }>(`/admin/users/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "users"] }),
  });
}
