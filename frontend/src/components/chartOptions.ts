// Построители опций ECharts — перенос конфигураций из прототипа.
import type { EChartsOption } from "echarts";

import type { ExpenseByArticle, FunnelStage, RevenueSeries, RomiByChannel, Source } from "@/api/dashboard";
import type { CampaignBubble, RomiChannelChart } from "@/api/romi";

// Вертикальный градиент для областей (объектная форма — без полного echarts).
function vGradient(from: string, to: string) {
  return {
    type: "linear" as const, x: 0, y: 0, x2: 0, y2: 1,
    colorStops: [
      { offset: 0, color: from },
      { offset: 1, color: to },
    ],
  };
}

const AXIS = {
  axisLine: { lineStyle: { color: "#E4E7EF" } },
  axisLabel: { color: "#8A92A6", fontSize: 11, fontFamily: "Inter" },
  axisTick: { show: false },
};
const SPLIT = { splitLine: { lineStyle: { color: "#F1F2F7" } } };

const rub = (v: number) => Math.round(v).toLocaleString("ru-RU") + " ₽";

export function funnelOption(stages: FunnelStage[]): EChartsOption {
  return {
    tooltip: { trigger: "item", formatter: "{b}: {c}" },
    series: [{
      type: "funnel", left: "6%", right: "6%", top: 6, bottom: 6, minSize: "32%", gap: 3,
      label: { position: "inside", color: "#fff", fontWeight: 600, fontFamily: "Inter", fontSize: 12, formatter: "{b}\n{c}" },
      itemStyle: { borderWidth: 0, borderRadius: 6 },
      color: ["#635BFF", "#7B6FF2", "#1BA9C7", "#0FA968", "#12B76A"],
      data: stages.map((s) => ({ value: s.value, name: s.label })),
    }],
  };
}

export function donutOption(sources: Source[]): EChartsOption {
  return {
    tooltip: { trigger: "item", formatter: "{b}: {c} ({d}%)" },
    legend: { bottom: 0, icon: "circle", itemWidth: 8, itemHeight: 8, textStyle: { color: "#6B7488", fontSize: 11, fontFamily: "Inter" } },
    series: [{
      type: "pie", radius: ["52%", "74%"], center: ["50%", "44%"], avoidLabelOverlap: true,
      itemStyle: { borderColor: "#fff", borderWidth: 3, borderRadius: 5 }, label: { show: false },
      data: sources.map((c) => ({ value: c.leads, name: c.short_name, itemStyle: { color: c.color } })),
    }],
  };
}

export function revenueOption(s: RevenueSeries): EChartsOption {
  return {
    tooltip: { trigger: "axis", valueFormatter: (v) => rub(v as number) },
    legend: { right: 0, top: 0, icon: "roundRect", itemWidth: 10, itemHeight: 10, textStyle: { color: "#6B7488", fontSize: 11 } },
    grid: { left: 8, right: 8, top: 34, bottom: 4, containLabel: true },
    xAxis: { type: "category", data: s.days, boundaryGap: false, ...AXIS },
    yAxis: {
      type: "value", ...AXIS, ...SPLIT,
      axisLabel: { color: "#8A92A6", fontSize: 11, formatter: (v: number) => (v >= 1e6 ? v / 1e6 + "M" : v / 1e3 + "k") },
    },
    series: [
      {
        name: "Выручка", type: "line", smooth: true, data: s.revenue, symbol: "none",
        lineStyle: { width: 2.5, color: "#635BFF" },
        areaStyle: { color: vGradient("rgba(99,91,255,.22)", "rgba(99,91,255,0)") },
      },
      {
        name: "Маржа", type: "line", smooth: true, data: s.margin, symbol: "none",
        lineStyle: { width: 2.5, color: "#12B76A" },
        areaStyle: { color: vGradient("rgba(18,183,106,.18)", "rgba(18,183,106,0)") },
      },
    ],
  };
}

export function romiBarOption(rows: RomiByChannel[]): EChartsOption {
  const data = rows.map((x) => x.romi).reverse();
  const names = rows.map((x) => x.short_name).reverse();
  return {
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, valueFormatter: (v) => v + "%" },
    grid: { left: 8, right: 16, top: 10, bottom: 4, containLabel: true },
    xAxis: { type: "value", ...AXIS, ...SPLIT, axisLabel: { color: "#8A92A6", fontSize: 11, formatter: "{value}%" } },
    yAxis: { type: "category", data: names, ...AXIS },
    series: [{
      type: "bar", barWidth: "52%",
      data: data.map((v) => ({ value: v, itemStyle: { color: v >= 200 ? "#12B76A" : v >= 80 ? "#F79009" : "#F04438", borderRadius: [0, 6, 6, 0] } })),
      label: { show: true, position: "right", formatter: "{c}%", color: "#6B7488", fontSize: 11, fontFamily: "Space Grotesk", fontWeight: 600 },
    }],
  };
}

