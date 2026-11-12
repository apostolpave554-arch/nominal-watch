# nominal.top → Telegram: новые офферы по Аргентине

Каждые ~10 минут GitHub Actions забирает список предложений с nominal.top
с фильтром `geo=AR` и присылает в Telegram только новые.
Бесплатно: GitHub Actions в **публичном** репозитории не ограничен по минутам.

## Найденные эндпоинты

Сайт — Next.js с серверным рендерингом. JSON-API для каталога нет: данные приходят уже в HTML.

| Что | URL |
|---|---|
| Офферы по GEO | `GET https://nominal.top/{locale}/catalog/offers?geo=AR&page=N` |
| Запросы по GEO | `GET https://nominal.top/{locale}/catalog/requests?geo=AR&page=N` |
| Компактный список | тот же URL + `&view=list` |
| Карточка оффера | `GET https://nominal.top/{locale}/catalog/{раздел}/{slug}` |
| Поиск (JSON) | `GET https://nominal.top/api/search?l={locale}&q={текст}` |
| Служебные | `POST /api/t` (аналитика), `/api/banners/{id}/click`, `/api/banners/view` |

Другие фильтры каталога (можно добавить в запрос): `audience`, `section`, `geo`, `method`
и ещё фасеты «Вертикали», «Качество трафика», «Тип KYC». Локали: `ru`, `en`, `es`, `ko`, `hi`.
Уникальный ключ оффера — его slug (`catalog/psp/loopex-terms`).

## Установка (≈5 минут)

1. **Бот.** В Telegram откройте @BotFather → `/newbot` → скопируйте токен.
   Напишите своему боту любое сообщение.
2. **chat_id.** Откройте в браузере `https://api.telegram.org/bot<ТОКЕН>/getUpdates`
   и возьмите число из `"chat":{"id": ...}`.
   (Для канала: добавьте бота админом, id будет вида `-100…`.)
3. **Репозиторий.** Создайте на GitHub новый **публичный** репозиторий и загрузите туда
   все файлы из этой папки, включая `.github/workflows/watch.yml`.
4. **Секреты.** Settings → Secrets and variables → Actions → *New repository secret*:
   - `TELEGRAM_BOT_TOKEN` — токен бота
   - `TELEGRAM_CHAT_ID` — ваш chat_id
5. **Запуск.** Вкладка Actions → `nominal-watch` → *Run workflow*.
   Первое сообщение: «Мониторинг запущен…». Дальше — только новые офферы.

Необязательные настройки (Settings → Secrets and variables → Actions → вкладка *Variables*):

- `GEO` — другая страна (`BR`, `MX`, …), по умолчанию `AR`
- `LOCALE` — язык сообщений, по умолчанию `ru`
- `SECTIONS` — `offers,requests`, чтобы получать ещё и запросы

## Локальная проверка

```bash
pip install -r requirements.txt
```

```bash
DRY_RUN=1 SEND_EXISTING=1 python nominal_watch.py
```

## Важно знать

- GitHub запускает cron с задержкой, иногда до 10–20 минут в часы пик. Для такого мониторинга это нормально.
- В публичном репозитории GitHub отключает расписание, если в репозитории 60 дней не было активности.
  Коммиты `seen.json` при новых офферах считаются активностью. Если офферов долго нет и придёт
  письмо об отключении, нажмите *Enable workflow*.
- Если сайт поменяет вёрстку и парсер найдёт 0 карточек, запуск упадёт, а GitHub пришлёт письмо.
  Состояние при этом не стирается, так что лавины старых офферов не будет.
- В приватном репозитории бесплатно 2000 минут в месяц. Тогда поставьте cron `*/30 * * * *`.
