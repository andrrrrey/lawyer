import { useQueryClient } from "@tanstack/react-query";
import { App, Button, Input, Segmented, Spin } from "antd";
import { useEffect, useMemo, useRef, useState } from "react";

import { FieldMapSection } from "@/components/FieldMapSection";
import {
  type CheckResult,
  type CheckStatus,
  type DataSource,
  type IntegrationField,
  type IntegrationProvider,
  type IntegrationsConfig,
  type RecomputeStatus,
  useCheckAll,
  useCheckIntegration,
  useGenerateAi,
  useIntegrations,
  useRecomputeStatus,
  useSaveIntegrations,
  useStartRecompute,
} from "@/api/integrations";

const PROVIDER_NAMES: Record<string, string> = {
  bitrix: "Bitrix24",
  bitrix_box: "Bitrix24 · коробка",
  bitrix_cloud: "Bitrix24 · облако",
  yandex_direct: "Яндекс Директ",
  yandex_metrika: "Яндекс Метрика",
  yandex_direct_uo: "Директ · ЮО",
  yandex_direct_csv: "Директ · ЦСВ",
  yandex_direct_urpase: "Директ · УрПАСЭ",
  yandex_metrika_uo: "Метрика · ЮО",
  yandex_metrika_csv: "Метрика · ЦСВ",
  yandex_metrika_urpase: "Метрика · УрПАСЭ",
  onec: "1С:УНФ",
  demo: "Демо-данные",
};

function SourcesSummary({ sources }: { sources: RecomputeStatus["sources"] }) {
  const entries = Object.entries(sources ?? {});
  if (entries.length === 0) return null;
  // Причины ошибок показываем отдельной строкой (не только в подсказке при наведении).
  const errors = entries.filter(([, s]) => s.status === "error" && s.message);
  return (
    <>
      <div className="intg-src-summary">
        {entries.map(([key, s]) => {
          const cls = s.status === "ok" ? "ok" : s.status === "error" ? "err" : "idle";
          const label =
            s.status === "ok"
              ? `${PROVIDER_NAMES[key] ?? key}: ${s.count ?? "готово"}`
              : s.status === "skipped"
                ? `${PROVIDER_NAMES[key] ?? key}: не настроен`
                : `${PROVIDER_NAMES[key] ?? key}: ошибка`;
          return (
            <span key={key} className={`intg-src-chip ${cls}`} title={s.message ?? ""}>
              {label}
            </span>
          );
        })}
      </div>
      {errors.length > 0 ? (
        <div className="intg-src-errors">
          {errors.map(([key, s]) => (
            <div key={key} className="intg-src-error">
              <b>{PROVIDER_NAMES[key] ?? key}:</b> {s.message}
            </div>
          ))}
        </div>
      ) : null}
    </>
  );
}

/* --- Значок статуса подключения --- */
function statusMeta(
  provider: IntegrationProvider,
  check?: CheckResult,
): { cls: string; text: string } {
  if (check) {
    if (check.status === "ok") return { cls: "ok", text: "Подключено" };
    if (check.status === "not_configured") return { cls: "idle", text: "Не заполнено" };
    return { cls: "err", text: "Ошибка" };
  }
  if (!provider.configured) return { cls: "idle", text: "Не заполнено" };
  return { cls: "warn", text: "Не проверено" };
}

function StatusBadge({ cls, text }: { cls: string; text: string }) {
  return (
    <span className={`intg-badge ${cls}`}>
      <span className="dot" />
      {text}
    </span>
  );
}

/* --- Поле ввода одного креда --- */
function FieldInput({
  field,
  value,
  onChange,
}: {
  field: IntegrationField;
  value: string;
  onChange: (v: string) => void;
}) {
  const placeholder = field.placeholder || "Не задано";

  return (
    <div className="field intg-field">
      <label>{field.label}</label>
      {field.secret ? (
        <Input.Password
          value={value}
          placeholder={placeholder}
          autoComplete="new-password"
          onChange={(e) => onChange(e.target.value)}
        />
      ) : (
        <Input value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} />
      )}
      {field.hint ? <span className="intg-hint">{field.hint}</span> : null}
    </div>
  );
}

/* --- Инициализация черновика из конфигурации (поля предзаполнены реальными
   значениями — их видно и можно редактировать) --- */
function initialDraft(cfg: IntegrationsConfig): Record<string, string> {
  const d: Record<string, string> = {};
  for (const p of cfg.providers) {
    for (const f of p.fields) d[f.key] = f.value;
  }
  return d;
}