export function expensesBarOption(rows: ExpenseByArticle[]): EChartsOption {
  return {
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, valueFormatter: (v) => rub(v as number) },
    grid: { left: 8, right: 16, top: 8, bottom: 4, containLabel: true },
    xAxis: { type: "value", ...AXIS, ...SPLIT, axisLabel: { color: "#8A92A6", fontSize: 11, formatter: (v: number) => v >= 1e6 ? `${v / 1e6}M` : `${v / 1e3}k` } },
    yAxis: { type: "category", data: rows.map((x) => x.article).reverse(), ...AXIS, axisLabel: { color: "#6B7488", fontSize: 10, width: 150, overflow: "truncate" } },
    series: [{
      type: "bar", barWidth: "52%",
      data: rows.map((x) => ({ value: x.amount, itemStyle: { color: x.source === "automatic" ? "#635BFF" : "#E0803B", borderRadius: [0, 6, 6, 0] } })).reverse(),
      label: { show: true, position: "right", formatter: (p: unknown) => rub(Number((p as { value: number }).value)), color: "#6B7488", fontSize: 10 },
    }],
  };
}

export function romiSpendMarginOption(rows: RomiChannelChart[]): EChartsOption {
  return {
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, valueFormatter: (v) => rub(v as number) },
    legend: { top: 0, right: 0, icon: "roundRect", itemWidth: 10, itemHeight: 10, textStyle: { color: "#6B7488", fontSize: 11 } },
    grid: { left: 8, right: 8, top: 34, bottom: 4, containLabel: true },
    xAxis: { type: "category", data: rows.map((d) => d.short_name), ...AXIS, axisLabel: { color: "#8A92A6", fontSize: 10, interval: 0, rotate: 18 } },
    yAxis: { type: "value", ...AXIS, ...SPLIT, axisLabel: { color: "#8A92A6", fontSize: 11, formatter: (v: number) => v / 1e3 + "k" } },
    series: [
      { name: "Расход", type: "bar", barWidth: "28%", data: rows.map((d) => d.spend), itemStyle: { color: "#E0803B", borderRadius: [5, 5, 0, 0], opacity: 0.85 } },
      { name: "Маржа", type: "bar", barWidth: "28%", data: rows.map((d) => ({ value: d.margin, itemStyle: { color: "#12B76A", borderRadius: [5, 5, 0, 0] } })) },
    ],
  };
}

export function bubbleOption(camps: CampaignBubble[]): EChartsOption {
  const data = camps.filter((c) => c.romi !== null && c.spend !== null);
  return {
    tooltip: {
      formatter: (p: unknown) => {
        const d = (p as { data: { value: [number, number, number, string] } }).data.value;
        return `${d[3]}<br/>Расход: ${Math.round(d[0]).toLocaleString("ru-RU")} ₽<br/>ROMI: ${d[1]}%<br/>Выручка: ${Math.round(d[2]).toLocaleString("ru-RU")} ₽`;
      },
    },
    grid: { left: 8, right: 16, top: 16, bottom: 4, containLabel: true },
    xAxis: { name: "Расход, ₽", nameLocation: "middle", nameGap: 30, nameTextStyle: { color: "#8A92A6", fontSize: 11 }, type: "value", ...AXIS, ...SPLIT, axisLabel: { color: "#8A92A6", fontSize: 11, formatter: (v: number) => v / 1e3 + "k" } },
    yAxis: { name: "ROMI, %", type: "value", ...AXIS, ...SPLIT, axisLabel: { color: "#8A92A6", fontSize: 11, formatter: "{value}%" } },
    series: [{
      type: "scatter",
      symbolSize: (d: number[]) => Math.max(14, Math.sqrt(d[2]) / 22),
      data: data.map((c) => ({ value: [c.spend, c.romi, c.revenue, c.name], itemStyle: { color: c.color, opacity: 0.82, borderColor: "#fff", borderWidth: 2 } })),
      label: { show: true, formatter: (p: unknown) => (p as { data: { value: [number, number] } }).data.value[1] + "%", position: "top", color: "#6B7488", fontSize: 10, fontFamily: "Space Grotesk", fontWeight: 600 },
    }],
  };
}
