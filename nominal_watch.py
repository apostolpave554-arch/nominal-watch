"""
Мониторинг новых предложений (offers) на nominal.top по выбранному GEO
с отправкой уведомлений в Telegram.

Источник данных: страница каталога рендерится на сервере (Next.js SSR),
отдельного JSON-API для списка нет, поэтому парсим HTML:

    GET https://nominal.top/{LOCALE}/catalog/{SECTION}?geo={GEO}&page={N}

    SECTION = offers   — предложения
    SECTION = requests — запросы (можно включить через SECTIONS=offers,requests)

Каждая карточка — <a class="card card-link" href="/{locale}/catalog/<раздел>/<slug>">,
slug уникален и используется как ключ "уже видели".

Переменные окружения:
    TELEGRAM_BOT_TOKEN   токен бота от @BotFather            (обязательно)
    TELEGRAM_CHAT_ID     id чата/канала для уведомлений      (обязательно)
    GEO                  код страны, по умолчанию AR (Аргентина)
    LOCALE               ru | en | es | ko | hi, по умолчанию ru
    SECTIONS             offers (по умолчанию) или offers,requests
    STATE_FILE           файл состояния, по умолчанию seen.json
    SEND_EXISTING        1 — при первом запуске прислать все текущие офферы
    DRY_RUN              1 — ничего не отправлять, только печатать
"""

from __future__ import annotations

import html
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE = "https://nominal.top"
GEO = os.getenv("GEO", "AR").upper()
LOCALE = os.getenv("LOCALE", "ru")
SECTIONS = [s.strip() for s in os.getenv("SECTIONS", "all,offers,requests").split(",") if s.strip()]
STATE_FILE = Path(os.getenv("STATE_FILE", "seen.json"))
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
SEND_EXISTING = os.getenv("SEND_EXISTING") == "1"
DRY_RUN = os.getenv("DRY_RUN") == "1"
MAX_PAGES = 50

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept-Language": f"{LOCALE},en;q=0.8",
}


@dataclass
class Offer:
    key: str              # slug-путь без локали: catalog/psp/rebill-terms
    url: str
    kind: str             # Offer / Request (бейдж)
    title: str
    company: str
    date: str             # ISO из <time datetime>
    date_text: str
    description: str = ""
    audience: list[str] = field(default_factory=list)   # "For:" чипы
    fields: list[tuple[str, str]] = field(default_factory=list)
    methods: list[str] = field(default_factory=list)
    geos: list[str] = field(default_factory=list)
    extra_geos: int = 0
    rate: str = ""        # ставка, напр. "IN 3%"
    kind_type: str = "offer"      # offer / request / company
    audience_label: str = ""      # "For" / "Looking for"


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def fetch(url: str, params: dict) -> str:
    last_err = None
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=30)
            r.raise_for_status()
            return r.text
        except requests.RequestException as e:
            last_err = e
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"Не удалось загрузить {url} {params}: {last_err}")


