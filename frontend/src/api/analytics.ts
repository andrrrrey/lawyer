// Хуки сквозной аналитики (TanStack Query).

import { useQuery } from "@tanstack/react-query";

import { api } from "./client";

export interface ChainStep {
  label: string; sub: string; color: string; width: number; glow: boolean;
  display: string; conversion: number | null;
}

export interface RomiTag { display: string; cls: string; value: number | null; }
export interface Action { label: string; cls: string; note: string; }

export interface Campaign {
  name: string; spend: number | null; spend_display: string;
  leads: number; deals: number; payments: number;
  revenue: number; revenue_display: string;
  romi: RomiTag; action: Action;
}
export interface ChannelRow extends Omit<Campaign, "name"> {
  name: string; color: string; campaigns: Campaign[];
}

export interface Reconciliation {
  timezone: string;
  bitrix: {
    leads: number; deals: number; successful_deals: number; successful_amount: number;
  };
  onec: {
    payments: number; revenue: number;
    matched_payments: number; matched_deals: number; matched_revenue: number;
    unmatched_payments: number; unmatched_revenue: number;
    excluded_payments: number; excluded_amount: number;
  };
  difference: number;
  funnels: Array<{
    crm_source: string; funnel_id: string; name: string; deals: number;
    successful_deals: number; successful_amount: number;
  }>;
}

const analyticsParams = (period: string, legalEntities: string[], channel?: string) => {
  const q = new URLSearchParams({ period });
  legalEntities.forEach((value) => q.append("legal_entity", value));
  if (channel && channel !== "all") q.set("channel", channel);
  return q.toString();
};

export const useChain = (period: string, legalEntities: string[]) =>
  useQuery<ChainStep[]>({
    queryKey: ["analytics", "chain", period, legalEntities],
    queryFn: () => api.get(`/analytics/chain?${analyticsParams(period, legalEntities)}`),
  });

export const useReconciliation = (period: string, legalEntities: string[]) =>
  useQuery<Reconciliation>({
    queryKey: ["analytics", "reconciliation", period, legalEntities],
    queryFn: () => api.get(
      `/analytics/reconciliation?${analyticsParams(period, legalEntities)}`,
    ),
  });

export const useChannels = (channel: string, period: string, legalEntities: string[]) =>
  useQuery<ChannelRow[]>({
    queryKey: ["analytics", "channels", channel, period, legalEntities],
    queryFn: () => api.get(
      `/analytics/channels?${analyticsParams(period, legalEntities, channel)}`,
    ),
  });
