---
format: 1920x1080
duration: 60s
message: Загрузил. Спросил. Понял.
arc: Hook → Upload → Quality → Chat → Charts → Live status → Lockup
audience: преподаватель и потенциальный заказчик
mode: autonomous
music: Sviridov Time Forward, CC BY Jamendo remix ingest (not generated)
---

## Video direction

Navy canvas `#123b5d`, orange `#f58220`, green `#2e9d68`. Large Russian titles sit in the top band; real UI stills occupy the middle; captions own the bottom 17%. Motion: fade/slide reveals paced to VO, count-up on quality stats, pie then scatter swap, status chips, icon assemble. No passwords, emails, or `.env`.

## Frame 1 — Hook

- status: animated
- src: compositions/frames/01-hook.html
- duration: 6s
- transition_in: crossfade
- scene: Маскот и название продукта
- voiceover: ДИС Аналитик 360 — персональный AI-помощник для анализа данных.
- poster: 2.2
- asset_candidates: assets/dis-mascot.jpg, capture/screenshots/01-landing.png
- blueprint: compose
- type: hook

Scene 1 (0.0–1.4s): Navy ground + orange glow behind mascot (center-left, large). Layout: hero-left.
Scene 2 (1.4–3.2s): Title «ДИС Аналитик 360» rises right of mascot. Layout: split lockup.
Scene 3 (3.2–5.0s): Super «Данные становятся понятными» in orange. Hold. Layout: lockup + tagline.

## Frame 2 — Upload

- status: animated
- src: compositions/frames/02-upload.html
- duration: 8s
- transition_in: crossfade
- scene: Загрузка sample_sales.csv
- voiceover: Загрузите таблицу, документ или изображение.
- poster: 4
- asset_candidates: capture/screenshots/02-dashboard.png
- blueprint: compose
- type: demo

Scene 1 (0.0–2.0s): Dashboard still, cropped to upload card. File chip `sample_sales.csv` enters. Layout: UI card center.
Scene 2 (2.0–5.0s): Format pills CSV · Excel · JSON · PDF · изображения stagger in. Layout: card + pill row.
Scene 3 (5.0–8.0s): Super «CSV • Excel • JSON • PDF • изображения». Hold. Layout: stacked title over UI.

## Frame 3 — Quality

- status: animated
- src: compositions/frames/03-quality.html
- duration: 10s
- transition_in: crossfade
- scene: Проверка качества таблицы
- voiceover: Система проверит качество данных, найдёт пропуски и дубликаты и рассчитает основные показатели.
- poster: 6
- asset_candidates: capture/screenshots/04-analysis.png
- blueprint: compose
- type: proof

Scene 1 (0.0–2.2s): Metric «строк / колонок» counts in. Layout: 2-up cards.
Scene 2 (2.2–4.4s): «пропуски» card. Layout: 3-up.
Scene 3 (4.4–6.6s): «дубликаты» card. Layout: 4-up.
Scene 4 (6.6–10.0s): Numeric stats (revenue sum/mean) reveal over analysis still. Layout: stats over UI plate.

## Frame 4 — Chat

- status: animated
- src: compositions/frames/04-chat.html
- duration: 10s
- transition_in: crossfade
- scene: Вопрос в чате и ответ ДИС
- voiceover: Задавайте вопросы обычными словами и получайте понятные выводы.
- poster: 6
- asset_candidates: capture/screenshots/03-chat.png
- blueprint: compose
- type: demo

Scene 1 (0.0–3.5s): Chat UI still; user bubble «Проанализируй продажи, найди основные тенденции и риски». Layout: chat column.
Scene 2 (3.5–10.0s): DIS answer bubble with short conclusion. Hold. Layout: two-bubble stack.

## Frame 5 — Charts

- status: animated
- src: compositions/frames/05-charts.html
- duration: 10s
- transition_in: crossfade
- scene: Круговая диаграмма, затем рассеяние
- voiceover: ДИС строит интерактивные графики непосредственно по исходным данным.
- poster: 7
- asset_candidates: capture/screenshots/05-pie.png, capture/screenshots/06-scatter.png
- blueprint: compose
- type: proof

Scene 1 (0.0–4.5s): Real pie chart still, label pie. Layout: full-bleed chart card.
Scene 2 (4.5–8.0s): Swap to scatter. Layout: same card.
Scene 3 (8.0–10.0s): Super «7 видов интерактивных графиков». Hold.

## Frame 6 — Realtime

- status: animated
- src: compositions/frames/06-realtime.html
- duration: 8s
- transition_in: crossfade
- scene: Статусы обработки и сохранение отчёта
- voiceover: Ход обработки отображается в реальном времени, а результаты можно сохранить.
- poster: 5
- asset_candidates: capture/screenshots/03-chat.png
- blueprint: compose
- type: feature

Scene 1 (0.0–1.8s): Chip «Файл загружается». Layout: status stack.
Scene 2 (1.8–3.6s): Chip «Выполняется анализ».
Scene 3 (3.6–5.4s): Chip «График готов» in green.
Scene 4 (5.4–8.0s): Save-report card «Сохранить отчёт .md». Hold.

## Frame 7 — Lockup

- status: animated
- src: compositions/frames/07-finale.html
- duration: 8s
- transition_in: crossfade
- scene: Стек и финальный слоган
- voiceover: ДИС Аналитик 360. Загрузил, спросил, понял.
- poster: 6
- asset_candidates: assets/dis-mascot.jpg
- blueprint: compose
- type: cta

Scene 1 (0.0–3.2s): Icons Docker, FastAPI, PostgreSQL, Redis, логирование assemble. Layout: icon row.
Scene 2 (3.2–6.0s): Wordmark «ДИС Аналитик 360». Layout: center lockup.
Scene 3 (6.0–9.0s): «Загрузил. Спросил. Понял.» then «Автор — Степанов Д. А.» Hold. Layout: stacked finale.
