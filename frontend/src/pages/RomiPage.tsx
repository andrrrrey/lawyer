import { App, Button, Spin } from "antd";
import { useState } from "react";

import {
  type BudgetRec, useBudgetRecs, useCampaignsBubble, useMinusWords, useRomiChannels,
} from "@/api/romi";
import { EChart } from "@/components/EChart";
import { EmptyState } from "@/components/EmptyState";
import { bubbleOption, romiSpendMarginOption } from "@/components/chartOptions";

const MS_STATUS: Record<string, [string, string]> = {
  new: ["Новое", "ms-new"], accepted: ["Принято", "ms-ok"],
  rejected: ["Отклонено", "ms-rej"], exported: ["Выгружено", "ms-exp"],
};

function SrcChips({ src }: { src: string[] }) {
  return (
    <div className="rec-src">
      {src.map((s) => <span key={s} className="srcchip">{s}</span>)}
    </div>
  );
}

function RecCard({ r }: { r: BudgetRec }) {
  const { message } = App.useApp();
  return (
    <div className="rec">
      <div className={`ric ${r.ic}`}>
        <svg fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"
          dangerouslySetInnerHTML={{ __html: r.svg }} />
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <h4>{r.title} <span className={`tag ${r.tag_class}`}>{r.tag_label}</span></h4>
        <p dangerouslySetInnerHTML={{ __html: r.text }} />
        <div className="why"><b>Как найдено:</b> {r.why}</div>
        <div className="rec-meta">
          <SrcChips src={r.src} />
          <span className="conf">достоверность: <b>{r.conf}</b></span>
          {r.dep ? <span className="depchip" title="Требует настроенной связки сделка ↔ поступление">треб. связки с 1С</span> : null}
        </div>
        <div className="rec-act">
          <Button type="primary" size="small" onClick={() => message.success("Рекомендация принята — сформирована задача")}>Принять</Button>
          <Button size="small" onClick={() => message.success("Отложено")}>Отложить</Button>
          <span className="impact tag t-blue">{r.impact}</span>
        </div>
      </div>
    </div>
  );
}

