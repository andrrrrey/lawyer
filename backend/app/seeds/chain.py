"""Шаги цепочки «реклама → визит → обращение → сделка → оплата → выручка».

Первые два шага (реклама/визиты) статичны; остальные считаются из BASE × период.
kind: count|money. Конверсии между шагами вычисляются в сервисе.
"""

CHAIN_STEPS = [
    {"label": "Реклама", "sub": "кликов", "color": "#8E96AD", "width": 100,
     "base_key": "clicks", "kind": "count", "static": "11 700"},
    {"label": "Визиты", "sub": "сессий", "color": "#635BFF", "width": 82,
     "base_key": "visits", "kind": "count", "static": "9 240"},
    {"label": "Обращения", "sub": "лидов", "color": "#7B6FF2", "width": 60, "base_key": "leads", "kind": "count"},
    {"label": "Сделки", "sub": "создано", "color": "#1BA9C7", "width": 42, "base_key": "deals", "kind": "count"},
    {"label": "Оплаты", "sub": "клиентов", "color": "#0FA968", "width": 30, "base_key": "payments", "kind": "count"},
    {"label": "Выручка по 1С", "sub": "поступило", "color": "#12B76A", "width": 24,
     "glow": True, "base_key": "revenue", "kind": "money"},
]
