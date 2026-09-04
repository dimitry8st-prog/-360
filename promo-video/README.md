# Проморолик «ДИС Аналитик 360»

Рекламно-демонстрационный ролик 16:9 (1920×1080, ~60 с). Логика сайта не меняется.

Фон: «Время, вперёд!» Свиридова — свободно лицензированный ремикс Mark Subbotin (Jamendo, CC BY 3.0), не синтез.
Озвучка: мужской русский голос `ru-RU-DmitryNeural`. Если WAV нет, ролик собирается без голоса.

## Предпросмотр

```bash
cd promo-video
export PATH="/c/Users/user/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-9.0-full_build/bin:$PATH"
npm run check
npm run dev
```

## Рендер

```bash
cd promo-video
export PATH="/c/Users/user/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-9.0-full_build/bin:$PATH"
npx hyperframes@0.7.94 render --skill=product-launch-video --quality high --output output/dis-analyst-360.mp4
```

Без озвучки: удалите `assets/voice/*.wav` и соберите заново (`audio_meta.json` с пустым `voices`), затем тот же render.

Итог: `promo-video/output/dis-analyst-360.mp4`.

Текущий файл проверен: **1920×1080, 60 с, H.264 + AAC**, ~4.1 МБ (рендер `--quality draft` из‑за режима низкой памяти). Для более высокого битрейта:

```bash
npx hyperframes@0.7.94 render --skill=product-launch-video --quality high --output output/dis-analyst-360.mp4
```

