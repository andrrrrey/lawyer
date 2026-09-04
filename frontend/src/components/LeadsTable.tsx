import type { Lead } from "@/api/dashboard";
import { SparkleIcon } from "./icons";
import { avatarColor, initials } from "./people";

const RISK_META: Record<string, [string, string]> = {
  high: ["Высокий риск", "rk-high"],
  mid: ["Средний риск", "rk-mid"],
};
const TAG_META: Record<string, string> = {
  "крупный чек": "tg-money", повторный: "tg-repeat", юрлицо: "tg-legal",
  дизайнер: "tg-designer", горячий: "tg-hot",
};

function Dot({ on }: { on: boolean }) {
  return <span className="dot-ok" style={{ background: on ? "var(--green)" : "#DFE2EA" }} />;
}

function PriorityCell({ lead }: { lead: Lead }) {
  const risk = lead.risk && RISK_META[lead.risk];
  const tags = lead.tags ?? [];
  if (!risk && !tags.length) return <span className="nodata">—</span>;
  return (
    <>
      {risk ? <span className={`risk-pill ${risk[1]}`}>{risk[0]}</span> : null}
      {tags.length ? (
        <span className="attr-wrap">
          {tags.map((t) => (
            <span key={t} className={`attr ${TAG_META[t] ?? ""}`}>{t}</span>
          ))}
        </span>
      ) : null}
    </>
  );
}

export function LeadsTable({ rows }: { rows: Lead[] }) {
  return (
    <div className="card" id="leads-table">
      <div className="card-h">
        <div><h3>Обработка лидов</h3></div>
      </div>
      <div className="tbl-wrap">
        <table className="mtable">
          <thead>
            <tr>
              <th className="cell-client">Клиент</th><th>Приоритет</th><th>Источник</th><th>Менеджер</th><th>Статус</th>
              <th>1-й контакт</th><th>Звонок</th><th>Счёт</th><th>Оплата</th><th>Сумма</th><th>Комментарий AI</th>
            </tr>
          </thead>
          <tbody>
            {rows.length ? (
              rows.map((l, i) => (
                <tr key={i} className={`click rk-row-${l.risk ?? "none"}`}>
                  <td className="cell-client" style={{ fontWeight: 600 }} title={l.name}>{l.name}</td>
                  <td><PriorityCell lead={l} /></td>
                  <td><span className="tag t-gray">{l.src}</span></td>
                  <td>
                    <span className="mgr">
                      <span className="ava" style={{ background: avatarColor(l.mgr) }}>{initials(l.mgr)}</span>
                      {l.mgr.split(" ")[0]}
                    </span>
                  </td>
                  <td><span className={`tag ${l.status_class}`}>{l.status_label}</span></td>
                  <td className="num">{l.fc}</td>
                  <td style={{ textAlign: "center" }}><Dot on={l.call} /></td>
                  <td style={{ textAlign: "center" }}><Dot on={l.inv} /></td>
                  <td style={{ textAlign: "center" }}><Dot on={l.pay} /></td>
                  <td className="money num">{l.amount_display === "Скрыто" ? "Скрыто" : l.amount ? l.amount_display : "—"}</td>
                  <td>
                    <div className="ai-cell"><SparkleIcon />{l.ai}</div>
                  </td>
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={11}>
                  <div className="empty-note">Нет лидов по выбранным фильтрам</div>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
