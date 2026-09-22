import { Alert, Spin, Table } from "antd";

import { useChain, useChannels, useReconciliation } from "@/api/analytics";
import { ChainView } from "@/components/ChainView";
import { ChannelsTable } from "@/components/ChannelsTable";
import { EmptyState } from "@/components/EmptyState";
import { useFilters } from "@/state/filters";

export default function AnalyticsPage() {
  const f = useFilters();
  const legalEntity = f.legalEntity[0] ?? "all";
  const chain = useChain(f.period, legalEntity);
  const reconciliation = useReconciliation(f.period, legalEntity);
  const channels = useChannels(f.channel, f.period, legalEntity);
  const money = (value: number) => `${Math.round(value).toLocaleString("ru-RU")} ₽`;

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
          <div>
            <h3>Сверка Bitrix24 ↔ 1С</h3>
            <span className="sub">календарные даты по Москве; договоры и фактические поступления показаны отдельно</span>
          </div>
        </div>
        {!reconciliation.data ? (
          <div style={{ padding: 30 }}><Spin /></div>
        ) : (
          <div className="card-p">
            <div className="recon-grid">
              <div className="recon-box">
                <span>Bitrix24</span>
                <b>{reconciliation.data.bitrix.leads.toLocaleString("ru-RU")} лидов</b>
                <b>{reconciliation.data.bitrix.deals.toLocaleString("ru-RU")} сделок</b>
                <small>
                  Успешно завершено за период: {reconciliation.data.bitrix.successful_deals}, договорная сумма {money(reconciliation.data.bitrix.successful_amount)}
                </small>
              </div>
              <div className="recon-box recon-ok">
                <span>Фактические поступления 1С</span>
                <b>{money(reconciliation.data.onec.revenue)}</b>
                <small>{reconciliation.data.onec.payments} платёжных документов</small>
                <small>
                  Связано: {reconciliation.data.onec.matched_payments} платежей / {reconciliation.data.onec.matched_deals} сделок на {money(reconciliation.data.onec.matched_revenue)}
                </small>
              </div>
              <div className="recon-box recon-warn">
                <span>Не сопоставлено с Bitrix24</span>
                <b>{money(reconciliation.data.onec.unmatched_revenue)}</b>
                <small>{reconciliation.data.onec.unmatched_payments} платёжных документов</small>
                <small>
                  Исключено правилами ДДС: {reconciliation.data.onec.excluded_payments} на {money(reconciliation.data.onec.excluded_amount)}
                </small>
              </div>
            </div>
            <Alert
              type={reconciliation.data.difference === 0 ? "success" : "warning"}
              showIcon
              style={{ marginTop: 14 }}
              message={`Разница «1С − успешные сделки Bitrix24»: ${money(reconciliation.data.difference)}`}
              description="Сравнивается договорная сумма сделок, успешно завершённых в периоде, и поступления 1С с датой платежа в периоде. Значения могут различаться из-за частичных оплат, оплат старых сделок и несопоставленных документов."
            />
            <Table
              style={{ marginTop: 14 }}
              size="small"
              rowKey={(row) => `${row.crm_source}:${row.funnel_id}`}
              pagination={false}
              dataSource={reconciliation.data.funnels}
              columns={[
                { title: "Воронка Bitrix24", dataIndex: "name" },
                { title: "Создано сделок", dataIndex: "deals", align: "right" },
                { title: "Завершено успешно за период", dataIndex: "successful_deals", align: "right" },
                { title: "Сумма завершённых успешно", dataIndex: "successful_amount", align: "right", render: money },
              ]}
            />
          </div>
        )}
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