export default function RomiPage() {
  const romiCh = useRomiChannels();
  const bubble = useCampaignsBubble();
  const recs = useBudgetRecs();
  const mw = useMinusWords();
  const { message } = App.useApp();
  const [statuses, setStatuses] = useState<Record<number, string>>({});

  const cycle = (i: number, current: string) => {
    const order = ["new", "accepted", "rejected"];
    const cur = statuses[i] ?? current;
    const next = cur === "exported" ? "new" : order[(order.indexOf(cur) + 1) % order.length];
    setStatuses((p) => ({ ...p, [i]: next }));
  };

  // Реальная выгрузка минус-слов: текстовый файл (по фразе на строку — формат,
  // который вставляется в «Минус-фразы» Яндекс Директа).
  const onDownloadMinus = () => {
    const items = mw.data?.items ?? [];
    if (!items.length) {
      message.info("Нет кандидатов в минус-слова — выполните пересчёт с подключённым Директом.");
      return;
    }
    const body = items.map((i) => i.phrase.trim()).filter(Boolean).join("\n");
    const blob = new Blob([body], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "minus-words-yandex-direct.txt";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    message.success(`Скачано минус-слов: ${items.length}`);
  };

  return (
    <>
      <div className="grid two-b">
        <div className="card">
          <div className="card-h"><h3>ROMI по каналам</h3><span className="sub">маржа против расхода</span></div>
          <div className="card-p">
            {romiCh.data ? <EChart option={romiSpendMarginOption(romiCh.data)} height={300} /> : <Spin />}
          </div>
        </div>
        <div className="card">
          <div className="card-h"><h3>Эффективность кампаний</h3><span className="sub">размер точки — выручка</span></div>
          <div className="card-p">
            {bubble.data ? <EChart option={bubbleOption(bubble.data)} height={300} /> : <Spin />}
          </div>
        </div>
      </div>

      <h3 style={{ fontSize: 15, fontWeight: 600, margin: "22px 0 0" }}>Рекомендации AI по бюджету</h3>
      {recs.data && recs.data.length === 0 ? (
        <div className="card" style={{ marginTop: 12 }}>
          <EmptyState
            title="Рекомендаций пока нет"
            hint="Рекомендации по бюджету формирует AI-слой по данным Директа и фактическим поступлениям 1С. Подключите интеграции, выполните пересчёт и нажмите «Сгенерировать AI» на странице «Интеграции»."
          />
        </div>
      ) : (
        <div className="grid recs-grid" style={{ gap: 14, marginTop: 12 }}>
          {recs.data?.map((r, i) => <RecCard key={i} r={r} />)}
        </div>
      )}

      <div className="card" style={{ marginTop: 18 }}>
        <div className="card-h">
          <div><h3>Минус-слова · рабочий список</h3></div>
        </div>
        {mw.data && mw.data.items.length === 0 ? (
          <EmptyState
            title="Нет кандидатов в минус-слова"
            hint="Список формируется из отчёта по поисковым запросам Яндекс Директа. Подключите Директ и выполните пересчёт."
          />
        ) : (
        <>
        <div className="tbl-wrap">
          <table>
            <thead>
              <tr>
                <th>Кампания</th><th>Фраза</th><th>Расход</th><th>Клики</th><th>Конв.</th>
                <th>Причина</th><th>Достоверность</th><th>Статус</th>
              </tr>
            </thead>
            <tbody>
              {mw.data?.items.slice(0, 10).map((w, i) => {
                const st = statuses[i] ?? w.status;
                return (
                  <tr key={i}>
                    <td><span className="tag t-gray">{w.camp}</span></td>
                    <td style={{ fontWeight: 600 }}>{w.phrase}</td>
                    <td className="num">{w.spend_display}</td>
                    <td className="num">{w.clicks}</td>
                    <td className="num">{w.conv}</td>
                    <td><span className="mw-reason">{w.reason}</span></td>
                    <td><span className={`conf-dot ${w.conf === "высокая" ? "cf-hi" : "cf-mid"}`} />{w.conf}</td>
                    <td><span className={`msbadge ${MS_STATUS[st][1]}`} onClick={() => cycle(i, w.status)} title="нажмите для смены статуса">{MS_STATUS[st][0]}</span></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div style={{ padding: "12px 14px", fontSize: 12, color: "var(--muted)" }}>
          Показаны 10 из <b>{mw.data?.summary.count ?? "—"}</b> кандидатов. Полный список — в выгрузке ниже.
        </div>
        </>
        )}
      </div>

      <div className="card export-card" style={{ marginTop: 16 }}>
        <div className="ec-ic">
          <svg fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
            <path d="M12 3v12M8 11l4 4 4-4M4 21h16" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </div>
        <div className="ec-body">
          <h3>Список минус-слов для Яндекс Директа</h3>
          <p>Кандидаты, на которые расходуется бюджет без конверсий. Выгрузка в формате Яндекс Директа для добавления в кампании (применение — на стороне Заказчика).</p>
          <div className="ec-stats">
            <div className="ecs"><b className="num">{mw.data?.summary.count ?? "—"}</b><span>кандидатов в минус-слова</span></div>
            <div className="ecs"><b className="num">{mw.data?.summary.spend_display ?? "—"}</b><span>расход без конверсий / мес</span></div>
            <div className="ecs"><b className="num">{mw.data?.summary.camps ?? "—"}</b><span>кампаний охвачено</span></div>
          </div>
        </div>
        <div className="ec-act">
          <Button type="primary" onClick={onDownloadMinus}>Скачать список</Button>
          <span className="ec-note">формат Яндекс Директа</span>
        </div>
      </div>
    </>
  );
}
