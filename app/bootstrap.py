"""Provisionamento idempotente das identidades do piloto, sem registrar segredos."""

import hashlib
import hmac
import json
import os
import re

from .database import connect
from .security import _app_secret, hash_password


def bootstrap_users() -> int:
    raw = os.getenv("BOOTSTRAP_USERS_JSON", "").strip()
    if not raw:
        return 0
    # Não propagar o JSON nem a mensagem do parser em falhas de configuração.
    try:
        users = json.loads(raw)
        if not isinstance(users, list) or not users:
            raise ValueError
        normalized = []
        usernames, public_ids = set(), set()
        secret = _app_secret()
        for user in users:
            username = user["usuario"].strip().lower()
            name, password, role = user["nome"].strip(), user["senha"], user["perfil"]
            if not re.fullmatch(r"[a-z0-9._-]{3,50}", username):
                raise ValueError
            if not 2 <= len(name) <= 200 or not isinstance(password, str) or not 12 <= len(password) <= 256:
                raise ValueError
            if role not in {"admin", "analista"} or username in usernames:
                raise ValueError
            public_id = user.get("operador_public_id") or "opr_" + hmac.new(
                secret.encode(), ("operador:" + username).encode(), hashlib.sha256
            ).hexdigest()[:32]
            if not re.fullmatch(r"opr_[0-9a-f]{32}", public_id) or public_id in public_ids:
                raise ValueError
            usernames.add(username)
            public_ids.add(public_id)
            normalized.append((username, name, password, role, public_id))
    except (ValueError, TypeError, KeyError, AttributeError):
        raise RuntimeError("BOOTSTRAP_USERS_JSON inválido. Verifique os campos e as identidades dos usuários.") from None

    created = 0
    with connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        for username, name, password, role, public_id in normalized:
            existing = connection.execute("SELECT id FROM usuarios WHERE usuario=?", (username,)).fetchone()
            if existing:
                continue  # Não redefinir senha, perfil, estado ou identidade de conta existente.
            if connection.execute("SELECT 1 FROM usuarios WHERE operador_public_id=?", (public_id,)).fetchone():
                raise RuntimeError("Identidade de bootstrap já vinculada a outro usuário.")
            connection.execute(
                """INSERT INTO usuarios(usuario,nome,senha_hash,totp_secret_encrypted,perfil,operador_public_id)
                   VALUES(?,?,?,'',?,?)""",
                (username, name, hash_password(password), role, public_id),
            )
            created += 1
    return created
