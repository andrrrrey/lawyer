import { Spin } from "antd";
import type { ReactNode } from "react";

import {
  useAttention, useDepartments, useExpensesByArticle, useFunnel, useKpis, useLeads,
  useManagers, usePlanFact, useRomiByChannel, useSources,
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
  donutOption, expensesBarOption, funnelOption, romiBarOption,
} from "@/components/chartOptions";
import { useFilters } from "@/state/filters";

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
  const expenses = useExpensesByArticle(q);
  const romi = useRomiByChannel(q);
  const managers = useManagers(q);
  const departments = useDepartments(q);
  const planFact = usePlanFact(new Date().toISOString().slice(0, 7), q);
  const leads = useLeads(
    f.mgr, f.source, f.leadFilter, f.period, f.legalEntity, f.funnel,
  );

  return (
    <>
      {attention.data ? <AttentionBlock data={attention.data} /> : null}
      {kpis.data ? <KpiRow cards={kpis.data} /> : <div style={{ minHeight: 120 }}><Spin /></div>}

      <div className="grid two" style={{ marginTop: 16 }}>
        <ChartCard title="Воронка обработки" sub="лид → квалификация → сделка → счёт → оплата">
          {funnel.data ? <EChart option={funnelOption(funnel.data)} height={280} /> : <Spin />}
        </ChartCard>
        <ChartCard title="Источники лидов" sub="по источнику сделки">
          {sources.data ? <EChart option={donutOption(sources.data)} height={280} /> : <Spin />}
        </ChartCard>
      </div>

      <div className="grid two-b" style={{ marginTop: 16 }}>
        <ChartCard title="Расходы по статьям" sub="Директ автоматически + ручной журнал">
          {!expenses.data ? <Spin /> : expenses.data.length ? (
            <EChart option={expensesBarOption(expenses.data)} height={260} />
          ) : (
            <EmptyState title="Расходов пока нет" hint="Данные Яндекс Директа появятся после подключения. Остальные статьи можно добавить вручную в разделе «Настройки → Расходы»." />
          )}
        </ChartCard>
        <ChartCard title="ROMI по каналам" sub="фактические поступления 1С против рекламных расходов">
          {!romi.data ? <Spin /> : romi.data.length ? (
            <EChart option={romiBarOption(romi.data)} height={260} />
          ) : (
            <EmptyState title="ROMI пока не рассчитан" hint="Нужны рекламные расходы с каналом и связанные с кампаниями фактические поступления 1С." />
          )}
        </ChartCard>
      </div>

      <div style={{ marginTop: 16 }}>
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
      </div>

      <div style={{ marginTop: 16 }}>
        {planFact.data?.length ? (
          <PlanFactTable rows={planFact.data} />
        ) : planFact.data ? (
          <div className="card">
            <EmptyState
              title="Планы на текущий месяц не заданы"
              hint="Добавьте план компании, отдела или сотрудника в разделе «Настройки → Структура и планы»."
            />
          </div>
        ) : null}
      </div>

      <div style={{ marginTop: 16 }}>
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
      </div>

      <div style={{ marginTop: 16 }}>
        {leads.data && leads.data.length ? (
          <LeadsTable rows={leads.data} />
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
