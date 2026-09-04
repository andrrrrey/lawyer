import { NavLink } from "react-router-dom";

import { useDataSource } from "@/api/integrations";
import { useMonitorStats } from "@/api/monitor";
import { useMe } from "@/api/auth";
import { NAV_ITEMS, NAV_SECTIONS } from "./navConfig";

interface SidebarProps {
  open?: boolean;
  onClose?: () => void;
}

export function Sidebar({ open = false, onClose }: SidebarProps) {
  const mon = useMonitorStats();
  const me = useMe();
  const ds = useDataSource(me.data?.role === "owner");
  const isReal = ds.data?.data_source === "real";

  // Реальный счётчик нарушений на пункте «Мониторинг» (вместо статичного).
  const badgeFor = (key: string): string | null => {
    if (key !== "monitor") return null;
    const n = mon.data?.badge ?? 0;
    if (!n) return null;
    return n > 99 ? "99+" : String(n);
  };

  return (
    <aside className={`sidebar${open ? " open" : ""}`}>
      <div className="brand">
        <div className="logo">L</div>
        <div>
          <b>Lawyer</b>
          <span>Контроль лидов и аналитика</span>
        </div>
      </div>

      <nav className="nav">
        {NAV_SECTIONS.map((section) => (
          <div key={section}>
            <div className="nav-label">{section}</div>
            {NAV_ITEMS.filter((i) => i.section === section).filter((item) => {
              if (me.data?.role === "owner") return true;
              if (me.data?.role === "head") return !["settings", "integrations"].includes(item.key);
              return ["dashboard", "monitor"].includes(item.key);
            }).map((item) => {
              const { Icon } = item;
              const badge = badgeFor(item.key);
              return (
                <NavLink key={item.key} to={item.path} onClick={onClose} className={({ isActive }) => (isActive ? "active" : "")}>
                  <Icon />
                  {item.label}
                  {badge ? <span className="badge">{badge}</span> : null}
                </NavLink>
              );
            })}
          </div>
        ))}
      </nav>

      <div className="side-foot">
        <b>{me.data?.role === "owner" ? (isReal ? "Боевые интеграции" : "Демо-данные") : "Рабочий кабинет"}</b>
        <br />
        Этап 1 · единая система контроля и аналитики
      </div>
    </aside>
  );
}
