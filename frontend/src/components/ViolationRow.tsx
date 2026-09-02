import { Button, Tag } from "antd";

import type { Violation } from "@/api/monitor";
import { SparkleIcon } from "./icons";

interface Props {
  v: Violation;
  onTask?: (ref: string) => void;
  taskPending?: boolean;
  taskDone?: boolean;
}

// Строка нарушения регламента (deal) — раскладка из прототипа.
export function ViolationRow({ v, onTask, taskPending, taskDone }: Props) {
  const barColor = v.severity === "review" ? "var(--violet)" : v.over ? "var(--red)" : "var(--amber)";
  const slaCls = v.over ? "over" : v.sla === "—" ? "" : "warn";

  return (
    <div className="deal">
      <div className="lft" style={{ background: barColor }} />
      <div className="body">
        <div className="name">
          {v.name}
          <span className={`tag ${v.kind_class}`}>{v.kind_label}</span>
          {v.amount ? <span className="risk-amt">под риском {v.amount_display}</span> : null}
        </div>
        <div className="meta">
          <span>👤 {v.mgr}</span>
          <span>◎ {v.src}</span>
          {v.norm ? <span>⏱ {v.norm}</span> : null}
        </div>
        <div className="ai-note">
          <SparkleIcon />
          {v.ai}
        </div>
      </div>
      {v.severity !== "review" ? (
        <div className="sla">
          <div className={`sla ${slaCls}`}>
            <div className="t num">{v.sla}</div>
            <div className="l">{v.over ? "просрочено" : v.sla === "—" ? "" : "до нормы"}</div>
          </div>
        </div>
      ) : null}
      {onTask ? (
        <div className="act">
          {taskDone ? (
            <Tag color="success">✓ Задача поставлена</Tag>
          ) : (
            <Button type="primary" size="small" loading={taskPending} onClick={() => onTask(v.deal_key)}>
              Поставить задачу
            </Button>
          )}
        </div>
      ) : null}
    </div>
  );
}
