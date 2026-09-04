from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
import pandas as pd
import plotly.express as px
from fastapi import UploadFile
from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader

from app.config import Settings


class FileServiceError(Exception): pass
class UnsupportedFileError(FileServiceError): pass
class FileTooLargeError(FileServiceError): pass
class EmptyFileError(FileServiceError): pass
class FileReadError(FileServiceError): pass

ALLOWED = {".csv": "table", ".xlsx": "table", ".xls": "table", ".json": "table", ".pdf": "pdf", ".png": "image", ".jpg": "image", ".jpeg": "image", ".webp": "image"}
ANALYST_MODES = {
    "business": "бизнес-аналитик",
    "finance": "финансовый аналитик",
    "marketing": "маркетинговый аналитик",
}
DEFAULT_QUESTIONS = {
    "business": "О чём документ и на что обратить внимание?",
    "finance": "Какие ключевые числовые показатели есть в документе?",
    "marketing": "Какие темы и формулировки выделяются в материале?",
}
NUMBER_RE = re.compile(
    r"(?:(?:USD|EUR|RUB|₽|руб\.?)\s*)?-?\d{1,3}(?:[ \u00a0,]\d{3})+(?:[.,]\d+)?|-?\d+[.,]\d{2}"
)
WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9]+", re.UNICODE)


