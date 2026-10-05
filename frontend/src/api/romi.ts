// Хуки ROMI и рекомендаций (TanStack Query).

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";

export interface RomiChannelChart {
  name: string; short_name: string; spend: number | null; revenue: number; color: string;
}
export interface CampaignBubble {
  name: string; spend: number | null; romi: number | null; revenue: number; color: string;
}
export interface BudgetRec {
  id: number;
  ic: string; svg: string; title: string; tag_label: string; tag_class: string;
  text: string; why: string; impact: string; src: string[]; conf: string; dep: boolean;
  status: "new" | "accepted" | "deferred"; deferred_until?: string | null;
}
export interface MinusWord {
  id: number;
  phrase: string; camp: string; level: string; shows: number; clicks: number;
  spend: number; spend_display: string; conv: number; deals: number;
  reason: string; conf: string; status: string;
}
export interface MinusWords {
  summary: { count: number; spend: number; spend_display: string; camps: number };
  items: MinusWord[];
}

const qs = (period: string, legalEntity: string) => {
  const q = new URLSearchParams({ period });
  if (legalEntity && legalEntity !== "all") q.set("legal_entity", legalEntity);
  return q.toString();
};

export const useRomiChannels = (period: string, legalEntity: string) =>
  useQuery<RomiChannelChart[]>({ queryKey: ["romi", "by-channel", period, legalEntity], queryFn: () => api.get(`/romi/by-channel?${qs(period, legalEntity)}`) });

export const useCampaignsBubble = (period: string, legalEntity: string) =>
  useQuery<CampaignBubble[]>({ queryKey: ["romi", "campaigns", period, legalEntity], queryFn: () => api.get(`/romi/campaigns?${qs(period, legalEntity)}`) });

export const useBudgetRecs = (period: string, legalEntity: string) =>
  useQuery<BudgetRec[]>({ queryKey: ["romi", "budget-recs", period, legalEntity], queryFn: () => api.get(`/romi/budget-recs?${qs(period, legalEntity)}`) });

export const useMinusWords = (period: string, legalEntity: string) =>
  useQuery<MinusWords>({ queryKey: ["romi", "minus-words", period, legalEntity], queryFn: () => api.get(`/romi/minus-words?${qs(period, legalEntity)}`) });

export const useBudgetRecAction = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, status }: { id: number; status: "accepted" | "deferred" | "new" }) =>
      api.patch(`/romi/budget-recs/${id}`, { status }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["romi", "budget-recs"] }),
  });
};

export const useMinusWordAction = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, status }: { id: number; status: string }) =>
      api.patch(`/romi/minus-words/${id}`, { status }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["romi", "minus-words"] }),
  });
};
