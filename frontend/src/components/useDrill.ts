import { useNavigate } from "react-router-dom";

import { useFilters } from "@/state/filters";

// Drill-down переходы (как в прототипе): KPI/плитки → мониторинг/аналитика,
// менеджер/риск → фильтр таблицы лидов.
export function useDrill() {
  const nav = useNavigate();
  const f = useFilters();

  const toDrill = (drill: string | null) => {
    if (!drill) return;
    if (drill.startsWith("monitor:")) nav(`/monitor?ptype=${drill.split(":")[1]}`);
    else if (drill === "analytics") nav("/analytics");
    else if (drill === "romi") nav("/romi");
    else if (drill === "data") nav("/integrations");
  };

  const toManager = (name: string) => {
    f.setMgr([name]);
    f.setLeadFilter(null);
    scrollToLeads();
  };

  const toRiskLeads = () => {
    f.setLeadFilter("risk");
    scrollToLeads();
  };

  return { toDrill, toManager, toRiskLeads };
}

function scrollToLeads() {
  setTimeout(() => {
    document.getElementById("leads-table")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, 80);
}