class FileService:
    def __init__(self, cfg: Settings): self.cfg = cfg

    def ensure_storage(self) -> None:
        self.cfg.upload_dir.mkdir(parents=True, exist_ok=True)
        self.cfg.output_dir.mkdir(parents=True, exist_ok=True)

    async def save(self, upload: UploadFile) -> tuple[str, str, str, int, Path]:
        self.ensure_storage()
        original = Path(upload.filename or "upload").name
        ext = Path(original).suffix.lower()
        if ext not in ALLOWED:
            raise UnsupportedFileError("Поддерживаются CSV, Excel, JSON, PDF и изображения PNG/JPG/WEBP.")
        file_id = uuid4().hex
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", original) or "upload"
        stored = f"{file_id}_{safe}"
        path = self.cfg.upload_dir / stored
        total = 0
        try:
            with path.open("wb") as target:
                while chunk := await upload.read(1024 * 1024):
                    total += len(chunk)
                    if total > self.cfg.max_file_size_bytes:
                        raise FileTooLargeError(f"Файл превышает лимит {self.cfg.max_file_size}.")
                    target.write(chunk)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        finally:
            await upload.close()
        if not total:
            path.unlink(missing_ok=True)
            raise EmptyFileError("Файл пуст.")
        return file_id, original, ALLOWED[ext], total, path

    def dataframe(self, path: Path) -> pd.DataFrame:
        try:
            ext = path.suffix.lower()
            if ext == ".csv":
                frame = pd.read_csv(path, low_memory=False)
            elif ext in {".xlsx", ".xls"}:
                frame = pd.read_excel(path)
            elif ext == ".json":
                frame = pd.json_normalize(json.loads(path.read_text(encoding="utf-8")))
            else:
                raise FileReadError("Файл не является таблицей.")
        except FileReadError:
            raise
        except Exception as exc:
            raise FileReadError("Файл не удалось прочитать. Проверьте его структуру.") from exc
        return _normalize_dataframe(frame)

    def analyze(self, path: Path, kind: str, mode: str = "business", question: str = "") -> dict[str, Any]:
        mode = mode if mode in ANALYST_MODES else "business"
        question = normalize_text((question or "").strip()[:400])
        if kind == "table":
            result = self._analyze_table(path, mode, question)
        elif kind == "pdf":
            result = self._analyze_pdf(path, mode, question)
        else:
            result = self._analyze_image(path, mode, question)
        return normalize_tree(result)

    def _analyze_table(self, path: Path, mode: str, question: str) -> dict[str, Any]:
        df = self.dataframe(path)
        if df.empty:
            raise EmptyFileError("Таблица не содержит строк.")
        duplicates = int(df.duplicated().sum())
        missing = int(df.isna().sum().sum())
        numeric = list(map(str, df.select_dtypes(include=np.number).columns))
        columns = list(map(str, df.columns))
        empty_cols = [str(col) for col in df.columns if df[col].isna().all()]
        issues: list[str] = []
        findings: list[str] = [f"Режим: {ANALYST_MODES[mode]}."]
        if missing:
            issues.append(f"В таблице {missing} пропусков — стоит проверить полноту данных.")
        if duplicates:
            issues.append(f"Найдено {duplicates} повторяющихся строк.")
        if empty_cols:
            issues.append("Полностью пустые колонки: " + ", ".join(empty_cols[:8]) + ".")
        numeric_stats: dict[str, dict[str, float]] = {}
        for col in numeric[:8]:
            series = pd.to_numeric(df[col], errors="coerce")
            numeric_stats[col] = {
                "sum": _as_float(series.sum()),
                "mean": _as_float(series.mean()),
                "min": _as_float(series.min()),
                "max": _as_float(series.max()),
            }
        categories: dict[str, list[str]] = {}
        for col in df.select_dtypes(exclude=np.number).columns[:4]:
            top = df[col].astype(str).value_counts().head(5)
            categories[str(col)] = [f"{name} — {int(count)}" for name, count in top.items()]
        if mode == "finance" and numeric_stats:
            first = next(iter(numeric_stats.items()))
            findings.append(f"По колонке «{first[0]}»: сумма {first[1]['sum']}, среднее {first[1]['mean']}, диапазон {first[1]['min']}–{first[1]['max']}.")
        elif mode == "marketing" and categories:
            first_name, values = next(iter(categories.items()))
            findings.append(f"Частые значения в «{first_name}»: " + "; ".join(values[:3]) + ".")
        else:
            findings.append(f"Набор данных: {len(df)} строк и {len(df.columns)} колонок.")
            if numeric:
                findings.append("Числовые колонки для расчётов: " + ", ".join(numeric[:6]) + ".")
        findings.extend(issues)
        question = question or DEFAULT_QUESTIONS[mode]
        answer = self._answer_question(question, " ".join(columns + findings), numeric_stats, categories)
        summary = f"{len(df)} строк, {len(df.columns)} колонок; пропусков: {missing}, дубликатов: {duplicates}."
        if issues:
            summary += " Есть замечания по качеству данных."
        return {
            "kind": "table",
            "mode": ANALYST_MODES[mode],
            "question": question,
            "answer": answer,
            "rows": len(df),
            "columns": len(df.columns),
            "missing": missing,
            "duplicates": duplicates,
            "numeric": numeric,
            "column_names": columns,
            "numeric_stats": numeric_stats,
            "categories": categories,
            "issues": issues,
            "findings": findings,
            "summary": summary,
            "method": "Строки, колонки, пропуски и дубликаты посчитаны pandas. Числовые показатели (сумма, среднее, min/max) рассчитаны программно. Модель не подменяет эти цифры; OpenAI в демо работает как заглушка.",
        }

    def _analyze_pdf(self, path: Path, mode: str, question: str) -> dict[str, Any]:
        try:
            reader = PdfReader(path)
            pages = [(page.extract_text() or "") for page in reader.pages]
        except Exception as exc:
            raise FileReadError("PDF не удалось прочитать.") from exc
        page_count = len(pages)
        raw = normalize_text("\n".join(pages))
        text = _clean_pdf_text(raw)
        empty_pages = sum(1 for page in pages if not page.strip())
        words = WORD_RE.findall(text)
        ranked_numbers = _ranked_numbers(text)[:10]
        numbers = [item["raw"] for item in ranked_numbers]
        title = _document_title(text)
        sentences = _sentences(text)
        contexts = _number_sentences(sentences, [item["raw"] for item in ranked_numbers[:6]])
        excerpt = " ".join(sentences[:3])[:700] if sentences else re.sub(r"\s+", " ", text).strip()[:700]
        question = question or DEFAULT_QUESTIONS[mode]
        issues: list[str] = []
        if empty_pages:
            issues.append(f"Страниц без текстового слоя: {empty_pages}. Если это скан, обычное извлечение PDF его не прочитает.")
        if page_count and len(text.strip()) < 80 * page_count:
            issues.append("Текста мало для объёма документа — возможно, часть страниц является изображением без OCR.")
        if not text.strip():
            issues.append("Текст не распознан. Для сканов нужна OCR; в демо без OpenAI доступны только метаданные PDF.")
        findings = [f"Режим: {ANALYST_MODES[mode]}."]
        if title:
            findings.append(f"Документ: {title}.")
        findings.append(f"Извлечён текст с {page_count} стр.: {len(words)} слов.")
        if ranked_numbers:
            top = ", ".join(f"{item['raw']}" for item in ranked_numbers[:5])
            findings.append(f"Наиболее крупные величины в тексте: {top}.")
        for sent in contexts[:4]:
            findings.append(sent)
        findings.extend(issues)
        answer = _pdf_answer(mode, question, title, ranked_numbers, contexts, issues)
        summary = _pdf_summary(title, page_count, len(words), ranked_numbers, issues)
        return {
            "kind": "pdf",
            "mode": ANALYST_MODES[mode],
            "question": question,
            "answer": answer,
            "pages": page_count,
            "characters": len(raw),
            "words": len(words),
            "empty_pages": empty_pages,
            "title": title,
            "numbers": numbers,
            "highlights": contexts,
            "excerpt": excerpt,
            "issues": issues,
            "findings": findings,
            "summary": summary,
            "method": "Текст извлечён pypdf.extract_text() по каждой странице и склеен в предложения. Страницы и слова посчитаны программно. Числа найдены регулярным выражением, отсортированы по величине, к ним подобраны соседние предложения. Содержимое файла в журнал событий не записывается. Внешняя модель в демо не вызывается.",
        }

    def _analyze_image(self, path: Path, mode: str, question: str) -> dict[str, Any]:
        try:
            with Image.open(path) as image:
                width, height, img_mode, fmt = image.width, image.height, image.mode, image.format or path.suffix.lstrip(".").upper()
        except (UnidentifiedImageError, OSError) as exc:
            raise FileReadError("Изображение не удалось прочитать.") from exc
        issues = ["OCR по изображению в демо без OpenAI не выполняется: доступны размер, цветовой режим и формат."]
        findings = [
            f"Режим: {ANALYST_MODES[mode]}.",
            f"Файл {fmt}: {width}×{height} px, цветовой режим {img_mode}.",
            issues[0],
        ]
        question = question or DEFAULT_QUESTIONS[mode]
        answer = self._answer_question(question, f"{fmt} {width} {height} {img_mode}", {}, {})
        return {
            "kind": "image",
            "mode": ANALYST_MODES[mode],
            "question": question,
            "answer": answer,
            "width": width,
            "height": height,
            "image_mode": img_mode,
            "format": fmt,
            "issues": issues,
            "findings": findings,
            "summary": f"Изображение {width}×{height}, режим {img_mode}.",
            "method": "Метаданные прочитаны Pillow. Распознавание текста на картинке отключено, пока не подключена модель.",
        }

    def _answer_question(self, question: str, haystack: str, numeric_stats: dict, categories: dict) -> str:
        if not question:
            return ""
        blob = haystack.lower()
        hits = [token for token in WORD_RE.findall(question.lower()) if len(token) > 3 and token in blob]
        extra = ""
        if numeric_stats:
            col, stats = next(iter(numeric_stats.items()))
            extra = f" Программный ориентир по «{col}»: сумма {stats['sum']}, максимум {stats['max']}."
        elif categories:
            col, values = next(iter(categories.items()))
            extra = f" Частые категории в «{col}»: " + "; ".join(values[:3]) + "."
        if hits:
            return f"По запросу «{question}» в данных встречаются: {', '.join(hits[:8])}.{extra} Ответ построен программно, без внешней языковой модели."
        return f"Запрос «{question}» принят. Точные показатели ниже рассчитаны программно; внешняя модель в демо не вызывается.{extra}"


