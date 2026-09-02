import { Spin } from "antd";
import type { ReactNode } from "react";

import {
  useAttention, useFunnel, useKpis, useLeads, useManagers,
  useRevenueSeries, useRomiByChannel, useSources,
} from "@/api/dashboard";
import { AttentionBlock } from "@/components/AttentionBlock";
import { EChart } from "@/components/EChart";
import { EmptyState } from "@/components/EmptyState";
import { KpiRow } from "@/components/KpiRow";
import { LeadsTable } from "@/components/LeadsTable";
import { ManagersTable } from "@/components/ManagersTable";
import {
  donutOption, funnelOption, revenueOption, romiBarOption,
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
  };
  const kpis = useKpis(q);
  const attention = useAttention(q);
  const funnel = useFunnel(q);
  const sources = useSources(q);
  const revenue = useRevenueSeries(q);
  const romi = useRomiByChannel(q);
  const managers = useManagers(q);
  const leads = useLeads(f.mgr, f.source, f.leadFilter, f.period, f.legalEntity);

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
        <ChartCard title="Выручка и маржа" sub="динамика по дням, ₽">
          {revenue.data ? <EChart option={revenueOption(revenue.data)} height={260} /> : <Spin />}
        </ChartCard>
        <ChartCard title="ROMI по каналам" sub="возврат на рекламу">
          {romi.data ? <EChart option={romiBarOption(romi.data)} height={260} /> : <Spin />}
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
