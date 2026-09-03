// Конфигурация навигации и мета страниц — соответствует прототипу (PAGE_META).
import type { ComponentType } from "react";

import {
  AdminIcon,
  AiIcon,
  AnalyticsIcon,
  DashboardIcon,
  IntegrationsIcon,
  MonitorIcon,
  RomiIcon,
} from "./icons";

export interface NavItem {
  key: string;
  path: string;
  label: string;
  subtitle: string;
  section: string;
  Icon: ComponentType;
  badge?: number;
}

export const NAV_ITEMS: NavItem[] = [
  {
    key: "dashboard",
    path: "/dashboard",
    label: "Дашборд",
    subtitle: "Единая картина по обработке лидов и деньгам",
    section: "Обзор",
    Icon: DashboardIcon,
  },
  {
    key: "monitor",
    path: "/monitor",
    label: "Мониторинг Битрикс24",
    subtitle: "Контроль регламента в реальном времени",
    section: "Обзор",
    Icon: MonitorIcon,
  },
  {
    key: "analytics",
    path: "/analytics",
    label: "Сквозная аналитика",
    subtitle: "Реклама → визит → звонок → сделка → оплата → маржа",
    section: "Маркетинг",
    Icon: AnalyticsIcon,
  },
  {
    key: "romi",
    path: "/romi",
    label: "ROMI и рекомендации",
    subtitle: "Возврат на рекламу и оптимизация бюджета",
    section: "Маркетинг",
    Icon: RomiIcon,
  },
  {
    key: "ai",
    path: "/ai",
    label: "AI-инсайты",
    subtitle: "Интерпретация, закономерности и риски",
    section: "Маркетинг",
    Icon: AiIcon,
  },
  {
    key: "settings",
    path: "/settings",
    label: "Настройки",
    subtitle: "Юрлица, воронки, SLA, сотрудники и планы",
    section: "Настройка",
    Icon: AdminIcon,
  },
  {
    key: "integrations",
    path: "/integrations",
    label: "Интеграции",
    subtitle: "Подключения источников и проверка статуса",
    section: "Настройка",
    Icon: IntegrationsIcon,
  },
];

// Порядок секций в сайдбаре.
export const NAV_SECTIONS = ["Обзор", "Маркетинг", "Настройка"];
