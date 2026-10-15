"""Verificação manual opt-in do bucket temporário (usa apenas conteúdo sintético)."""
import hashlib
import os
from pathlib import Path
import sys
import uuid

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> None:
    if os.getenv("TEST_SUPABASE_ENABLED", "false").lower() != "true":
        raise RuntimeError("Defina TEST_SUPABASE_ENABLED=true para executar este teste.")
    from app.file_storage import file_storage
    content = b"%PDF-1.4\n% documento sintetico de teste\n"
    key = f"healthcheck/{uuid.uuid4().hex}/synthetic.pdf"
    storage = file_storage()
    storage.store(key, content)
    try:
        if not storage.exists(key) or hashlib.sha256(storage.read(key)).digest() != hashlib.sha256(content).digest():
            raise RuntimeError("A verificação de integridade do storage falhou.")
    finally:
        storage.delete(key)
    if storage.exists(key):
        raise RuntimeError("O objeto de teste não foi removido.")
    print("Supabase Storage verificado com sucesso.")


if __name__ == "__main__":
    main()