def normalize_text(value: str) -> str:
    """Разворачивает HTML-сущности и \\uXXXX в обычный текст для экрана."""
    if not value:
        return value
    text = html.unescape(value.replace("\xa0", " "))
    pattern = re.compile(r"\\u([0-9a-fA-F]{4})")

    def repl(match: re.Match[str]) -> str:
        return chr(int(match.group(1), 16))

    for _ in range(3):
        nxt = pattern.sub(repl, text)
        if nxt == text:
            break
        text = nxt
    return html.unescape(text)


def normalize_tree(value: Any) -> Any:
    if isinstance(value, str):
        return normalize_text(value)
    if isinstance(value, list):
        return [normalize_tree(item) for item in value]
    if isinstance(value, dict):
        return {key: normalize_tree(item) for key, item in value.items()}
    return value


def _normalize_dataframe(frame: pd.DataFrame) -> pd.DataFrame:
    cleaned = frame.copy()
    for col in cleaned.select_dtypes(include=["object", "string"]).columns:
        cleaned[col] = cleaned[col].map(lambda cell: normalize_text(cell) if isinstance(cell, str) else cell)
    return cleaned


def pretty_json(value: Any) -> str:
    """JSON для <pre>: кириллица и <адрес> без \\u003c / \\u0441."""
    return json.dumps(value, ensure_ascii=False, indent=2)


