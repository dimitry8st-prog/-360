from __future__ import annotations

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
            if ext == ".csv": return pd.read_csv(path, low_memory=False)
            if ext in {".xlsx", ".xls"}: return pd.read_excel(path)
            if ext == ".json": return pd.json_normalize(json.loads(path.read_text(encoding="utf-8")))
        except Exception as exc:
            raise FileReadError("Файл не удалось прочитать. Проверьте его структуру.") from exc
        raise FileReadError("Файл не является таблицей.")

    def analyze(self, path: Path, kind: str) -> dict[str, Any]:
        if kind == "table":
            df = self.dataframe(path)
            if df.empty: raise EmptyFileError("Таблица не содержит строк.")
            duplicates = int(df.duplicated().sum())
            missing = int(df.isna().sum().sum())
            numeric = list(map(str, df.select_dtypes(include=np.number).columns))
            return {"kind": kind, "rows": len(df), "columns": len(df.columns), "missing": missing, "duplicates": duplicates, "numeric": numeric, "column_names": list(map(str, df.columns)), "summary": f"{len(df)} строк, {len(df.columns)} колонок; пропусков: {missing}, дубликатов: {duplicates}."}
        if kind == "pdf":
            try:
                reader = PdfReader(path)
                text = "\n".join((p.extract_text() or "") for p in reader.pages)
                return {"kind": kind, "pages": len(reader.pages), "characters": len(text), "summary": f"PDF: {len(reader.pages)} стр., распознано {len(text)} символов."}
            except Exception as exc: raise FileReadError("PDF не удалось прочитать.") from exc
        try:
            with Image.open(path) as image:
                return {"kind": kind, "width": image.width, "height": image.height, "mode": image.mode, "summary": f"Изображение {image.width}×{image.height}, режим {image.mode}."}
        except (UnidentifiedImageError, OSError) as exc: raise FileReadError("Изображение не удалось прочитать.") from exc


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

