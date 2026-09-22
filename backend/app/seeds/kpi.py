"""KPI-базлайны и карточки дашборда (BASE / PMUL / PLABEL / renderKpis)."""

# Базовые значения за 30 дней (BASE в прототипе)
BASE = {
    "leads": 342,
    "qual": 218,
    "deals": 96,
    "invoices": 78,
    "payments": 61,
    "revenue": 4820000,
    "margin": 1640000,
    "spend": 356000,
    "first_contact": 8.4,
    "overdue": 14,
}

# Множители периода относительно базлайна 30 дней
PMUL = {"today": 0.045, "7": 0.28, "30": 1, "quarter": 3.05}
PLABEL = {"today": "за сегодня", "7": "за 7 дней", "30": "за 30 дней", "quarter": "за квартал"}

# Карточки KPI (renderKpis). kind: money|count|minutes|percent.
# scales — умножать base на PMUL; static_value — готовая строка (не скалируется).
# drill — семантическая ссылка для фронтенда: "analytics" | "monitor:<ptype>".
KPI_CARDS = [
    {
        "key": "leads", "label": "Лиды", "icon": "i-indigo",
        "svg": '<path d="M16 8a4 4 0 10-8 0 4 4 0 008 0zM4 20a8 8 0 0116 0" stroke-linecap="round"/>',
        "kind": "count", "base_key": "leads", "scales": True,
        "trend": "up", "delta": "+12%", "spark": [8, 10, 9, 12, 11, 14, 13, 16], "drill": None,
    },
    {
        "key": "deals", "label": "Сделки", "icon": "i-cyan",
        "svg": '<path d="M9 12l2 2 4-4M7.8 3.5a2 2 0 011.6-.9h5.2a2 2 0 011.6.9l1.9 2.6a2 2 0 01.4 1.2v8.4a2 2 0 01-2 2H7.5a2 2 0 01-2-2V7.3a2 2 0 01.4-1.2z" stroke-linejoin="round"/>',
        "kind": "count", "base_key": "deals", "scales": True,
        "trend": "up", "delta": "+8%", "spark": [5, 6, 6, 7, 8, 7, 9, 10], "drill": None,
    },
    {
        "key": "revenue", "label": "Выручка", "icon": "i-green",
        "svg": '<path d="M12 2v20M17 6H10a3 3 0 000 6h4a3 3 0 010 6H6" stroke-linecap="round"/>',
        "kind": "money", "base_key": "revenue", "scales": True,
        "trend": "up", "delta": "+15%", "spark": [10, 11, 10, 13, 14, 13, 16, 18], "drill": None,
    },
    {
        "key": "margin", "label": "Маржа", "icon": "i-green",
        "svg": '<path d="M4 18L10 12l4 4 6-8M20 8h-4M20 8v4" stroke-linecap="round" stroke-linejoin="round"/>',
        "kind": "money", "base_key": "margin", "scales": True,
        "trend": "up", "delta": "+11%", "spark": [7, 8, 8, 9, 11, 10, 12, 13], "drill": None,
    },
    {
        "key": "spend", "label": "Расход на рекламу", "icon": "i-amber",
        "svg": '<path d="M12 3v18M6 8h9a3 3 0 010 6H8a3 3 0 000 6h10" stroke-linecap="round"/>',
        "kind": "money", "base_key": "spend", "scales": True,
        "trend": "warn", "delta": "+4%", "spark": [9, 10, 9, 11, 10, 11, 10, 11], "drill": "analytics",
    },
    {
        "key": "romi", "label": "ROMI · платные каналы", "icon": "i-indigo",
        "svg": '<circle cx="12" cy="12" r="9"/><path d="M12 8v8M9 10c0-1 1-1.6 3-1.6s3 .6 3 1.8c0 2.4-6 1.2-6 3.6 0 1.2 1 1.8 3 1.8s3-.6 3-1.6" stroke-linecap="round"/>',
        "kind": "percent", "base_key": None, "scales": False, "static_value": "+197%",
        "trend": "up", "delta": "+18 п.п.", "spark": [6, 7, 8, 9, 10, 12, 13, 15], "drill": "analytics",
    },
    {
        "key": "first_contact", "label": "Медиана первого контакта", "icon": "i-cyan",
        "svg": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2" stroke-linecap="round" stroke-linejoin="round"/>',
        "kind": "minutes", "base_key": "first_contact", "scales": False,
        "trend": "up", "delta": "−1,3 мин", "spark": [12, 11, 11, 10, 9, 9, 8, 8], "drill": None,
    },
    {
        "key": "overdue", "label": "Просрочки регламента", "icon": "i-red",
        "svg": '<path d="M12 8v4M12 16h.01M10.3 3.9L2.6 17.5a2 2 0 001.7 3h15.4a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z" stroke-linecap="round" stroke-linejoin="round"/>',
        "kind": "count", "base_key": "overdue", "scales": True,
        "trend": "down", "delta": "−6%", "spark": [18, 16, 15, 14, 14, 13, 12, 11],
        "drill": "monitor:overdue_contact",
    },
]
