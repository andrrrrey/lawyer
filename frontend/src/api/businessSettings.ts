import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";

export interface DdsArticle {
  name: string;
  operation: "income" | "refund" | "exclude";
  enabled: boolean;
  notes: string;
}

export interface LegalEntity {
  key: string;
  name: string;
  inn: string;
  kpp: string;
  enabled: boolean;
  position: number;
  dds_articles: DdsArticle[];
}

export interface CrmSource { key: string; name: string; enabled: boolean }
export interface Funnel {
  key: string;
  external_id: string;
  name: string;
  crm_source: string;
  legal_entity_key: string;
  sla_profile_key: string;
  enabled: boolean;
}
export interface Department { key: string; name: string; enabled: boolean }
export interface Employee {
  key: string;
  name: string;
  crm_source: string;
  bitrix_user_id: string;
  legal_entity_key: string;
  department_key: string;
  enabled: boolean;
}
export interface Plan {
  key: string;
  employee_key: string;
  legal_entity_key: string;
  period: string;
  revenue: number;
  payments: number;
  deals: number;
}
export interface SlaRule {
  source_number: number;
  key: string;
  name: string;
  description: string;
  minutes?: number;
  days?: number;
  schedule?: { day: number; action: string }[];
  enabled: boolean;
}
export interface SlaProfile { key: string; name: string; enabled: boolean; rules: SlaRule[] }

export interface BusinessSettings {
  schema_version: number;
  legal_entities: LegalEntity[];
  crm_sources: CrmSource[];
  funnels: Funnel[];
  departments: Department[];
  employees: Employee[];
  plans: Plan[];
  sla_profiles: SlaProfile[];
}

export function useBusinessSettings() {
  return useQuery<BusinessSettings>({
    queryKey: ["admin", "business-settings"],
    queryFn: () => api.get("/admin/business-settings"),
  });
}

export interface BitrixFunnelOption {
  id: string;
  name: string;
  is_default: boolean;
  sort: number;
}

export interface BitrixFunnelSource {
  key: string;
  name: string;
  configured: boolean;
  ok: boolean;
  error?: string;
  funnels: BitrixFunnelOption[];
}

export function useBitrixFunnels() {
  return useQuery<{ sources: BitrixFunnelSource[] }>({
    queryKey: ["integrations", "bitrix", "funnels"],
    queryFn: () => api.get("/integrations/bitrix/funnels"),
    staleTime: 60_000,
  });
}

export function useSaveBusinessSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: BusinessSettings) =>
      api.put<BusinessSettings>("/admin/business-settings", payload),
    onSuccess: (data) => {
      qc.setQueryData(["admin", "business-settings"], data);
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      qc.invalidateQueries({ queryKey: ["monitor"] });
    },
  });
}

export interface OneCReceiptJournalRow {
  id: number;
  date: string | null;
  number: string;
  legal_entity_key: string;
  organization: string;
  counterparty: string;
  article: string;
  operation: string;
  amount: number;
  crm_external_id: string;
  matched: boolean;
  excluded: boolean;
  reason: string;
}

export function useOneCReceiptJournal() {
  return useQuery<OneCReceiptJournalRow[]>({
    queryKey: ["admin", "one-c", "receipts"],
    queryFn: () => api.get("/admin/one-c/receipts"),
  });
}
