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
  revenue: number; revenue_display: string; margin: number; margin_display: string;
  romi: RomiTag; action: Action;
}
export interface ChannelRow extends Omit<Campaign, "name"> {
  name: string; color: string; campaigns: Campaign[];
}

export const useChain = (period: string, legalEntity: string) =>
  useQuery<ChainStep[]>({
    queryKey: ["analytics", "chain", period, legalEntity],
    queryFn: () => api.get(`/analytics/chain?period=${encodeURIComponent(period)}&legal_entity=${encodeURIComponent(legalEntity)}`),
  });

export const useChannels = (channel: string, period: string, legalEntity: string) =>
  useQuery<ChannelRow[]>({
    queryKey: ["analytics", "channels", channel, period, legalEntity],
    queryFn: () =>
      api.get(
        `/analytics/channels?channel=${encodeURIComponent(channel)}` +
          `&period=${encodeURIComponent(period)}` +
          `&legal_entity=${encodeURIComponent(legalEntity)}`,
      ),
  });
