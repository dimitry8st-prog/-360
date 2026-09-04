from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import Settings


class AIServiceError(Exception):
    """Base class for controlled AI errors."""


class AIConfigurationError(AIServiceError):
    pass


class AIProviderError(AIServiceError):
    pass


@dataclass(frozen=True)
class AIAnswer:
    text: str
    provider: str
    model: str
    is_stub: bool = False


class AIService:
    def __init__(self, cfg: Settings):
        self.cfg = cfg

    @staticmethod
    def mask_pii(value: str) -> str:
        value = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[EMAIL СКРЫТ]", value)
        return re.sub(r"(?<!\d)(?:\+?\d[\d ()-]{8,}\d)(?!\d)", "[ТЕЛЕФОН СКРЫТ]", value)

    def _system_prompt(self) -> str:
        return (
            "Ты ДИС — финансовый аналитик и помощник руководителя. Отвечай по-русски, "
            "кратко и человеческим языком. Используй только переданный контекст файла; "
            "не выдумывай значения. Сначала дай вывод, затем факты и ограничения. "
            "Если данных недостаточно, скажи об этом явно."
        )

    def answer(self, question: str, context: dict[str, Any] | None, history: list[dict[str, str]]) -> AIAnswer:
        safe_question = self.mask_pii(question.strip())
        if not self.cfg.openai_api_key:
            summary = (context or {}).get("summary", "Файл не выбран.")
            return AIAnswer(
                text=(
                    "Демо-режим: AI-ключ не настроен, поэтому я не отправляю данные внешнему провайдеру. "
                    f"Проверенный локальный результат: {summary} "
                    "Для смыслового ответа добавьте OPENAI_API_KEY; расчёты и графики продолжают работать локально."
                ),
                provider="local",
                model="deterministic-stub",
                is_stub=True,
            )
        messages = [{"role": "system", "content": self._system_prompt()}]
        messages.extend(history[-8:])
        messages.append({"role": "user", "content": safe_question + "\n\nКонтекст файла:\n" + json.dumps(context or {}, ensure_ascii=False, default=str)[:16000]})
        try:
            response = httpx.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.cfg.openai_api_key}"},
                json={"model": self.cfg.openai_model, "messages": messages},
                timeout=60,
            )
            response.raise_for_status()
            text = response.json()["choices"][0]["message"]["content"]
            return AIAnswer(text=text, provider="openai", model=self.cfg.openai_model)
        except (httpx.HTTPError, KeyError, IndexError, TypeError) as exc:
            raise AIProviderError("AI-провайдер временно недоступен. Локальный анализ файла сохранён.") from exc