def _as_float(value: Any) -> float:
    try:
        if value is None or pd.isna(value):
            return 0.0
    except (TypeError, ValueError):
        return 0.0
    return round(float(value), 2)


def _unique_keep_order(items) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = re.sub(r"\s+", " ", str(item)).strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _clean_pdf_text(text: str) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    joined: list[str] = []
    buf = ""
    for line in lines:
        if not line:
            if buf:
                joined.append(buf)
                buf = ""
            continue
        if buf and not buf.endswith((".", "?", "!", ":", ";")) and line[:1].islower():
            buf = f"{buf} {line}"
            continue
        if buf:
            joined.append(buf)
        buf = line
    if buf:
        joined.append(buf)
    return "\n".join(joined)


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", text).strip())
    return [part.strip() for part in parts if len(part.strip()) > 20]


def _strip_page_marker(line: str) -> str:
    return re.sub(r"\s*Page\s+\d+\s+of\s+\d+\s*$", "", line, flags=re.I).strip(" -•\t")


def _document_title(text: str) -> str:
    lines = [_strip_page_marker(line) for line in text.splitlines()]
    for line in lines:
        if re.search(r"report|отчет|отчёт|анализ|review", line, re.I) and 16 <= len(line) <= 140:
            return line
    for line in lines:
        if re.search(r"page\s+\d+\s+of\s+\d+", line, re.I):
            continue
        if re.match(r"^\d{4}$", line):
            continue
        if 16 <= len(line) <= 140 and not NUMBER_RE.fullmatch(line):
            return line
    sentences = _sentences(text)
    return sentences[0][:120] if sentences else "Документ PDF"


def _parse_number(raw: str) -> float:
    token = re.sub(r"[^\d,.\-]", "", raw)
    if re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?", token):
        token = token.replace(",", "")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", token):
        token = token.replace(".", "").replace(",", ".")
    else:
        token = token.replace(" ", "").replace(",", ".")
    try:
        return abs(float(token))
    except ValueError:
        return 0.0


def _is_chart_noise(sentence: str) -> bool:
    nums = NUMBER_RE.findall(sentence)
    words = WORD_RE.findall(sentence)
    return len(nums) >= 4 or len(words) < 8


def _ranked_numbers(text: str) -> list[dict[str, Any]]:
    useful = [sentence for sentence in _sentences(text) if not _is_chart_noise(sentence)]
    haystack = " ".join(useful) if useful else text
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in NUMBER_RE.findall(haystack):
        if "\n" in raw:
            continue
        key = re.sub(r"\s+", "", raw)
        if key in seen:
            continue
        seen.add(key)
        value = _parse_number(raw)
        if value <= 0:
            continue
        found.append({"raw": raw.strip(), "value": value})
    found.sort(key=lambda item: item["value"], reverse=True)
    return found