def parse_cards(page_html: str) -> list[Offer]:
    soup = BeautifulSoup(page_html, "html.parser")
    out: list[Offer] = []
    for a in soup.select("a.card.card-link[href*='/catalog/']"):
        href = a.get("href", "")
        key = re.sub(r"^/[a-z]{2}/", "", href).split("?")[0]

        header = a.find("div")
        badge = a.select_one(".badge")
        time_el = a.find("time")
        is_company = badge is None and time_el is None  # карточка компании из общего каталога

        ps = a.find_all("p", recursive=False)
        title, description, company_el = "", "", None
        audience: list[str] = []
        audience_label = ""
        methods: list[str] = []

        if is_company:
            name_el = header.select_one("p") if header else None
            title = clean(name_el.get_text()) if name_el else ""
            for p in ps:
                if "line-clamp-2" in (p.get("class") or []):
                    description = clean(p.get_text())
            cats = a.find("div", class_="flex-wrap", recursive=False)
            if cats:
                audience = [clean(c.get_text()) for c in cats.select(".chip")]
            kind = "Компания" if LOCALE == "ru" else "Company"
            kind_type = "company"
        else:
            company_el = header.select_one("span.truncate span.truncate") if header else None
            if company_el is None and header:
                company_el = header.select_one("span.truncate")
            title = clean(ps[0].get_text()) if ps else ""
            for p in ps[1:]:
                chips = p.select(".chip")
                label_el = p.select_one(".text-muted")
                if chips and label_el:
                    audience = [clean(c.get_text()) for c in chips]
                    audience_label = clean(label_el.get_text()).rstrip(":")
                elif "line-clamp-2" in (p.get("class") or []):
                    description = clean(p.get_text())
            kind = clean(badge.get_text()) if badge else ""
            kind_type = "request" if badge and "badge-accent" in badge.get("class", []) else "offer"

        fields = []
        for span in a.select("div.space-y-2 span.min-w-0"):
            label = span.select_one(".text-muted")
            value = span.select_one(".font-medium")
            if label and value:
                fields.append((clean(label.get_text()).rstrip(":"), clean(value.get_text())))
        # методы оплаты внутри блока условий (у запросов)
        for p in a.select("div.space-y-2 > p"):
            if not p.select_one(".text-muted"):
                methods += [clean(c.get_text()) for c in p.select(".chip")]

        geos, extra, rate = [], 0, ""
        footer = a.select_one("div.border-t")
        if footer:
            rate_el = footer.select_one("p.font-numeral")
            if rate_el:
                rate = clean(rate_el.get_text(" "))
            mbox = footer.select_one("span.flex-wrap")
            if mbox:
                methods += [clean(c.get_text()) for c in mbox.select(".chip")]
            geos = [s["title"] for s in footer.select("span[title]")]
            more = footer.select_one("span.text-faint")
            if more:
                m = re.search(r"\d+", more.get_text())
                extra = int(m.group()) if m else 0

        out.append(
            Offer(
                key=key,
                url=BASE + href,
                kind=kind,
                kind_type=kind_type,
                audience_label=audience_label,
                title=title,
                company=clean(company_el.get_text()) if company_el else "",
                date=time_el.get("datetime", "") if time_el else "",
                date_text=clean(time_el.get_text()) if time_el else "",
                description=description,
                audience=audience,
                fields=fields,
                methods=methods,
                geos=geos,
                extra_geos=extra,
                rate=rate,
            )
        )
    return out


def has_next_page(page_html: str, page: int) -> bool:
    return re.search(rf'href="\?[^"]*page={page + 1}\b', page_html) is not None


def collect(section: str) -> list[Offer]:
    # "all" — общий каталог компаний (/catalog), остальные — подразделы (/catalog/<section>)
    url = f"{BASE}/{LOCALE}/catalog" + ("" if section == "all" else f"/{section}")
    result: dict[str, Offer] = {}
    for page in range(1, MAX_PAGES + 1):
        params = {"geo": GEO}
        if page > 1:
            params["page"] = page
        page_html = fetch(url, params)
        cards = parse_cards(page_html)
        new_here = [c for c in cards if c.key not in result]
        for c in new_here:
            result[c.key] = c
        if not new_here or not has_next_page(page_html, page):
            break
        time.sleep(1)
    return list(result.values())


def format_message(o: Offer) -> str:
    e = html.escape
    icon = {"offer": "🆕", "request": "📩", "company": "🏢"}.get(o.kind_type, "🆕")
    lines = [f"{icon} <b>{e(o.title)}</b>"]
    meta = " · ".join(x for x in (e(o.kind), e(o.company), e(o.date_text)) if x)
    if meta:
        lines.append(f"<i>{meta}</i>")
    if o.description:
        lines.append("")
        lines.append(e(o.description))
    if o.rate or o.audience:
        lines.append("")
    if o.rate:
        lines.append(f"💰 <b>{e(o.rate)}</b>")
    if o.audience:
        prefix = f"{e(o.audience_label)}: " if o.audience_label else ""
        lines.append(f"👥 {prefix}{e(', '.join(o.audience))}")
    for k, v in o.fields:
        lines.append(f"• {e(k)}: {e(v)}")
    if o.methods:
        lines.append(f"💳 {e(', '.join(o.methods))}")
    if o.geos:
        g = ", ".join(o.geos)
        if o.extra_geos:
            g += f" +{o.extra_geos}"
        lines.append(f"🌍 {e(g)}")
    lines.append("")
    lines.append(f'<a href="{e(o.url)}">Открыть на nominal.top</a>')
    return "\n".join(lines)[:4000]


