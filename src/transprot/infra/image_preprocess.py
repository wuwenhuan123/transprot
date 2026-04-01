from __future__ import annotations

import importlib.util
from pathlib import Path


def preprocess_capture(image_path: Path) -> Path:
    if importlib.util.find_spec("PIL") is None:
        return image_path

    from PIL import Image, ImageEnhance

    with Image.open(image_path) as image:
        image = image.convert("RGB")
        width, height = image.size
        if min(width, height) < 640:
            image = image.resize((width * 2, height * 2))
        image = ImageEnhance.Contrast(image).enhance(1.12)
        output_path = image_path.with_name(f"{image_path.stem}-preprocessed.png")
        image.save(output_path)
        return output_path
