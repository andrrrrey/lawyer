import { Fragment, useState } from "react";

import type { Action, Campaign, ChannelRow, RomiTag } from "@/api/analytics";

function RomiCell({ romi }: { romi: RomiTag }) {
  return <span className={`tag ${romi.cls}`}>{romi.display}</span>;
}

function ActionCell({ action }: { action: Action }) {
  if (action.label === "—") return <span className="nodata" title={action.note}>—</span>;
  return <span className={`actbadge ${action.cls}`} title={action.note}>{action.label}</span>;
}

function CampaignRow({ k }: { k: Campaign }) {
  // Кампания — обычная строка той же таблицы (не вложенная), чтобы колонки
  // совпадали с шапкой канала. Первая ячейка (каретка) — пустая.
  return (
    <tr className="camp-row">
      <td />
      <td className="cell-cmp"><span className="camp-name">↳ {k.name}</span></td>
      <td className="num">{k.spend ? k.spend_display : "—"}</td>
      <td className="num">{k.leads}</td>
      <td className="num">{k.deals}</td>
      <td className="num">{k.payments}</td>
      <td className="num money">{k.revenue_display}</td>
      <td className="num money" style={{ color: "var(--green)" }}>{k.margin_display}</td>
      <td><RomiCell romi={k.romi} /></td>
      <td><ActionCell action={k.action} /></td>
    </tr>
  );
}

export function ChannelsTable({ rows }: { rows: ChannelRow[] }) {
  const [open, setOpen] = useState<Set<number>>(new Set());
  const toggle = (i: number) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(i)) next.delete(i);
      else next.add(i);
      return next;
    });

  return (
    <div className="tbl-wrap">
      <table>
        <thead>
          <tr>
            <th />
            <th className="cell-cmp">Канал / кампания</th><th>Расход</th><th>Лиды</th><th>Сделки</th><th>Оплаты</th>
            <th>Выручка</th><th>Маржа</th><th>ROMI</th><th>Действие</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((c, i) => {
            const hasKids = c.campaigns.length > 0;
            return (
              <Fragment key={i}>
                <tr
                  className={`${hasKids ? "click" : ""} ${open.has(i) ? "open" : ""}`}
                  onClick={hasKids ? () => toggle(i) : undefined}
                >
                  <td>{hasKids ? <span className="caret">▸</span> : null}</td>
                  <td className="cell-cmp">
                    <span style={{ display: "inline-flex", alignItems: "center", gap: 9 }}>
                      <i style={{ width: 10, height: 10, borderRadius: 3, background: c.color }} />
                      <b>{c.name}</b>
                    </span>
                  </td>
                  <td className="num">{c.spend_display}</td>
                  <td className="num">{c.leads}</td>
                  <td className="num">{c.deals}</td>
                  <td className="num">{c.payments}</td>
                  <td className="num money">{c.revenue_display}</td>
                  <td className="num money" style={{ color: "var(--green)" }}>{c.margin_display}</td>
                  <td><RomiCell romi={c.romi} /></td>
                  <td><ActionCell action={c.action} /></td>
                </tr>
                {hasKids && open.has(i)
                  ? c.campaigns.map((k, j) => <CampaignRow key={`c-${j}`} k={k} />)
                  : null}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
