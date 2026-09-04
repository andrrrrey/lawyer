import { Alert, App, Button, DatePicker, Input, InputNumber, Popconfirm, Select, Spin, Switch, Table, Tabs, Tag } from "antd";
import dayjs from "dayjs";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import {
  type BusinessSettings,
  type BitrixFunnelOption,
  type DdsArticle,
  type Funnel,
  type Plan,
  useBitrixFunnels,
  useBusinessSettings,
  useCreateManualExpense,
  useDeleteManualExpense,
  useManualExpenses,
  useOneCReceiptJournal,
  useSaveBusinessSettings,
} from "@/api/businessSettings";
import AdminPage from "@/pages/AdminPage";

const uid = (prefix: string) => `${prefix}_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;

function Card({ title, subtitle, children }: React.PropsWithChildren<{ title: string; subtitle?: string }>) {
  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <div className="card-h"><div><h3>{title}</h3>{subtitle ? <span className="sub">{subtitle}</span> : null}</div></div>
      <div className="card-p">{children}</div>
    </div>
  );
}

const inputStyle = { minWidth: 150 };

export default function BusinessSettingsPage() {
  const query = useBusinessSettings();
  const bitrixFunnels = useBitrixFunnels();
  const save = useSaveBusinessSettings();
  const receipts = useOneCReceiptJournal();
  const expenses = useManualExpenses();
  const createExpense = useCreateManualExpense();
  const deleteExpense = useDeleteManualExpense();
  const { message } = App.useApp();
  const [searchParams, setSearchParams] = useSearchParams();
  const [draft, setDraft] = useState<BusinessSettings | null>(null);
  const [expenseDraft, setExpenseDraft] = useState({
    spent_at: dayjs().format("YYYY-MM-DD"), legal_entity_key: "", article: "",
    amount: 0, include_in_romi: false, channel: "", campaign: "", comment: "",
  });

  useEffect(() => { if (query.data) setDraft(structuredClone(query.data)); }, [query.data]);
  const dirty = useMemo(
    () => !!draft && !!query.data && JSON.stringify(draft) !== JSON.stringify(query.data),
    [draft, query.data],
  );
  if (!draft) return <div style={{ minHeight: "40vh", display: "grid", placeItems: "center" }}><Spin size="large" /></div>;

  const mutate = (fn: (next: BusinessSettings) => void) => {
    setDraft((current) => { const next = structuredClone(current!); fn(next); return next; });
  };
  const entityOptions = draft.legal_entities.map((x) => ({ value: x.key, label: x.name }));
  const slaOptions = draft.sla_profiles.map((x) => ({ value: x.key, label: x.name }));
  const departmentOptions = draft.departments.map((x) => ({ value: x.key, label: x.name }));
  const employeeOptions = draft.employees.map((x) => ({ value: x.key, label: x.name }));
  const planTargetOptions = (scope: Plan["scope_type"]) => {
    if (scope === "department") return departmentOptions;
    if (scope === "employee") return employeeOptions;
    return [];
  };

  const addExpense = async () => {
    const payload = {
      ...expenseDraft,
      legal_entity_key: expenseDraft.legal_entity_key || draft.legal_entities[0]?.key || "",
    };
    try {
      await createExpense.mutateAsync(payload);
      setExpenseDraft((current) => ({
        ...current, article: "", amount: 0, channel: "", campaign: "", comment: "",
      }));
      message.success("Расход добавлен");
    } catch (error) {
      message.error(error instanceof Error ? error.message : "Не удалось добавить расход");
    }
  };

  const toggleFunnel = (
    sourceKey: string,
    funnel: BitrixFunnelOption,
    enabled: boolean,
  ) => mutate((next) => {
    const index = next.funnels.findIndex(
      (item) => item.crm_source === sourceKey && item.external_id === funnel.id,
    );
    if (!enabled) {
      if (index >= 0) next.funnels.splice(index, 1);
      return;
    }
    if (index >= 0) {
      next.funnels[index].enabled = true;
      next.funnels[index].name = funnel.name;
      return;
    }
    next.funnels.push({
      key: `funnel_${sourceKey}_${funnel.id}`,
      external_id: funnel.id,
      name: funnel.name,
      crm_source: sourceKey,
      legal_entity_key: next.legal_entities[0]?.key ?? "",
      sla_profile_key: next.sla_profiles[0]?.key ?? "default",
      expected_payment_stages: ["Заключение Контракта"],
      enabled: true,
    } satisfies Funnel);
  });

  const updateFunnel = (
    sourceKey: string,
    externalId: string,
    field: "legal_entity_key" | "sla_profile_key",
    value: string,
  ) => mutate((next) => {
    const item = next.funnels.find(
      (row) => row.crm_source === sourceKey && row.external_id === externalId,
    );
    if (item) item[field] = value;
  });

  const settingsTabs = [
    {
      key: "entities", label: "Юрлица и ДДС", children: (
        <>
          {draft.legal_entities.map((entity, index) => (
            <Card key={entity.key} title={entity.name} subtitle="реквизиты и разрешённые статьи поступлений">
              <div className="grid" style={{ gridTemplateColumns: "1fr 1fr 1fr auto", gap: 12 }}>
                <Input value={entity.name} addonBefore="Название" onChange={(e) => mutate((x) => { x.legal_entities[index].name = e.target.value; })} />
                <Input value={entity.inn} addonBefore="ИНН" placeholder="Будет предоставлен" onChange={(e) => mutate((x) => { x.legal_entities[index].inn = e.target.value; })} />
                <Input value={entity.kpp} addonBefore="КПП" onChange={(e) => mutate((x) => { x.legal_entities[index].kpp = e.target.value; })} />
                <Switch checked={entity.enabled} checkedChildren="Вкл." unCheckedChildren="Выкл." onChange={(v) => mutate((x) => { x.legal_entities[index].enabled = v; })} />
              </div>
              <div className="field" style={{ marginTop: 14 }}>
                <label>Статьи ДДС по поступлениям — точное название, одна строка = одна статья</label>
                <Input.TextArea rows={Math.max(5, entity.dds_articles.length + 1)} value={entity.dds_articles.map((a) => a.name).join("\n")} onChange={(e) => mutate((x) => {
                  const old = new Map(x.legal_entities[index].dds_articles.map((a) => [a.name, a]));
                  x.legal_entities[index].dds_articles = e.target.value.split("\n").filter((name) => name.trim()).map((name) => old.get(name) ?? ({ name, operation: "income", enabled: true, notes: "" } satisfies DdsArticle));
                })} />
              </div>
            </Card>
          ))}
        </>
      ),
    },
    {
      key: "funnels", label: "Воронки", children: (
        <Card title="Воронки Bitrix24" subtitle="выберите используемые воронки и укажите их юрлицо и SLA">
          <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 12 }}>
            <Button loading={bitrixFunnels.isFetching} onClick={() => bitrixFunnels.refetch()}>
              Обновить список из Bitrix24
            </Button>
          </div>
          {bitrixFunnels.isLoading ? <Spin /> : null}
          {(bitrixFunnels.data?.sources ?? []).map((source) => {
            const discoveredIds = new Set(source.funnels.map((item) => item.id));
            const savedOnly: BitrixFunnelOption[] = draft.funnels
              .filter((item) => item.crm_source === source.key && !discoveredIds.has(item.external_id))
              .map((item) => ({ id: item.external_id, name: item.name, is_default: false, sort: 0 }));
            const options = [...source.funnels, ...savedOnly];
            return (
              <div key={source.key} style={{ borderTop: "1px solid var(--line2)", paddingTop: 14, marginTop: 14 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
                  <b>{source.name}</b>
                  <Tag color={source.ok ? "green" : source.configured ? "red" : "default"}>
                    {source.ok ? `Получено: ${source.funnels.length}` : source.configured ? "Ошибка подключения" : "Не настроен"}
                  </Tag>
                </div>
                {!source.ok && source.error ? <Alert type="warning" showIcon message={source.error} style={{ marginBottom: 10 }} /> : null}
                {options.length === 0 && source.ok ? <Alert type="info" showIcon message="В этом Bitrix24 нет доступных воронок сделок." /> : null}
                {options.map((option) => {
                  const selected = draft.funnels.find(
                    (item) => item.crm_source === source.key && item.external_id === option.id,
                  );
                  const unavailable = !discoveredIds.has(option.id);
                  return (
                    <div className="setrow" key={`${source.key}:${option.id}`} style={{ gap: 10, flexWrap: "wrap" }}>
                      <Switch
                        checked={!!selected?.enabled}
                        checkedChildren="Выбрана"
                        unCheckedChildren="Не выбрана"
                        onChange={(checked) => toggleFunnel(source.key, option, checked)}
                      />
                      <div className="st" style={{ minWidth: 240 }}>
                        <b>{option.name} {option.is_default ? <Tag>основная</Tag> : null}</b>
                        <span>ID: {option.id}{unavailable ? " · сохранена, но сейчас не найдена в Bitrix24" : ""}</span>
                      </div>
                      <Select
                        style={{ width: 150 }}
                        placeholder="Юрлицо"
                        disabled={!selected?.enabled}
                        options={entityOptions}
                        value={selected?.legal_entity_key}
                        onChange={(value) => updateFunnel(source.key, option.id, "legal_entity_key", value)}
                      />
                      <Select
                        style={{ width: 210 }}
                        placeholder="Профиль SLA"
                        disabled={!selected?.enabled}
                        options={slaOptions}
                        value={selected?.sla_profile_key}
                        onChange={(value) => updateFunnel(source.key, option.id, "sla_profile_key", value)}
                      />
                      <Input
                        style={{ minWidth: 260, flex: 1 }}
                        placeholder="Стадии ожидания оплаты через запятую"
                        value={(selected?.expected_payment_stages ?? ["Заключение Контракта"]).join(", ")}
                        onChange={(event) => mutate((next) => {
                          const item = next.funnels.find(
                            (row) => row.crm_source === source.key && row.external_id === option.id,
                          );
                          if (item) item.expected_payment_stages = event.target.value
                            .split(",").map((value) => value.trim()).filter(Boolean);
                        })}
                      />
                    </div>
                  );
                })}
              </div>
            );
          })}
        </Card>
      ),
    },
    {
      key: "sla", label: "SLA и регламенты", children: (
        <Tabs type="card" items={[
          {
            key: "sla-profiles",
            label: "SLA по воронкам",
            children: <>{draft.sla_profiles.map((profile, profileIndex) => (
              <Card key={profile.key} title={profile.name} subtitle="правила из файла SLA.xlsx; исходная нумерация сохранена">
                {profile.rules.map((rule, ruleIndex) => (
                  <div className="setrow" key={rule.key} style={{ alignItems: "flex-start", gap: 12 }}>
                    <b style={{ minWidth: 28 }}>№{rule.source_number}</b>
                    <div style={{ flex: 1 }}><Input value={rule.name} onChange={(e) => mutate((x) => { x.sla_profiles[profileIndex].rules[ruleIndex].name = e.target.value; })} /><Input.TextArea style={{ marginTop: 8 }} value={rule.description} onChange={(e) => mutate((x) => { x.sla_profiles[profileIndex].rules[ruleIndex].description = e.target.value; })} /></div>
                    {rule.minutes !== undefined ? <InputNumber addonAfter="мин." min={1} value={rule.minutes} onChange={(v) => mutate((x) => { x.sla_profiles[profileIndex].rules[ruleIndex].minutes = v ?? 1; })} /> : null}
                    {rule.days !== undefined ? <InputNumber addonAfter="дн." min={1} value={rule.days} onChange={(v) => mutate((x) => { x.sla_profiles[profileIndex].rules[ruleIndex].days = v ?? 1; })} /> : null}
                    <Switch checked={rule.enabled} onChange={(v) => mutate((x) => { x.sla_profiles[profileIndex].rules[ruleIndex].enabled = v; })} />
                  </div>
                ))}
              </Card>
            ))}</>,
          },
          { key: "control", label: "Параметры контроля CRM", children: <AdminPage /> },
        ]} />
      ),
    },
    {
      key: "onec", label: "Журнал 1С", children: (
        <Card title="Поступления 1С" subtitle="включённые, исключённые и несопоставленные операции">
          <Table rowKey="id" loading={receipts.isLoading} dataSource={receipts.data ?? []} pagination={{ pageSize: 25 }} columns={[
            { title: "Дата", dataIndex: "date", render: (value: string | null) => value ? new Date(value).toLocaleDateString("ru-RU") : "—" },
            { title: "№", dataIndex: "number" },
            { title: "Юрлицо", dataIndex: "legal_entity_key", render: (value: string) => draft.legal_entities.find((x) => x.key === value)?.name ?? "Не определено" },
            { title: "Контрагент", dataIndex: "counterparty" },
            { title: "Статья ДДС", dataIndex: "article" },
            { title: "Сумма", dataIndex: "amount", render: (value: number) => `${value.toLocaleString("ru-RU")} ₽` },
            { title: "Код BTX", dataIndex: "crm_external_id" },
            { title: "Статус", render: (_, row) => row.excluded ? <Tag color="red">Исключено: {row.reason}</Tag> : row.matched ? <Tag color="green">Сопоставлено</Tag> : <Tag color="orange">Не сопоставлено</Tag> },
          ]} />
        </Card>
      ),
    },
    {
      key: "expenses", label: "Расходы", children: (
        <>
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
            message="Расходы Яндекс Директа загружаются автоматически"
            description="Вручную добавляйте другие статьи и корректировки. В ROMI попадут только строки с включённым признаком «Учитывать в ROMI» и указанным рекламным каналом. Не дублируйте здесь расход, уже полученный из Директа."
          />
          <Card title="Добавить расход" subtitle="управленческие и рекламные расходы по юридическим лицам">
            <div className="setrow" style={{ gap: 10, flexWrap: "wrap", alignItems: "flex-end" }}>
              <div className="field"><label>Дата</label><DatePicker value={dayjs(expenseDraft.spent_at)} format="DD.MM.YYYY" onChange={(value) => value && setExpenseDraft((x) => ({ ...x, spent_at: value.format("YYYY-MM-DD") }))} /></div>
              <div className="field"><label>Юрлицо</label><Select style={{ width: 150 }} options={entityOptions} value={expenseDraft.legal_entity_key || draft.legal_entities[0]?.key} onChange={(value) => setExpenseDraft((x) => ({ ...x, legal_entity_key: value }))} /></div>
              <div className="field"><label>Статья расхода</label><Input style={{ width: 210 }} placeholder="Например, реклама в Авито" value={expenseDraft.article} onChange={(e) => setExpenseDraft((x) => ({ ...x, article: e.target.value }))} /></div>
              <div className="field"><label>Сумма, ₽</label><InputNumber min={0.01} precision={2} style={{ width: 150 }} value={expenseDraft.amount} onChange={(value) => setExpenseDraft((x) => ({ ...x, amount: value ?? 0 }))} /></div>
              <div className="field"><label>Учитывать в ROMI</label><Switch checked={expenseDraft.include_in_romi} onChange={(value) => setExpenseDraft((x) => ({ ...x, include_in_romi: value, channel: value ? x.channel : "", campaign: value ? x.campaign : "" }))} /></div>
              <div className="field"><label>Рекламный канал</label><Input disabled={!expenseDraft.include_in_romi} style={{ width: 190 }} placeholder="Например, Авито" value={expenseDraft.channel} onChange={(e) => setExpenseDraft((x) => ({ ...x, channel: e.target.value }))} /></div>
              <div className="field"><label>Кампания</label><Input disabled={!expenseDraft.include_in_romi} style={{ width: 180 }} placeholder="Необязательно" value={expenseDraft.campaign} onChange={(e) => setExpenseDraft((x) => ({ ...x, campaign: e.target.value }))} /></div>
              <div className="field"><label>Комментарий</label><Input style={{ width: 220 }} placeholder="Необязательно" value={expenseDraft.comment} onChange={(e) => setExpenseDraft((x) => ({ ...x, comment: e.target.value }))} /></div>
              <Button type="primary" loading={createExpense.isPending} disabled={!expenseDraft.article.trim() || expenseDraft.amount <= 0 || (expenseDraft.include_in_romi && !expenseDraft.channel.trim())} onClick={addExpense}>Добавить</Button>
            </div>
          </Card>
          <Card title="Журнал расходов" subtitle="автоматические расходы Директа отображаются на дашборде, ручные — в этом журнале">
            <Table rowKey="id" loading={expenses.isLoading} dataSource={expenses.data ?? []} pagination={{ pageSize: 25 }} columns={[
              { title: "Дата", dataIndex: "spent_at", render: (value: string) => dayjs(value).format("DD.MM.YYYY") },
              { title: "Юрлицо", dataIndex: "legal_entity_key", render: (value: string) => draft.legal_entities.find((x) => x.key === value)?.name ?? value },
              { title: "Статья", dataIndex: "article" },
              { title: "Сумма", dataIndex: "amount", render: (value: number) => `${value.toLocaleString("ru-RU")} ₽` },
              { title: "ROMI", dataIndex: "include_in_romi", render: (value: boolean, row) => value ? <Tag color="purple">{row.channel}{row.campaign ? ` · ${row.campaign}` : ""}</Tag> : <Tag>Не учитывается</Tag> },
              { title: "Комментарий", dataIndex: "comment" },
              { title: "", render: (_, row) => <Popconfirm title="Удалить расход?" okText="Удалить" cancelText="Отмена" onConfirm={() => deleteExpense.mutateAsync(row.id).then(() => message.success("Расход удалён")).catch((e: Error) => message.error(e.message))}><Button danger size="small">Удалить</Button></Popconfirm> },
            ]} />
          </Card>
        </>
      ),
    },
    {
      key: "team", label: "Структура и планы", children: (
        <>
          <Card title="Отделы">
            {draft.departments.map((row, index) => <div className="setrow" key={row.key}><Input value={row.name} onChange={(e) => mutate((x) => { x.departments[index].name = e.target.value; })} /><Switch checked={row.enabled} onChange={(v) => mutate((x) => { x.departments[index].enabled = v; })} /><Button danger onClick={() => mutate((x) => x.departments.splice(index, 1))}>Удалить</Button></div>)}
            <Button onClick={() => mutate((x) => x.departments.push({ key: uid("department"), name: "Новый отдел", enabled: true }))}>Добавить отдел</Button>
          </Card>
          <Card title="Сотрудники" subtitle="соответствие пользователям Bitrix24, юрлицам и отделам">
            {draft.employees.map((row, index) => <div className="setrow" key={row.key} style={{ gap: 8, flexWrap: "wrap" }}><Input style={inputStyle} placeholder="ФИО" value={row.name} onChange={(e) => mutate((x) => { x.employees[index].name = e.target.value; })} /><Select style={{ width: 190 }} placeholder="Bitrix24" options={draft.crm_sources.map((x) => ({ value: x.key, label: x.name }))} value={row.crm_source || undefined} onChange={(v) => mutate((x) => { x.employees[index].crm_source = v; })} /><Input style={{ width: 140 }} placeholder="ID Bitrix24" value={row.bitrix_user_id} onChange={(e) => mutate((x) => { x.employees[index].bitrix_user_id = e.target.value; })} /><Select style={{ width: 120 }} allowClear placeholder="Юрлицо" options={entityOptions} value={row.legal_entity_key || undefined} onChange={(v) => mutate((x) => { x.employees[index].legal_entity_key = v ?? ""; })} /><Select style={{ width: 180 }} allowClear placeholder="Отдел" options={departmentOptions} value={row.department_key || undefined} onChange={(v) => mutate((x) => { x.employees[index].department_key = v ?? ""; })} /><Switch checked={row.enabled} onChange={(v) => mutate((x) => { x.employees[index].enabled = v; })} /><Button danger onClick={() => mutate((x) => x.employees.splice(index, 1))}>Удалить</Button></div>)}
            <Button onClick={() => mutate((x) => x.employees.push({ key: uid("employee"), name: "Новый сотрудник", crm_source: x.crm_sources[0]?.key ?? "", bitrix_user_id: "", legal_entity_key: "", department_key: "", enabled: true }))}>Добавить сотрудника</Button>
          </Card>
          <Card title="Планы" subtitle="на компанию, отдел или сотрудника; факт рассчитывается автоматически">
            {draft.plans.map((row, index) => (
              <div className="setrow" key={row.key} style={{ gap: 8, flexWrap: "wrap" }}>
                <Select
                  style={{ width: 145 }}
                  value={row.scope_type}
                  options={[
                    { value: "company", label: "Компания" },
                    { value: "department", label: "Отдел" },
                    { value: "employee", label: "Сотрудник" },
                  ]}
                  onChange={(scope: Plan["scope_type"]) => mutate((x) => {
                    x.plans[index].scope_type = scope;
                    x.plans[index].scope_key = scope === "company"
                      ? x.plans[index].legal_entity_key
                      : planTargetOptions(scope)[0]?.value ?? "";
                  })}
                />
                {row.scope_type !== "company" ? (
                  <Select
                    style={{ width: 190 }}
                    placeholder={row.scope_type === "department" ? "Отдел" : "Сотрудник"}
                    options={planTargetOptions(row.scope_type)}
                    value={row.scope_key || undefined}
                    onChange={(value) => mutate((x) => { x.plans[index].scope_key = value; })}
                  />
                ) : null}
                <Select
                  style={{ width: 120 }}
                  placeholder="Юрлицо"
                  options={entityOptions}
                  value={row.legal_entity_key || undefined}
                  onChange={(value) => mutate((x) => {
                    x.plans[index].legal_entity_key = value;
                    if (x.plans[index].scope_type === "company") x.plans[index].scope_key = value;
                  })}
                />
                <DatePicker
                  picker="month"
                  format="MM.YYYY"
                  value={dayjs(`${row.period}-01`)}
                  onChange={(value) => {
                    if (value) mutate((x) => { x.plans[index].period = value.format("YYYY-MM"); });
                  }}
                />
                <InputNumber addonBefore="Выручка" min={0} value={row.revenue} onChange={(v) => mutate((x) => { x.plans[index].revenue = v ?? 0; })} />
                <InputNumber addonBefore="Оплаты" min={0} value={row.payments} onChange={(v) => mutate((x) => { x.plans[index].payments = v ?? 0; })} />
                <InputNumber addonBefore="Продажи" min={0} value={row.deals} onChange={(v) => mutate((x) => { x.plans[index].deals = v ?? 0; })} />
                <InputNumber addonBefore="Звонки" min={0} value={row.calls} onChange={(v) => mutate((x) => { x.plans[index].calls = v ?? 0; })} />
                <InputNumber addonBefore="Встречи" min={0} value={row.meetings} onChange={(v) => mutate((x) => { x.plans[index].meetings = v ?? 0; })} />
                <Button danger onClick={() => mutate((x) => x.plans.splice(index, 1))}>Удалить</Button>
              </div>
            ))}
            <Button disabled={!draft.legal_entities.length} onClick={() => mutate((x) => {
              const entity = x.legal_entities[0]?.key ?? "";
              x.plans.push({
                key: uid("plan"), scope_type: "company", scope_key: entity,
                legal_entity_key: entity, period: new Date().toISOString().slice(0, 7),
                revenue: 0, payments: 0, deals: 0, calls: 0, meetings: 0,
              });
            })}>Добавить план</Button>
          </Card>
        </>
      ),
    },
  ];

  const requestedTab = searchParams.get("tab") ?? "entities";
  const activeTab = settingsTabs.some((item) => item.key === requestedTab) ? requestedTab : "entities";

  return <><Tabs activeKey={activeTab} onChange={(tab) => setSearchParams({ tab })} items={settingsTabs} /><div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 20 }}><Button disabled={!dirty} onClick={() => setDraft(structuredClone(query.data!))}>Сбросить</Button><Button type="primary" disabled={!dirty} loading={save.isPending} onClick={() => save.mutateAsync(draft).then(() => message.success("Настройки сохранены")).catch((e: Error) => message.error(e.message))}>Сохранить настройки</Button></div></>;
}
