// Хуки дашборда (TanStack Query).

import { useQuery } from "@tanstack/react-query";

import { api } from "./client";

export interface Kpi {
  key: string;
  label: string;
  icon: string;
  svg: string;
  kind: string;
  value: number | null;
  display: string;
  trend: "up" | "down" | "warn";
  delta: string;
  spark: number[];
  drill: string | null;
  period_label: string;
}

export interface AttentionTile {
  n: number;
  label: string;
  sub: string;
  cls: string;
  icon: string;
  drill: string;
}
export interface Attention {
  money_at_risk: number;
  money_at_risk_display: string;
  risk_leads: number;
  tiles: AttentionTile[];
}

export interface FunnelStage { label: string; value: number; }
export interface Source { name: string; short_name: string; color: string; leads: number; }
export interface RevenueSeries { days: string[]; revenue: number[]; margin: number[]; }
export interface RomiByChannel { name: string; short_name: string; romi: number; }

export interface Manager {
  name: string; inwork: number; overdue: number; notask: number; fc: string;
  invoices: number; payments: number; paysum: number; paysum_display: string;
  zone_label: string; zone_class: string;
}

export interface Lead {
  name: string; src: string; mgr: string; status_label: string; status_class: string;
  fc: string; call: boolean; inv: boolean; pay: boolean; amount: number; amount_display: string;
  risk: string | null; tags: string[]; ai: string; reason: string;
  legal_entity_key: string;
}

// Фильтры панели дашборда: период + менеджер + источник. Витрины принимают их
// целиком — иначе выпадающие списки не влияли ни на что, кроме таблицы лидов.
export interface DashFilters {
  period: string;
  mgr: string;
  source: string;
  legalEntity: string;
}

const qs = (f: DashFilters) => {
  const q = new URLSearchParams({ period: f.period });
  if (f.mgr && f.mgr !== "all") q.set("mgr", f.mgr);
  if (f.source && f.source !== "all") q.set("source", f.source);
  if (f.legalEntity && f.legalEntity !== "all") q.set("legal_entity", f.legalEntity);
  return `?${q.toString()}`;
};

// Ключ кэша запроса: меняется вместе с любым из фильтров.
const key = (f: DashFilters) => [f.period, f.legalEntity, f.mgr, f.source];

export interface FilterOptions {
  managers: string[];
  channels: string[];
  sources: string[];
  legal_entities: { value: string; label: string }[];
}

export const useFilterOptions = () =>
  useQuery<FilterOptions>({
    queryKey: ["dashboard", "filters"],
    queryFn: () => api.get("/dashboard/filters"),
    staleTime: 60_000,
  });

export const useKpis = (f: DashFilters) =>
  useQuery<Kpi[]>({ queryKey: ["dashboard", "kpis", ...key(f)], queryFn: () => api.get(`/dashboard/kpis${qs(f)}`) });

export const useAttention = (f: DashFilters) =>
  useQuery<Attention>({
    queryKey: ["dashboard", "attention", f.legalEntity, f.mgr, f.source],
    // Триаж показывает состояние «сейчас» — период к нему не применяется,
    // но менеджер и источник сужают выборку.
    queryFn: () => {
      const q = new URLSearchParams();
      if (f.mgr && f.mgr !== "all") q.set("mgr", f.mgr);
      if (f.source && f.source !== "all") q.set("source", f.source);
      if (f.legalEntity && f.legalEntity !== "all") q.set("legal_entity", f.legalEntity);
      const s = q.toString();
      return api.get(`/dashboard/attention${s ? `?${s}` : ""}`);
    },
  });

export const useFunnel = (f: DashFilters) =>
  useQuery<FunnelStage[]>({ queryKey: ["dashboard", "funnel", ...key(f)], queryFn: () => api.get(`/dashboard/funnel${qs(f)}`) });

export const useSources = (f: DashFilters) =>
  useQuery<Source[]>({ queryKey: ["dashboard", "sources", ...key(f)], queryFn: () => api.get(`/dashboard/sources${qs(f)}`) });

export const useRevenueSeries = (f: DashFilters) =>
  useQuery<RevenueSeries>({ queryKey: ["dashboard", "revenue", ...key(f)], queryFn: () => api.get(`/dashboard/revenue-series${qs(f)}`) });

export const useRomiByChannel = (f: DashFilters) =>
  useQuery<RomiByChannel[]>({ queryKey: ["dashboard", "romi-by-channel", ...key(f)], queryFn: () => api.get(`/dashboard/romi-by-channel${qs(f)}`) });

export const useManagers = (f: DashFilters) =>
  useQuery<Manager[]>({ queryKey: ["dashboard", "managers", ...key(f)], queryFn: () => api.get(`/dashboard/managers${qs(f)}`) });

export const useLeads = (
  mgr: string,
  source: string,
  risk: string | null,
  period: string,
  legalEntity: string,
) =>
  useQuery<Lead[]>({
    queryKey: ["dashboard", "leads", legalEntity, mgr, source, risk, period],
    queryFn: () => {
      const q = new URLSearchParams();
      if (mgr && mgr !== "all") q.set("mgr", mgr);
      if (source && source !== "all") q.set("source", source);
      if (legalEntity && legalEntity !== "all") q.set("legal_entity", legalEntity);
      if (risk) q.set("risk", risk);
      if (period) q.set("period", period);
      const qs = q.toString();
      return api.get(`/dashboard/leads${qs ? `?${qs}` : ""}`);
    },
  });
