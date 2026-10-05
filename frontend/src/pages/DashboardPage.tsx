import { DatePicker, Spin } from "antd";
import dayjs from "dayjs";
import { type ReactNode, useEffect, useState } from "react";

import {
  useAttention, useDepartments, useExpensesByArticle, useFunnel, useKpis, useLeads,
  useManagers, usePlanFact, useRevenueSeries, useRomiByChannel, useSources,
} from "@/api/dashboard";
import { AttentionBlock } from "@/components/AttentionBlock";
import { EChart } from "@/components/EChart";
import { EmptyState } from "@/components/EmptyState";
import { DepartmentsTable } from "@/components/DepartmentsTable";
import { KpiRow } from "@/components/KpiRow";
import { LeadsTable } from "@/components/LeadsTable";
import { ManagersTable } from "@/components/ManagersTable";
import { PlanFactTable } from "@/components/PlanFactTable";
import {
  expensesBarOption, funnelOption, revenueOption, romiBarOption, sourcesBarOption,
} from "@/components/chartOptions";
import { useFilters } from "@/state/filters";
import { useMe } from "@/api/auth";

function ChartCard({ title, sub, children }: { title: string; sub: string; children: ReactNode }) {
  return (
    <div className="card">
      <div className="card-h"><h3>{title}</h3><span className="sub">{sub}</span></div>
      <div className="card-p">{children}</div>
    </div>
  );
}

export default function DashboardPage() {
  const f = useFilters();
  const me = useMe();
  const canViewFinancial = me.data?.role !== "manager";
  // Все витрины дашборда следуют одному набору фильтров панели.
  const q = {
    period: f.period,
    legalEntity: f.legalEntity,
    mgr: f.mgr,
    source: f.source,
    funnel: f.funnel,
  };
  const kpis = useKpis(q);
  const attention = useAttention(q);
  const funnel = useFunnel(q);
  const sources = useSources(q);
  const revenueSeries = useRevenueSeries(q);
  const expenses = useExpensesByArticle(q, canViewFinancial);
  const romi = useRomiByChannel(q, canViewFinancial);
  const managers = useManagers(q);
  const departments = useDepartments(q);
  const [planMonth, setPlanMonth] = useState(new Date().toISOString().slice(0, 7));
  const [leadPage, setLeadPage] = useState(1);
  const planFact = usePlanFact(planMonth, q);
  const leads = useLeads(
    f.mgr, f.source, f.leadFilter, f.period, f.legalEntity, f.funnel, leadPage,
  );
  useEffect(() => setLeadPage(1), [f.mgr, f.source, f.leadFilter, f.period, f.legalEntity, f.funnel]);

  return (
    <>
      {attention.data ? <AttentionBlock data={attention.data} /> : null}
      {kpis.data ? <KpiRow cards={kpis.data} /> : <div style={{ minHeight: 120 }}><Spin /></div>}

      <div className="grid two" style={{ marginTop: 16 }}>
        <ChartCard title="Воронка обработки" sub="уникальные обращения и сделки за период → стадия ожидания оплаты → подтверждённая оплата 1С">
          {funnel.data ? <EChart option={funnelOption(funnel.data)} height={280} /> : <Spin />}
        </ChartCard>
        <ChartCard title="Источники лидов" sub="Источник (авто) · резерв: Источник">
          {sources.data ? <EChart option={sourcesBarOption(sources.data)} height={320} /> : <Spin />}
        </ChartCard>
      </div>

      {canViewFinancial ? <div className="grid two-b" style={{ marginTop: 16 }}>
        <ChartCard title="Динамика выручки" sub="фактические поступления 1С по дням">
          {!revenueSeries.data ? <Spin /> : revenueSeries.data.days.length ? <EChart option={revenueOption(revenueSeries.data)} height={260} /> : <EmptyState title="Нет поступлений за период" />}
        </ChartCard>
        <ChartCard title="Расходы по статьям" sub="Директ автоматически + ручной журнал">
          {!expenses.data ? <Spin /> : expenses.data.length ? (
            <EChart option={expensesBarOption(expenses.data)} height={260} />
          ) : (
            <EmptyState title="Расходов пока нет" hint="Данные Яндекс Директа появятся после подключения. Остальные статьи можно добавить вручную в разделе «Настройки → Расходы»." />
          )}
        </ChartCard>
        <ChartCard title="ROMI по выручке" sub="фактические поступления 1С против рекламных расходов">
          {!romi.data ? <Spin /> : romi.data.length ? (
            <EChart option={romiBarOption(romi.data)} height={260} />
          ) : (
            <EmptyState title="ROMI пока не рассчитан" hint="Нужны рекламные расходы с каналом и связанные с кампаниями фактические поступления 1С." />
          )}
        </ChartCard>
      </div> : null}

      {me.data?.role !== "manager" ? <div style={{ marginTop: 16 }}>
        {managers.data && managers.data.length ? (
          <ManagersTable rows={managers.data} />
        ) : managers.data ? (
          <div className="card">
            <EmptyState
              title="Нет данных по менеджерам"
              hint="Агрегаты считаются автоматически по сделкам Битрикс24 с назначенным ответственным. Подключите Битрикс24 и выполните пересчёт — если данных нет, значит у сделок за период не заполнен ответственный."
            />
          </div>
        ) : null}
      </div> : null}

      <div style={{ marginTop: 16 }}>
        <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 8 }}>
          <DatePicker picker="month" allowClear={false} value={dayjs(`${planMonth}-01`)}
            onChange={(value) => value && setPlanMonth(value.format("YYYY-MM"))} />
        </div>
        {planFact.data?.length ? (
          <PlanFactTable rows={planFact.data} financial={canViewFinancial} />
        ) : planFact.data ? (
          <div className="card">
            <EmptyState
              title={`Планы на ${dayjs(`${planMonth}-01`).format("MM.YYYY")} не заданы`}
              hint="Добавьте план компании, отдела или сотрудника в разделе «Настройки → Структура и планы»."
            />
          </div>
        ) : null}
      </div>

      {me.data?.role !== "manager" ? <div style={{ marginTop: 16 }}>
        {departments.data?.length ? (
          <DepartmentsTable rows={departments.data} />
        ) : departments.data ? (
          <div className="card">
            <EmptyState
              title="Отделы ещё не настроены"
              hint="Создайте отделы и распределите сотрудников в разделе «Настройки → Структура и планы»."
            />
          </div>
        ) : null}
      </div> : null}

      <div style={{ marginTop: 16 }}>
        {leads.data && leads.data.items.length ? (
          <LeadsTable rows={leads.data.items} total={leads.data.total} page={leadPage} onPage={setLeadPage} />
        ) : leads.data ? (
          <div className="card">
            <EmptyState
              title="Нет сделок за период"
              hint="Подключите Битрикс24 на странице «Интеграции» и выполните пересчёт."
            />
          </div>
        ) : null}
      </div>
    </>
  );
}
