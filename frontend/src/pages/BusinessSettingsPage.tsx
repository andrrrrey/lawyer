import { App, Button, Input, InputNumber, Select, Spin, Switch, Table, Tabs, Tag } from "antd";
import { useEffect, useMemo, useState } from "react";

import {
  type BusinessSettings,
  type DdsArticle,
  type Funnel,
  useBusinessSettings,
  useOneCReceiptJournal,
  useSaveBusinessSettings,
} from "@/api/businessSettings";

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
  const save = useSaveBusinessSettings();
  const receipts = useOneCReceiptJournal();
  const { message } = App.useApp();
  const [draft, setDraft] = useState<BusinessSettings | null>(null);

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
  const sourceOptions = draft.crm_sources.map((x) => ({ value: x.key, label: x.name }));
  const slaOptions = draft.sla_profiles.map((x) => ({ value: x.key, label: x.name }));
  const departmentOptions = draft.departments.map((x) => ({ value: x.key, label: x.name }));
  const employeeOptions = draft.employees.map((x) => ({ value: x.key, label: x.name }));

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
        <Card title="Соответствие воронок" subtitle="внутренний источник Bitrix24 × воронка → юрлицо и SLA">
          {draft.funnels.map((funnel, index) => (
            <div className="setrow" key={funnel.key} style={{ gap: 8, flexWrap: "wrap" }}>
              <Input style={inputStyle} placeholder="Название" value={funnel.name} onChange={(e) => mutate((x) => { x.funnels[index].name = e.target.value; })} />
              <Input style={{ width: 130 }} placeholder="ID воронки" value={funnel.external_id} onChange={(e) => mutate((x) => { x.funnels[index].external_id = e.target.value; })} />
              <Select style={{ width: 190 }} options={sourceOptions} value={funnel.crm_source} onChange={(v) => mutate((x) => { x.funnels[index].crm_source = v; })} />
              <Select style={{ width: 120 }} options={entityOptions} value={funnel.legal_entity_key} onChange={(v) => mutate((x) => { x.funnels[index].legal_entity_key = v; })} />
              <Select style={{ width: 180 }} options={slaOptions} value={funnel.sla_profile_key} onChange={(v) => mutate((x) => { x.funnels[index].sla_profile_key = v; })} />
              <Switch checked={funnel.enabled} onChange={(v) => mutate((x) => { x.funnels[index].enabled = v; })} />
              <Button danger onClick={() => mutate((x) => { x.funnels.splice(index, 1); })}>Удалить</Button>
            </div>
          ))}
          <Button onClick={() => mutate((x) => x.funnels.push({ key: uid("funnel"), external_id: "", name: "Новая воронка", crm_source: x.crm_sources[0]?.key ?? "", legal_entity_key: x.legal_entities[0]?.key ?? "", sla_profile_key: x.sla_profiles[0]?.key ?? "default", enabled: true } satisfies Funnel))}>Добавить воронку</Button>
        </Card>
      ),
    },
    {
      key: "sla", label: "SLA и регламенты", children: (
        <>{draft.sla_profiles.map((profile, profileIndex) => (
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
        ))}</>
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
      key: "team", label: "Структура и планы", children: (
        <>
          <Card title="Отделы">
            {draft.departments.map((row, index) => <div className="setrow" key={row.key}><Input value={row.name} onChange={(e) => mutate((x) => { x.departments[index].name = e.target.value; })} /><Switch checked={row.enabled} onChange={(v) => mutate((x) => { x.departments[index].enabled = v; })} /><Button danger onClick={() => mutate((x) => x.departments.splice(index, 1))}>Удалить</Button></div>)}
            <Button onClick={() => mutate((x) => x.departments.push({ key: uid("department"), name: "Новый отдел", enabled: true }))}>Добавить отдел</Button>
          </Card>
          <Card title="Сотрудники" subtitle="соответствие пользователям Bitrix24, юрлицам и отделам">
            {draft.employees.map((row, index) => <div className="setrow" key={row.key} style={{ gap: 8, flexWrap: "wrap" }}><Input style={inputStyle} placeholder="ФИО" value={row.name} onChange={(e) => mutate((x) => { x.employees[index].name = e.target.value; })} /><Input style={{ width: 140 }} placeholder="ID Bitrix24" value={row.bitrix_user_id} onChange={(e) => mutate((x) => { x.employees[index].bitrix_user_id = e.target.value; })} /><Select style={{ width: 120 }} allowClear placeholder="Юрлицо" options={entityOptions} value={row.legal_entity_key || undefined} onChange={(v) => mutate((x) => { x.employees[index].legal_entity_key = v ?? ""; })} /><Select style={{ width: 180 }} allowClear placeholder="Отдел" options={departmentOptions} value={row.department_key || undefined} onChange={(v) => mutate((x) => { x.employees[index].department_key = v ?? ""; })} /><Switch checked={row.enabled} onChange={(v) => mutate((x) => { x.employees[index].enabled = v; })} /><Button danger onClick={() => mutate((x) => x.employees.splice(index, 1))}>Удалить</Button></div>)}
            <Button onClick={() => mutate((x) => x.employees.push({ key: uid("employee"), name: "Новый сотрудник", bitrix_user_id: "", legal_entity_key: "", department_key: "", enabled: true }))}>Добавить сотрудника</Button>
          </Card>
          <Card title="Планы сотрудников" subtitle="период в формате ГГГГ-ММ">
            {draft.plans.map((row, index) => <div className="setrow" key={row.key} style={{ gap: 8, flexWrap: "wrap" }}><Select style={{ width: 190 }} placeholder="Сотрудник" options={employeeOptions} value={row.employee_key || undefined} onChange={(v) => mutate((x) => { x.plans[index].employee_key = v; })} /><Select style={{ width: 120 }} placeholder="Юрлицо" options={entityOptions} value={row.legal_entity_key || undefined} onChange={(v) => mutate((x) => { x.plans[index].legal_entity_key = v; })} /><Input style={{ width: 120 }} placeholder="2026-09" value={row.period} onChange={(e) => mutate((x) => { x.plans[index].period = e.target.value; })} /><InputNumber addonBefore="Выручка" min={0} value={row.revenue} onChange={(v) => mutate((x) => { x.plans[index].revenue = v ?? 0; })} /><InputNumber addonBefore="Оплаты" min={0} value={row.payments} onChange={(v) => mutate((x) => { x.plans[index].payments = v ?? 0; })} /><InputNumber addonBefore="Сделки" min={0} value={row.deals} onChange={(v) => mutate((x) => { x.plans[index].deals = v ?? 0; })} /><Button danger onClick={() => mutate((x) => x.plans.splice(index, 1))}>Удалить</Button></div>)}
            <Button disabled={!draft.employees.length} onClick={() => mutate((x) => x.plans.push({ key: uid("plan"), employee_key: x.employees[0]?.key ?? "", legal_entity_key: x.legal_entities[0]?.key ?? "", period: new Date().toISOString().slice(0, 7), revenue: 0, payments: 0, deals: 0 }))}>Добавить план</Button>
          </Card>
        </>
      ),
    },
  ];

  return <><Tabs items={settingsTabs} /><div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 20 }}><Button disabled={!dirty} onClick={() => setDraft(structuredClone(query.data!))}>Сбросить</Button><Button type="primary" disabled={!dirty} loading={save.isPending} onClick={() => save.mutateAsync(draft).then(() => message.success("Настройки сохранены")).catch((e: Error) => message.error(e.message))}>Сохранить настройки</Button></div></>;
}
