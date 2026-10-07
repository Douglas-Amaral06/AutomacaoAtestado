"""Configuração local carregada antes de calcular os caminhos da aplicação."""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env", encoding="utf-8-sig")
DATA_DIR = Path(os.getenv("DATA_DIR") or BASE_DIR / "data").expanduser().resolve()


def positive_env_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default
