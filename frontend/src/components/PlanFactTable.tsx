import type { PlanFactRow, PlanFactValues } from "@/api/dashboard";

const METRICS: { key: keyof PlanFactValues; label: string; money?: boolean }[] = [
  { key: "revenue", label: "Выручка", money: true },
  { key: "payments", label: "Оплаты" },
  { key: "deals", label: "Продажи" },
  { key: "calls", label: "Звонки" },
  { key: "meetings", label: "Встречи" },
];

const number = (value: number, money = false) =>
  `${value.toLocaleString("ru-RU")}${money ? " ₽" : ""}`;

function Metric({ row, metric, money }: {
  row: PlanFactRow; metric: keyof PlanFactValues; money?: boolean;
}) {
  const percent = row.completion[metric];
  return (
    <td className="num">
      <b>{number(row.fact[metric], money)}</b>
      <div className="sub">из {number(row.plan[metric], money)}</div>
      <span className={`tag ${percent === null ? "" : percent >= 100 ? "t-green" : percent >= 70 ? "t-amber" : "t-red"}`}>
        {percent === null ? "план не задан" : `${percent}%`}
      </span>
    </td>
  );
}

export function PlanFactTable({ rows }: { rows: PlanFactRow[] }) {
  return (
    <div className="card">
      <div className="card-h">
        <div><h3>План‑факт</h3><span className="sub">факт из Bitrix24 и поступлений 1С</span></div>
      </div>
      <div className="tbl-wrap">
        <table>
          <thead><tr><th>Уровень</th>{METRICS.map((item) => <th key={item.key}>{item.label}</th>)}<th>Итого</th></tr></thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.key}>
                <td><b>{row.scope_name}</b><div className="sub">{row.legal_entity_name}</div></td>
                {METRICS.map((item) => <Metric key={item.key} row={row} metric={item.key} money={item.money} />)}
                <td><span className={`tag ${row.overall_completion !== null && row.overall_completion >= 100 ? "t-green" : "t-amber"}`}>{row.overall_completion === null ? "—" : `${row.overall_completion}%`}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
