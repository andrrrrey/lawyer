import { Spin } from "antd";

import { useChain, useChannels } from "@/api/analytics";
import { ChainView } from "@/components/ChainView";
import { ChannelsTable } from "@/components/ChannelsTable";
import { EmptyState } from "@/components/EmptyState";
import { useFilters } from "@/state/filters";

export default function AnalyticsPage() {
  const f = useFilters();
  const chain = useChain(f.period, f.legalEntity);
  const channels = useChannels(f.channel, f.period, f.legalEntity);

  return (
    <>
      <div className="card">
        <div className="card-h">
          <h3>Цепочка «реклама → деньги»</h3>
          <span className="sub">сквозная аналитика по деньгам, не по кликам</span>
        </div>
        {chain.data ? <ChainView steps={chain.data} /> : <div style={{ padding: 30 }}><Spin /></div>}
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <div className="card-h">
          <div><h3>Сводка по каналам и кампаниям</h3></div>
        </div>
        {!channels.data ? (
          <div style={{ padding: 30 }}><Spin /></div>
        ) : channels.data.length ? (
          <ChannelsTable rows={channels.data} />
        ) : (
          <EmptyState
            title="Нет данных по каналам"
            hint="Сводка собирается из расходов Директа и фактической выручки 1С. Добавьте кабинеты Директа и нажмите «Обновить Яндекс»."
          />
        )}
      </div>
    </>
  );
}