def _number_sentences(sentences: list[str], numbers: list[str]) -> list[str]:
    hits: list[str] = []
    useful = [sentence for sentence in sentences if not _is_chart_noise(sentence)]
    for raw in numbers:
        for sentence in useful:
            if raw in sentence and sentence not in hits:
                hits.append(sentence if len(sentence) <= 280 else sentence[:277] + "…")
                break
    return hits[:6]


def _pdf_summary(title: str, pages: int, words: int, ranked: list[dict[str, Any]], issues: list[str]) -> str:
    top = ", ".join(item["raw"] for item in ranked[:3])
    text = f"«{title}»: {pages} стр., {words} слов."
    if top:
        text += f" Ключевые величины: {top}."
    if issues:
        text += " Есть замечания к качеству извлечения."
    return text


def _pdf_answer(mode: str, question: str, title: str, ranked: list[dict[str, Any]], contexts: list[str], issues: list[str]) -> str:
    parts = [f"По запросу «{question}» ДИС разобрал «{title}» как {ANALYST_MODES[mode]}."]
    if ranked:
        parts.append("Самые крупные числа в тексте: " + ", ".join(item["raw"] for item in ranked[:5]) + ".")
    if contexts:
        parts.append("Контекст: " + " ".join(contexts[:2]))
    elif mode == "marketing":
        parts.append("Отдельных устойчивых формулировок с цифрами мало — смотрите фрагмент документа ниже.")
    if issues:
        parts.append(issues[0])
    parts.append("Цифры сняты с текста программно; внешняя модель в демо не вызывается, поэтому это наблюдения, а не аудит первоисточника.")
    return " ".join(parts)


class ChartService:
    TYPES = {"bar", "line", "histogram", "pie", "scatter", "box", "heatmap"}

    def __init__(self, cfg: Settings): self.cfg = cfg

    def create(self, path: Path, chart_type: str, x: str | None, y: str | None) -> dict[str, str]:
        if chart_type not in self.TYPES: raise ValueError("Неизвестный тип графика.")
        df = FileService(self.cfg).dataframe(path)
        numeric = list(df.select_dtypes(include=np.number).columns)
        x = x if x in df.columns else str(df.columns[0])
        y = y if y in df.columns else (str(numeric[0]) if numeric else None)
        if chart_type == "histogram": fig = px.histogram(df, x=y or x)
        elif chart_type == "pie":
            if y: fig = px.pie(df.groupby(x, as_index=False)[y].sum().head(12), names=x, values=y)
            else: fig = px.pie(df[x].value_counts().head(12).reset_index(), names=x, values="count")
        elif chart_type == "scatter": fig = px.scatter(df, x=x, y=y)
        elif chart_type == "line": fig = px.line(df, x=x, y=y)
        elif chart_type == "box": fig = px.box(df, x=x, y=y)
        elif chart_type == "heatmap": fig = px.imshow(df.select_dtypes(include=np.number).corr(), text_auto=True)
        else: fig = px.bar(df.groupby(x, as_index=False)[y].sum().head(30), x=x, y=y) if y else px.bar(df[x].value_counts().head(30).reset_index(), x=x, y="count")
        chart_id = uuid4().hex
        html_name = f"{chart_id}.html"
        png_name = f"{chart_id}.png"
        fig.update_layout(template="plotly_white", colorway=["#1976D2", "#F58220", "#2E9D68"])
        fig.write_html(self.cfg.output_dir / html_name, include_plotlyjs="cdn", full_html=True)
        png_url = ""
        try:
            fig.write_image(self.cfg.output_dir / png_name, width=1200, height=700)
            png_url = f"/outputs/{png_name}"
        except Exception:
            pass
        return {"html_url": f"/outputs/{html_name}", "png_url": png_url, "method": f"Тип: {chart_type}; X: {x}; Y: {y or 'частота'}."}

