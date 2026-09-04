import { DatePicker, Popover, Segmented, Select } from "antd";
import type { Dayjs } from "dayjs";
import dayjs from "dayjs";
import { useState } from "react";
import { useLocation } from "react-router-dom";

import { useFilterOptions } from "@/api/dashboard";
import { useFilters } from "@/state/filters";

// Панель фильтров. Опции менеджеров/каналов/источников — реальные из данных БД
// (в боевом режиме отражают подключённые интеграции; в демо — демо-значения).
const PERIODS = [
  { key: "today", label: "Сегодня" },
  { key: "7", label: "7 дней" },
  { key: "30", label: "30 дней" },
  { key: "quarter", label: "Квартал" },
];

// Какие контролы фильтров релевантны на каждой странице. На страницах, которых
// нет в конфиге (ROMI, AI, Мониторинг, Интеграции, Админ), панель не показывается —
// эти разделы не используют фильтры.
type Control = "period" | "legalEntity" | "funnel" | "channel" | "mgr" | "source";
const PAGE_FILTERS: Record<string, Control[]> = {
  "/dashboard": ["period", "legalEntity", "funnel", "mgr", "source"],
  "/analytics": ["period", "legalEntity", "channel"],
  "/romi": ["period", "legalEntity"],
};

const ISO = "YYYY-MM-DD";

// Кастомный период кодируется в значении фильтра: точная дата — `date:YYYY-MM-DD`,
// интервал — `range:YYYY-MM-DD:YYYY-MM-DD`. Бэкенд разбирает эти же строки.
function parseCustom(period: string): { mode: "date" | "range"; from: Dayjs; to: Dayjs } | null {
  const d = /^date:(\d{4}-\d{2}-\d{2})$/.exec(period);
  if (d) return { mode: "date", from: dayjs(d[1]), to: dayjs(d[1]) };
  const r = /^range:(\d{4}-\d{2}-\d{2}):(\d{4}-\d{2}-\d{2})$/.exec(period);
  if (r) return { mode: "range", from: dayjs(r[1]), to: dayjs(r[2]) };
  return null;
}

function customLabel(period: string): string | null {
  const c = parseCustom(period);
  if (!c) return null;
  if (c.mode === "date") return c.from.format("DD.MM.YYYY");
  return `${c.from.format("DD.MM")}–${c.to.format("DD.MM.YYYY")}`;
}

function opts(all: string, values: string[]) {
  return [{ value: "all", label: all }, ...values.map((v) => ({ value: v, label: v }))];
}

// Кнопка «Период» в переключателе: выбор точной даты или интервала дат.
function CustomPeriod({ period, onPick }: { period: string; onPick: (v: string) => void }) {
  const current = parseCustom(period);
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<"date" | "range">(current?.mode ?? "range");
  const active = current !== null;
  const noFuture = (d: Dayjs) => d.isAfter(dayjs().endOf("day"));

  const content = (
    <div className="period-pop">
      <Segmented
        size="small"
        value={mode}
        onChange={(v) => setMode(v as "date" | "range")}
        options={[
          { value: "date", label: "Точная дата" },
          { value: "range", label: "Интервал" },
        ]}
      />
      {mode === "date" ? (
        <DatePicker
          style={{ width: "100%" }}
          format="DD.MM.YYYY"
          placeholder="Выберите дату"
          disabledDate={noFuture}
          value={current?.mode === "date" ? current.from : null}
          onChange={(d) => {
            if (d) {
              onPick(`date:${d.format(ISO)}`);
              setOpen(false);
            }
          }}
        />
      ) : (
        <DatePicker.RangePicker
          style={{ width: "100%" }}
          format="DD.MM.YYYY"
          placeholder={["Начало", "Конец"]}
          disabledDate={noFuture}
          value={current?.mode === "range" ? [current.from, current.to] : null}
          onChange={(range) => {
            if (range && range[0] && range[1]) {
              onPick(`range:${range[0].format(ISO)}:${range[1].format(ISO)}`);
              setOpen(false);
            }
          }}
        />
      )}
    </div>
  );

  return (
    <Popover
      trigger="click"
      open={open}
      onOpenChange={setOpen}
      placement="bottomLeft"
      content={content}
    >
      <button className={active ? "on" : ""} title="Выбрать точную дату или интервал">
        {active ? customLabel(period) : "Период ▾"}
      </button>
    </Popover>
  );
}

export function FilterBar() {
  const f = useFilters();
  const o = useFilterOptions();
  const location = useLocation();

  const path = Object.keys(PAGE_FILTERS).find((p) => location.pathname.startsWith(p));
  const controls = path ? PAGE_FILTERS[path] : [];
  if (controls.length === 0) return null;

  const customActive = parseCustom(f.period) !== null;

  return (
    <div className="filterbar">
      {controls.includes("period") ? (
        <div className="seg">
          {PERIODS.map((p) => (
            <button
              key={p.key}
              className={!customActive && f.period === p.key ? "on" : ""}
              onClick={() => f.setPeriod(p.key)}
            >
              {p.label}
            </button>
          ))}
          <CustomPeriod period={f.period} onPick={f.setPeriod} />
        </div>
      ) : null}
      <div className="spacer" />
      {controls.includes("legalEntity") ? (
        <Select
          className="fb-select"
          value={f.legalEntity}
          onChange={(value) => {
            f.setLegalEntity(value);
            f.setFunnel("all");
            f.setLeadFilter(null);
          }}
          options={[
            { value: "all", label: "Все юрлица" },
            ...(o.data?.legal_entities ?? []),
          ]}
        />
      ) : null}
      {controls.includes("channel") ? (
        <Select
          className="fb-select"
          value={f.channel}
          onChange={f.setChannel}
          options={opts("Все каналы", o.data?.channels ?? [])}
        />
      ) : null}
      {controls.includes("funnel") ? (
        <Select
          className="fb-select"
          value={f.funnel}
          onChange={(value) => { f.setFunnel(value); f.setLeadFilter(null); }}
          options={[
            { value: "all", label: "Все воронки" },
            ...(o.data?.funnels ?? []),
          ]}
        />
      ) : null}
      {controls.includes("mgr") ? (
        <Select
          className="fb-select"
          value={f.mgr}
          onChange={(v) => { f.setMgr(v); f.setLeadFilter(null); }}
          options={opts("Все менеджеры", o.data?.managers ?? [])}
        />
      ) : null}
      {controls.includes("source") ? (
        <Select
          className="fb-select"
          value={f.source}
          onChange={f.setSource}
          options={opts("Все источники", o.data?.sources ?? [])}
        />
      ) : null}
    </div>
  );
}