export default function IntegrationsPage() {
  const q = useIntegrations();
  const save = useSaveIntegrations();
  const checkOne = useCheckIntegration();
  const checkAll = useCheckAll();
  const { message } = App.useApp();

  const startRecompute = useStartRecompute();
  const recomputeStatus = useRecomputeStatus();
  const generateAi = useGenerateAi();
  const qc = useQueryClient();

  const [draft, setDraft] = useState<Record<string, string>>({});
  const [dataSource, setDataSource] = useState<DataSource>("mock");
  const [checks, setChecks] = useState<Record<string, CheckResult>>({});
  const [busy, setBusy] = useState<Record<string, boolean>>({});

  useEffect(() => {
    if (q.data) {
      setDraft(initialDraft(q.data));
      setDataSource(q.data.data_source);
      // Восстанавливаем сохранённые результаты проверок (переживают перезагрузку).
      const saved: Record<string, CheckResult> = {};
      for (const p of q.data.providers) {
        if (p.last_check) saved[p.key] = p.last_check;
      }
      setChecks((prev) => ({ ...saved, ...prev }));
    }
  }, [q.data]);

  // Когда фоновый пересчёт завершился — обновляем витрины дашборда и сообщаем.
  const prevState = useRef<string | undefined>(undefined);
  useEffect(() => {
    const st = recomputeStatus.data?.state;
    if (prevState.current === "running" && st && st !== "running") {
      if (st === "done") {
        for (const key of ["dashboard", "monitor", "analytics", "romi", "ai"]) {
          qc.invalidateQueries({ queryKey: [key] });
        }
        message.success("Пересчёт завершён, дашборд обновлён");
      } else if (st === "error") {
        message.error(`Пересчёт: ${recomputeStatus.data?.error ?? "ошибка"}`);
      }
    }
    prevState.current = st;
  }, [recomputeStatus.data?.state, recomputeStatus.data?.error, qc, message]);

  const cfg = q.data;

  const dirty = useMemo(() => {
    if (!cfg) return false;
    if (dataSource !== cfg.data_source) return true;
    for (const p of cfg.providers) {
      for (const f of p.fields) {
        if ((draft[f.key] ?? "") !== f.value) return true;
      }
    }
    return false;
  }, [cfg, draft, dataSource]);

  if (!cfg) {
    return (
      <div style={{ minHeight: "40vh", display: "grid", placeItems: "center" }}>
        <Spin size="large" />
      </div>
    );
  }

  const setField = (key: string, v: string) => setDraft((d) => ({ ...d, [key]: v }));

  const buildValues = (): Record<string, string> => {
    const values: Record<string, string> = {};
    for (const p of cfg.providers) {
      for (const f of p.fields) {
        const cur = draft[f.key] ?? "";
        // Присылаем только изменённые поля; пустая строка очищает значение.
        if (cur !== f.value) values[f.key] = cur;
      }
    }
    return values;
  };

  const onSave = async () => {
    try {
      await save.mutateAsync({
        values: buildValues(),
        data_source: dataSource,
      });
      message.success("Настройки интеграций сохранены");
    } catch (e) {
      message.error((e as Error).message);
    }
  };

  const applyCheck = (res: CheckResult) => {
    setChecks((c) => ({ ...c, [res.provider]: res }));
    return res;
  };

  const onCheckOne = async (provider: string) => {
    setBusy((b) => ({ ...b, [provider]: true }));
    try {
      const res = await checkOne.mutateAsync(provider);
      applyCheck(res);
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setBusy((b) => ({ ...b, [provider]: false }));
    }
  };

  const onCheckAll = async () => {
    try {
      const res = await checkAll.mutateAsync();
      setChecks(res);
    } catch (e) {
      message.error((e as Error).message);
    }
  };

  const onRecompute = async () => {
    try {
      await startRecompute.mutateAsync();
      await recomputeStatus.refetch();
    } catch (e) {
      message.error((e as Error).message);
    }
  };

  const onGenerateAi = async () => {
    try {
      const res = await generateAi.mutateAsync();
      if (res.generated) {
        message.success(
          `AI-советы обновлены · инсайтов: ${res.insights ?? 0}, рекомендаций по бюджету: ${res.budget_recs ?? 0}`,
        );
      } else {
        message.warning("AI-интеграция не подключена — генерация пропущена");
      }
    } catch (e) {
      message.error((e as Error).message);
    }
  };

  return (
    <>
      {/* Источник данных */}
      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-h">
          <h3>Источник данных</h3>
          <span className="sub">чем наполнять систему</span>
        </div>
        <div className="card-p intg-source">
          <Segmented
            value={dataSource}
            onChange={(v) => setDataSource(v as DataSource)}
            options={[
              { label: "Демо-данные", value: "mock" },
              { label: "Боевые интеграции", value: "real" },
            ]}
          />
          <p className="intg-source-note">
            {dataSource === "mock"
              ? "Система работает на демонстрационных данных прототипа. Доступы ниже можно заполнить заранее."
              : "Система использует боевые интеграции. Заполните и проверьте доступы ниже — иначе выгрузка данных завершится ошибкой."}
          </p>
        </div>
      </div>

      {/* Обслуживание данных: ручной пересчёт и генерация AI */}
      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-h">
          <h3>Обслуживание данных</h3>
          <span className="sub">ручной пересчёт и генерация AI</span>
        </div>
        <div className="card-p">
          <div className="intg-maint">
            <div className="intg-maint-row">
              <div className="st">
                <b>Пересчитать данные и обновить дашборд</b>
                <span>
                  {cfg.data_source === "real"
                    ? "Выгружает настроенные источники и пересобирает витрины по боевым интеграциям."
                    : "Пересобирает демонстрационные данные для согласованного отображения."}
                </span>
                {recomputeStatus.data && recomputeStatus.data.state !== "idle" ? (
                  <div className={`intg-progress ${recomputeStatus.data.state}`}>
                    <div className="intg-progress-head">
                      {recomputeStatus.data.state === "running" ? <Spin size="small" /> : null}
                      <span>
                        {recomputeStatus.data.state === "running"
                          ? recomputeStatus.data.step || "Идёт пересчёт…"
                          : recomputeStatus.data.state === "done"
                            ? "Пересчёт завершён"
                            : `Ошибка: ${recomputeStatus.data.error ?? "неизвестно"}`}
                      </span>
                    </div>
                    {recomputeStatus.data.state !== "running" ? (
                      <SourcesSummary sources={recomputeStatus.data.sources} />
                    ) : null}
                  </div>
                ) : null}
              </div>
              <Button
                onClick={onRecompute}
                loading={startRecompute.isPending || recomputeStatus.data?.state === "running"}
                disabled={recomputeStatus.data?.state === "running"}
              >
                Пересчитать
              </Button>
            </div>
            <div className="intg-maint-row">
              <div className="st">
                <b>Сгенерировать AI-советы и отчёты</b>
                <span>
                  {cfg.ai_configured
                    ? "Запускает генерацию инсайтов и рекомендаций по бюджету (раздел ROMI) через подключённую AI-интеграцию."
                    : "Недоступно: подключите AI-интеграцию (API-ключ и Base URL LLM) ниже."}
                </span>
              </div>
              <Button
                onClick={onGenerateAi}
                loading={generateAi.isPending}
                disabled={!cfg.ai_configured}
              >
                Сгенерировать AI
              </Button>
            </div>
          </div>
        </div>
      </div>

      {/* Карточки интеграций */}
      <div className="grid intg-grid">
        {cfg.providers.map((p) => {
          const check = checks[p.key];
          const meta = statusMeta(p, check);
          return (
            <div className="card intg-card" key={p.key}>
              <div className="card-h">
                <div>
                  <h3>{p.name}</h3>
                  <span className="sub">{p.subtitle}</span>
                </div>
                <StatusBadge cls={meta.cls} text={meta.text} />
              </div>
              <div className="card-p">
                {p.fields.map((f) => (
                  <FieldInput
                    key={f.key}
                    field={f}
                    value={draft[f.key] ?? ""}
                    onChange={(v) => setField(f.key, v)}
                  />
                ))}

                <div className="intg-docs">{p.docs}</div>

                {check ? (
                  <div className={`intg-result ${resultCls(check.status)}`}>
                    <b>{check.message}</b>
                    {check.detail ? <span> {check.detail}</span> : null}
                  </div>
                ) : null}

                <div className="intg-actions">
                  <Button
                    size="small"
                    loading={busy[p.key]}
                    onClick={() => onCheckOne(p.key)}
                  >
                    Проверить подключение
                  </Button>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Сопоставление пользовательских полей Битрикс24 */}
      <FieldMapSection targets={cfg.field_targets} initial={cfg.field_map} />

      {/* Нижняя панель действий */}
      <div className="intg-footer">
        <span className="intg-footer-note">
          Проверка использует сохранённые доступы. Изменили поля — сначала сохраните.
        </span>
        <div style={{ display: "flex", gap: 10 }}>
          <Button onClick={onCheckAll} loading={checkAll.isPending}>
            Проверить все
          </Button>
          <Button type="primary" onClick={onSave} loading={save.isPending} disabled={!dirty}>
            Сохранить
          </Button>
        </div>
      </div>
    </>
  );
}

function resultCls(status: CheckStatus): string {
  if (status === "ok") return "ok";
  if (status === "not_configured") return "idle";
  return "err";
}
