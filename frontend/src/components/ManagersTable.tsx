import type { Manager } from "@/api/dashboard";
import { avatarColor, initials } from "./people";
import { useDrill } from "./useDrill";

export function ManagersTable({ rows }: { rows: Manager[] }) {
  const { toManager } = useDrill();
  return (
    <div className="card">
      <div className="card-h">
        <div><h3>Контроль обработки по менеджерам</h3></div>
      </div>
      <div className="tbl-wrap">
        <table>
          <thead>
            <tr>
              <th>Менеджер</th><th>В работе</th><th>Просрочки</th><th>Без задач</th>
              <th>Ср. контакт</th><th>Ожидают оплату</th><th>Оплаченные сделки</th><th>Сумма оплат</th><th>Зона</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((m) => (
              <tr key={m.name} className="click" onClick={() => toManager(m.name)}>
                <td>
                  <span className="mgr">
                    <span className="ava" style={{ background: avatarColor(m.name) }}>{initials(m.name)}</span>
                    <b>{m.name}</b>
                  </span>
                </td>
                <td className="num">{m.inwork}</td>
                <td className="num">{m.overdue ? <span className="cnt-bad">{m.overdue}</span> : "0"}</td>
                <td className="num">{m.notask ? <span className="cnt-bad">{m.notask}</span> : "0"}</td>
                <td className="num">{m.fc}</td>
                <td className="num">{m.invoices}</td>
                <td className="num">{m.payments}</td>
                <td className="num money">{m.paysum_display}</td>
                <td><span className={`tag ${m.zone_class}`}>{m.zone_label}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
