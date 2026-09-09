// Хуки страницы настроек интеграций (TanStack Query).

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";

export type DataSource = "mock" | "real";

export interface IntegrationField {
  key: string;
  label: string;
  hint: string;
  secret: boolean;
  placeholder: string;
  filled: boolean;
  value: string; // для секретов — маска; для остального — само значение
}

export interface IntegrationProvider {
  key: string;
  name: string;
  subtitle: string;
  docs: string;
  configured: boolean;
  last_check?: CheckResult | null;
  fields: IntegrationField[];
}

export interface FieldTarget { key: string; label: string; hint: string; }
export interface FieldMap { fields: Record<string, string>; required: string[]; }
export interface BitrixField { code: string; title: string; }
export interface BitrixStage { id: string; name: string; }
export interface BitrixSchema {
  ok: boolean;
  error?: string;
  fields: BitrixField[];
  stages: BitrixStage[];
}

export interface IntegrationsConfig {
  data_source: DataSource;
  ai_configured: boolean;
  providers: IntegrationProvider[];
  yandex: YandexConfig;
  field_map: FieldMap;
  field_targets: FieldTarget[];
}

export interface YandexCredential {
  id: string;
  name: string;
  login: string;
  token: string;
  token_filled?: boolean;
  enabled: boolean;
}

export interface YandexDirectAccount {
  id: string;
  name: string;
  credential_id: string;
  client_login: string;
  legal_entity_key: string;
  enabled: boolean;
}

export interface YandexMetrikaCounter {
  id: string;
  name: string;
  credential_id: string;
  counter_id: string;
  site: string;
  legal_entity_key: string;
  enabled: boolean;
}

export interface YandexConfig {
  client_id: string;
  credentials: YandexCredential[];
  direct_accounts: YandexDirectAccount[];
  metrika_counters: YandexMetrikaCounter[];
  last_checks: Record<string, CheckResult>;
}

export interface YandexCountersResult {
  ok: boolean;
  error?: string;
  counters: Array<{
    counter_id: string;
    name: string;
    site: string;
    owner_login: string;
    permission: string;
  }>;
}

export type RecomputeState = "idle" | "running" | "done" | "error";

export interface RecomputeSource {
  status: string; // ok | error | skipped
  count?: number;
  message?: string;
  label?: string;
  retained_previous?: boolean;
}

export interface RecomputeStatus {
  state: RecomputeState;
  step: string;
  started_at: string | null;
  finished_at: string | null;
  mode: DataSource | null;
  error: string | null;
  sources: Record<string, RecomputeSource>;
  stats: Record<string, unknown>;
}

export interface AiGenerateResult {
  generated: boolean;
  count?: number;
  insights?: number;
  budget_recs?: number;
  deal_comments?: number;
  reason?: string;
}

export type CheckStatus = "ok" | "error" | "not_configured";

export interface CheckResult {
  provider: string;
  status: CheckStatus;
  message: string;
  detail: string;
  checked_at: string;
}

export interface SavePayload {
  values?: Record<string, string>;
  clear?: string[];
  data_source?: DataSource;
}

export function useIntegrations() {
  return useQuery<IntegrationsConfig>({
    queryKey: ["integrations"],
    queryFn: () => api.get("/integrations"),
  });
}

// Лёгкий запрос текущего источника данных (для плашки режима в топбаре).
export function useDataSource(enabled = true) {
  return useQuery<{ data_source: DataSource }>({
    queryKey: ["integrations", "data-source"],
    queryFn: () => api.get("/integrations/data-source"),
    staleTime: 30_000,
    enabled,
  });
}

export function useSaveIntegrations() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: SavePayload) => api.put<IntegrationsConfig>("/integrations", payload),
    onSuccess: (data) => {
      qc.setQueryData(["integrations"], data);
      qc.setQueryData(["integrations", "data-source"], { data_source: data.data_source });
    },
  });
}

export function useCheckIntegration() {
  return useMutation({
    mutationFn: (provider: string) => api.post<CheckResult>(`/integrations/${provider}/check`),
  });
}

export function useCheckAll() {
  return useMutation({
    mutationFn: () => api.post<Record<string, CheckResult>>("/integrations/check"),
  });
}

// Запуск фонового пересчёта (возвращает начальный статус running).
export function useStartRecompute() {
  return useMutation({
    mutationFn: () => api.post<RecomputeStatus>("/integrations/recompute"),
  });
}

// Опрос статуса пересчёта; сам опрашивает, пока идёт работа.
export function useRecomputeStatus() {
  return useQuery<RecomputeStatus>({
    queryKey: ["integrations", "recompute", "status"],
    queryFn: () => api.get("/integrations/recompute/status"),
    refetchInterval: (q) => (q.state.data?.state === "running" ? 1500 : false),
  });
}

export function useSaveYandex() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: YandexConfig) => api.put<YandexConfig>("/integrations/yandex", payload),
    onSuccess: (data) => {
      qc.setQueryData<IntegrationsConfig | undefined>(["integrations"], (prev) =>
        prev ? { ...prev, yandex: data } : prev,
      );
    },
  });
}

export function useCheckYandex() {
  return useMutation({
    mutationFn: () =>
      api.post<{ results: Record<string, CheckResult> }>("/integrations/yandex/check"),
  });
}

export function useDiscoverYandexCounters() {
  return useMutation({
    mutationFn: (credentialId: string) =>
      api.post<YandexCountersResult>(`/integrations/yandex/credentials/${credentialId}/counters`),
  });
}

export function useStartYandexSync() {
  return useMutation({
    mutationFn: () => api.post<RecomputeStatus>("/integrations/yandex/sync"),
  });
}

export function useYandexSyncStatus() {
  return useQuery<RecomputeStatus>({
    queryKey: ["integrations", "yandex", "sync", "status"],
    queryFn: () => api.get("/integrations/yandex/sync/status"),
    refetchInterval: (q) => (q.state.data?.state === "running" ? 1500 : false),
  });
}

// Живая схема воронки Битрикс24 (поля сделки + стадии) — по кнопке.
export function useBitrixSchema() {
  return useMutation({
    mutationFn: () => api.get<BitrixSchema>("/integrations/bitrix/schema"),
  });
}

export interface MpdbColumn { name: string; type: string; }
export interface MpdbTable { schema: string; table: string; columns: MpdbColumn[]; }
export interface MpdbSchema { ok: boolean; error?: string; tables: MpdbTable[]; }

// Структура Postgres-реплики МойСклад (mpdb): таблицы и колонки — по кнопке.
export function useMoyskladSchema() {
  return useMutation({
    mutationFn: () => api.get<MpdbSchema>("/integrations/moysklad/schema"),
  });
}

// Сохранение сопоставления пользовательских полей Битрикс24.
export function useSaveFieldMap() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (p: FieldMap) => api.put<FieldMap>("/integrations/field-map", p),
    onSuccess: (data) => {
      qc.setQueryData<IntegrationsConfig | undefined>(["integrations"], (prev) =>
        prev ? { ...prev, field_map: data } : prev,
      );
    },
  });
}

// Ручной запуск генерации AI-инсайтов.
export function useGenerateAi() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<AiGenerateResult>("/integrations/ai/generate"),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["ai"] });
    },
  });
}
