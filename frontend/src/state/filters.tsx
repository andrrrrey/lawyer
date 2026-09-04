/* eslint-disable react-refresh/only-export-components */
import { createContext, type ReactNode, useContext, useMemo, useState } from "react";

// Глобальные фильтры дашборда/аналитики (период, канал, менеджер, источник)
// и фильтр таблицы лидов. Совпадают с фильтрами прототипа.
export interface FiltersState {
  period: string;
  channel: string;
  mgr: string;
  source: string;
  legalEntity: string;
  funnel: string;
  leadFilter: string | null;
  setPeriod: (v: string) => void;
  setChannel: (v: string) => void;
  setMgr: (v: string) => void;
  setSource: (v: string) => void;
  setLegalEntity: (v: string) => void;
  setFunnel: (v: string) => void;
  setLeadFilter: (v: string | null) => void;
}

const FiltersContext = createContext<FiltersState | null>(null);

export function FiltersProvider({ children }: { children: ReactNode }) {
  const [period, setPeriod] = useState("30");
  const [channel, setChannel] = useState("all");
  const [mgr, setMgr] = useState("all");
  const [source, setSource] = useState("all");
  const [legalEntity, setLegalEntity] = useState("all");
  const [funnel, setFunnel] = useState("all");
  const [leadFilter, setLeadFilter] = useState<string | null>(null);

  const value = useMemo(
    () => ({
      period, channel, mgr, source, legalEntity, funnel, leadFilter,
      setPeriod, setChannel, setMgr, setSource, setLegalEntity, setFunnel, setLeadFilter,
    }),
    [period, channel, mgr, source, legalEntity, funnel, leadFilter],
  );

  return <FiltersContext.Provider value={value}>{children}</FiltersContext.Provider>;
}

export function useFilters(): FiltersState {
  const ctx = useContext(FiltersContext);
  if (!ctx) throw new Error("useFilters must be used within FiltersProvider");
  return ctx;
}
