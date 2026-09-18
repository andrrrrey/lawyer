// Хуки мониторинга Битрикс24 (TanStack Query).

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";

export interface MonStat {
  n: string;
  label: string;
  cls: string;
  // Идентификатор фильтра списка нарушений (?sev=key). Пустой/нет — плашка некликабельна.
  key?: string;
}
export interface MonStatsResponse {
  stats: MonStat[];
  badge: number;
}

export interface Violation {
  severity: "over" | "warn" | "review";
  ptype: string;
  kind_label: string;
  kind_class: string;
  name: string;
  ref: string;
  deal_key: string;
  mgr: string;
  src: string;
  norm: string;
  sla: string;
  over: boolean;
  amount: number;
  amount_display: string;
  ai: string;
  violation_at: string | null;
}

export interface MonitorScope {
  legalEntities: string[];
  funnels: string[];
}

const scopeParams = (scope: MonitorScope) => {
  const params = new URLSearchParams();
  scope.legalEntities.forEach((value) => params.append("legal_entity", value));
  scope.funnels.forEach((value) => params.append("funnel", value));
  return params;
};

export function useMonitorStats(scope?: MonitorScope) {
  const activeScope = scope ?? { legalEntities: [], funnels: [] };
  const params = scopeParams(activeScope);
  const query = params.toString();
  return useQuery<MonStatsResponse>({
    queryKey: ["monitor", "stats", activeScope.legalEntities, activeScope.funnels],
    queryFn: () => api.get(`/monitor/stats${query ? `?${query}` : ""}`),
  });
}

export interface ViolationFilters {
  ptype?: string | null;
  dateFrom?: string | null;
  dateTo?: string | null;
  legalEntities: string[];
  funnels: string[];
}

export function useViolations({
  ptype, dateFrom, dateTo, legalEntities, funnels,
}: ViolationFilters) {
  const params = scopeParams({ legalEntities, funnels });
  if (ptype) params.set("ptype", ptype);
  if (dateFrom) params.set("date_from", dateFrom);
  if (dateTo) params.set("date_to", dateTo);
  const query = params.toString();
  return useQuery<Violation[]>({
    queryKey: ["monitor", "violations", ptype, dateFrom, dateTo, legalEntities, funnels],
    queryFn: () => api.get(`/monitor/violations${query ? `?${query}` : ""}`),
  });
}

export function useReview(scope: MonitorScope) {
  const params = scopeParams(scope);
  const query = params.toString();
  return useQuery<Violation[]>({
    queryKey: ["monitor", "review", scope.legalEntities, scope.funnels],
    queryFn: () => api.get(`/monitor/review${query ? `?${query}` : ""}`),
  });
}

export interface CreatedTask {
  assignee: string;
  title: string;
  due: string;
  // ID задачи и «дела» в Битрикс24; mock=true — демо-режим, в портал ничего не ушло.
  external_id: string | null;
  activity_id: string | null;
  mock: boolean;
}

export function useCreateTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (dealKey: string) =>
      api.post<CreatedTask>("/monitor/task", { deal_key: dealKey }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["monitor"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}
