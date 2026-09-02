import { Spin } from "antd";

import { type Insight, useInsights } from "@/api/ai";
import { EmptyState } from "@/components/EmptyState";

const ICONS: Record<string, string> = {
  alert: '<path d="M12 8v4M12 16h.01M10.3 3.9L2.6 17.5a2 2 0 001.7 3h15.4a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z" stroke-linejoin="round"/>',
  trend: '<path d="M4 7l6 6 4-4 6 6M20 15V9M14 9h6" stroke-linecap="round" stroke-linejoin="round"/>',
  eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/>',
  up: '<path d="M4 18L10 12l4 4 6-8M20 8h-4M20 8v4" stroke-linejoin="round"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2" stroke-linecap="round"/>',
  net: '<circle cx="6" cy="7" r="2.4"/><circle cx="18" cy="7" r="2.4"/><circle cx="12" cy="17" r="2.4"/><path d="M7.6 8.6l3 6.8M16.4 8.6l-3 6.8M8.2 7h7.6" stroke-linecap="round"/>',
  leak: '<path d="M6 3h12M8 3v4l-3 9a4 4 0 004 5h6a4 4 0 004-5l-3-9V3" stroke-linejoin="round"/><path d="M6.5 14h11" stroke-linecap="round"/>',
};

const REC_ARROW = '<path d="M5 12h14M13 6l6 6-6 6" stroke-linecap="round" stroke-linejoin="round"/>';

function InsightCard({ x }: { x: Insight }) {
  return (
    <div className="insight">
      <div className={`iic ${x.ic}`}>
        <svg fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"
          dangerouslySetInnerHTML={{ __html: ICONS[x.icon] ?? "" }} />
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="ihead">
          <b>{x.title}</b>
          <span className={`sev ${x.sev_class}`}>{x.sev_label}</span>
          <span className="time">{x.time}</span>
        </div>
        <div className="i-surface"><span>На дашборде:</span> {x.surface}</div>
        <p dangerouslySetInnerHTML={{ __html: x.text }} />
        <div className="i-rec">
          <svg fill="none" stroke="currentColor" strokeWidth={2.2} viewBox="0 0 24 24"
            dangerouslySetInnerHTML={{ __html: REC_ARROW }} />
          <span>{x.rec}</span>
        </div>
        <div className="rec-meta">
          <div className="rec-src">{x.src.map((s) => <span key={s} className="srcchip">{s}</span>)}</div>
          <span className="conf">достоверность: <b>{x.conf}</b></span>
          {x.dep ? <span className="depchip">треб. связки с 1С</span> : null}
        </div>
      </div>
    </div>
  );
}

export default function AiPage() {
  const insights = useInsights();

  return (
    <>
      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-h">
          <h3>AI-слой интерпретации</h3>
          <span className="sub">закономерности, отклонения и риски · вызовы модели по расписанию</span>
        </div>
        <div className="card-p" style={{ fontSize: 13, color: "var(--muted)", lineHeight: 1.6 }}>
          Модель применяется только на слое интерпретации и рекомендаций. Расчёт метрик, контроль
          сроков и атрибуция выполняются детерминированной логикой без LLM (раздел 3.6 ТЗ).
        </div>
      </div>

      {!insights.data ? (
        <div style={{ padding: 40, textAlign: "center" }}><Spin /></div>
      ) : insights.data.length ? (
        <div className="grid" style={{ gap: 12 }}>
          {insights.data.map((x, i) => <InsightCard key={i} x={x} />)}
        </div>
      ) : (
        <div className="card">
          <EmptyState
            title="AI-инсайтов пока нет"
            hint="Подключите AI-интеграцию (API-ключ и Base URL LLM) на странице «Интеграции» и нажмите «Сгенерировать AI-советы и отчёты»."
          />
        </div>
      )}
    </>
  );
}
