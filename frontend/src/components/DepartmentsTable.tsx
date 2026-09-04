import type { DepartmentAnalytics } from "@/api/dashboard";

export function DepartmentsTable({ rows }: { rows: DepartmentAnalytics[] }) {
  return (
    <div className="card">
      <div className="card-h">
        <div><h3>Аналитика по отделам</h3><span className="sub">Bitrix24 + звонки и встречи + поступления 1С</span></div>
      </div>
      <div className="tbl-wrap">
        <table>
          <thead>
            <tr>
              <th>Отдел</th><th>Сотрудники</th><th>Лиды</th><th>В работе</th>
              <th>Продажи</th><th>Конверсия</th><th>Звонки</th><th>Встречи</th>
              <th>Оплаты</th><th>Выручка</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.key}>
                <td><b>{row.name}</b></td>
                <td className="num">{row.employees}</td>
                <td className="num">{row.leads}</td>
                <td className="num">{row.inwork}</td>
                <td className="num">{row.sales}</td>
                <td className="num"><span className={`tag ${row.conversion >= 25 ? "t-green" : row.conversion >= 10 ? "t-amber" : "t-red"}`}>{row.conversion}%</span></td>
                <td className="num">{row.calls}</td>
                <td className="num">{row.meetings}</td>
                <td className="num">{row.payments}</td>
                <td className="num money">{row.revenue_display}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
