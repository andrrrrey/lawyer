// Хуки админ-панели регламента (TanStack Query).

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";

export interface Threshold { n: string; s: string; v: number; u: string; }
export interface TaskRule { n: string; s: string; on: boolean; }
export type ReqField = [string, number];

export interface RegulationConfig {
  thresholds: Threshold[];
  task_rules: TaskRule[];
  req_fields: ReqField[];
  dup_rule: { value: string; options: string[] };
  schedule: {
    days: string[];
    days_on: boolean[];
    work_from: string;
    work_to: string;
    production_calendar: boolean;
    holidays?: string[];
  };
  task_logic: { assignee: string; assignee_options: string[]; template: string };
  evaluative: { highlight_spam: boolean; highlight_refusal: boolean; stuck_days: number };
}

export interface HistoryEntry {
  id: number;
  dt: string;
  user: string;
  param: string;
  from: string;
  to: string;
  crit: boolean;
  can_rollback: boolean;
}

export function useRegulation() {
  return useQuery<RegulationConfig>({
    queryKey: ["admin", "regulation"],
    queryFn: () => api.get("/admin/regulation"),
  });
}

export function useHistory() {
  return useQuery<HistoryEntry[]>({
    queryKey: ["admin", "history"],
    queryFn: () => api.get("/admin/history"),
  });
}

export function useSaveRegulation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (config: RegulationConfig) =>
      api.put<{ changes: number }>("/admin/regulation", config),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin"] });
      qc.invalidateQueries({ queryKey: ["monitor"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

export function useRollback() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.post(`/admin/history/${id}/rollback`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin"] });
      qc.invalidateQueries({ queryKey: ["monitor"] });
    },
  });
}