def send_telegram(text: str) -> None:
    if DRY_RUN:
        print("---- DRY RUN ----\n" + text + "\n")
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    for _ in range(5):
        r = requests.post(url, json=payload, timeout=30)
        if r.status_code == 429:  # flood limit
            wait = r.json().get("parameters", {}).get("retry_after", 5)
            time.sleep(wait + 1)
            continue
        if not r.ok:
            raise RuntimeError(f"Telegram error {r.status_code}: {r.text}")
        time.sleep(1.1)
        return
    raise RuntimeError("Telegram: превышено число попыток")


def load_state() -> dict | None:
    if not STATE_FILE.exists():
        return None
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")


SECTION_NAMES = {"all": "компании", "offers": "предложения", "requests": "запросы"}


def main() -> int:
    if not DRY_RUN and (not BOT_TOKEN or not CHAT_ID):
        print("Нужны TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID (или DRY_RUN=1)", file=sys.stderr)
        return 2

    state = load_state()
    first_run = state is None
    seen: dict = (state or {}).get("seen", {})
    # старые файлы состояния (до появления поля sections) отслеживали только offers
    known_sections = set((state or {}).get("sections", ["offers"] if state else []))
    fresh_sections = [s for s in SECTIONS if s not in known_sections]

    current: list[Offer] = []
    silent_keys: set[str] = set()   # элементы новых разделов — запоминаем без отправки
    counts_by_section: dict[str, int] = {}
    for section in SECTIONS:
        items = collect(section)
        print(f"[{section}] geo={GEO}: найдено {len(items)}")
        current.extend(items)
        counts_by_section[section] = len(items)
        if section in fresh_sections and not SEND_EXISTING:
            silent_keys.update(o.key for o in items)

    if not current:
        # Пустой результат почти наверняка означает, что сайт поменял вёрстку
        # или недоступен — состояние не трогаем, падаем, чтобы GitHub прислал письмо.
        print("Не найдено ни одной карточки — проверьте разметку сайта.", file=sys.stderr)
        return 1

    def persist() -> None:
        save_state({"geo": GEO, "sections": sorted(known_sections | set(SECTIONS)), "seen": seen})

    unique: dict[str, Offer] = {}
    for o in current:
        unique.setdefault(o.key, o)
    new = [o for k, o in unique.items() if k not in seen and k not in silent_keys]
    new.sort(key=lambda o: o.date)  # старые первыми, чтобы в чате был хронологический порядок

    if fresh_sections and not SEND_EXISTING:
        names = ", ".join(SECTION_NAMES.get(s, s) for s in fresh_sections)
        counts = ", ".join(
            f"{SECTION_NAMES.get(s, s)}: {counts_by_section.get(s, 0)}"
            for s in fresh_sections
        )
        head = "✅ Мониторинг nominal.top запущен" if first_run else "➕ Добавлены разделы для отслеживания"
        send_telegram(
            f"{head}\nGEO: <b>{html.escape(GEO)}</b>, разделы: {html.escape(names)}\n"
            f"Сейчас на сайте — {html.escape(counts)}.\nБуду присылать только новые."
        )

    for o in new:
        send_telegram(format_message(o))
        seen[o.key] = {"title": o.title, "date": o.date}
        persist()  # сохраняем после каждой отправки

    for k, o in unique.items():
        seen.setdefault(k, {"title": o.title, "date": o.date})
    persist()
    print(f"Новых отправлено: {len(new)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
