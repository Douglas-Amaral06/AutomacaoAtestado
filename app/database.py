import sqlite3
import uuid
from .config import BASE_DIR, DATA_DIR


UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "atestados.db"


def new_operator_public_id() -> str:
    """Gera identidade opaca, permanente e não derivada de dados pessoais."""
    return f"opr_{uuid.uuid4().hex}"


def initialize_database() -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS atestados (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT,
                cpf TEXT,
                cid TEXT,
                dias_afastamento INTEGER,
                data_atestado TEXT,
                arquivo_original TEXT NOT NULL,
                arquivo_salvo TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pendente',
                observacoes TEXT,
                confianca TEXT,
                criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                revisado_em TEXT
            )
            """
        )
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(atestados)").fetchall()
        }
        if "arquivo_hash" not in columns:
            connection.execute("ALTER TABLE atestados ADD COLUMN arquivo_hash TEXT")
        for column, definition in {
            "revisado_por": "INTEGER",
            "motivo_rejeicao": "TEXT",
            "dados_originais": "TEXT",
            "matricula": "TEXT",
            "telefone": "TEXT",
            "email": "TEXT",
            "empresa": "TEXT",
            "tipo_documento": "TEXT",
            "status_enriquecimento": "TEXT",
            "crm": "TEXT",
            "crm_uf": "TEXT",
            "assinado": "INTEGER",
            "carimbado": "INTEGER",
            "operador_envio_id": "INTEGER",
            "id_documento": "TEXT",
            "status_entrega": "TEXT",
        }.items():
            if column not in columns:
                connection.execute(f"ALTER TABLE atestados ADD COLUMN {column} {definition}")
        connection.execute("DROP INDEX IF EXISTS idx_atestados_arquivo_hash")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_atestados_arquivo_hash ON atestados(arquivo_hash)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_atestados_id_documento ON atestados(id_documento)")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario TEXT NOT NULL UNIQUE COLLATE NOCASE,
                nome TEXT NOT NULL,
                senha_hash TEXT NOT NULL,
                totp_secret_encrypted TEXT NOT NULL,
                perfil TEXT NOT NULL CHECK(perfil IN ('admin','analista')),
                ativo INTEGER NOT NULL DEFAULT 1,
                criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                ultimo_login TEXT
            );
            CREATE TABLE IF NOT EXISTS sessoes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario_id INTEGER NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                csrf_token TEXT NOT NULL,
                ip_hash TEXT,
                user_agent_hash TEXT,
                expira_em TEXT NOT NULL,
                criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(usuario_id) REFERENCES usuarios(id)
            );
            CREATE TABLE IF NOT EXISTS tentativas_login (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chave_hash TEXT NOT NULL,
                sucesso INTEGER NOT NULL,
                criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_login_chave_data ON tentativas_login(chave_hash, criado_em);
            CREATE TABLE IF NOT EXISTS gemini_consumo (
                dia TEXT PRIMARY KEY,
                chamadas INTEGER NOT NULL DEFAULT 0,
                tokens_reservados INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS fila_processamento (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                arquivo_hash TEXT NOT NULL,
                arquivo_original TEXT NOT NULL,
                arquivo_salvo TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'processando',
                tentativas INTEGER NOT NULL DEFAULT 0,
                ultimo_erro TEXT,
                disponivel_em TEXT,
                atestado_id INTEGER,
                criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                atualizado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(atestado_id) REFERENCES atestados(id)
            );
            """
        )
        user_columns = {row[1] for row in connection.execute("PRAGMA table_info(usuarios)").fetchall()}
        if "operador_public_id" not in user_columns:
            connection.execute("ALTER TABLE usuarios ADD COLUMN operador_public_id TEXT")
        missing_operator_ids = connection.execute(
            "SELECT id FROM usuarios WHERE operador_public_id IS NULL OR operador_public_id=''"
        ).fetchall()
        for row in missing_operator_ids:
            connection.execute(
                "UPDATE usuarios SET operador_public_id=? WHERE id=?",
                (new_operator_public_id(), row[0]),
            )
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_usuarios_operador_public_id ON usuarios(operador_public_id)"
        )
        _migrate_queue(connection)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nivel TEXT NOT NULL,
                evento TEXT NOT NULL,
                mensagem TEXT NOT NULL,
                detalhes TEXT,
                criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        # Versões antigas persistiam mensagens cruas de exceção. Preserva o
        # evento e a data, removendo somente os campos que podiam conter segredos.
        connection.execute(
            """UPDATE logs SET mensagem='Falha histórica sanitizada.', detalhes=NULL
               WHERE evento IN ('processamento_falhou','manutencao_falhou','falha_interna')
                 AND mensagem NOT LIKE 'Falha de processamento. Referência: %'"""
        )
        connection.execute(
            """UPDATE fila_processamento SET ultimo_erro='Falha histórica sanitizada.'
               WHERE ultimo_erro IS NOT NULL
                 AND ultimo_erro<>'classificacao_documento_invalido'
                 AND ultimo_erro NOT LIKE 'Falha de processamento. Referência: %'"""
        )


def _migrate_queue(connection: sqlite3.Connection) -> None:
    """Reconstrói apenas a fila em transação; preserva IDs, vínculos e leases.

    Os identificadores de canal antigo abaixo existem somente para migrar bancos
    anteriores. Nenhuma rota ou serviço depende deles após esta conversão.
    """
    definitions = {
        "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
        "arquivo_hash": "TEXT NOT NULL", "arquivo_original": "TEXT NOT NULL",
        "arquivo_salvo": "TEXT NOT NULL", "mime_type": "TEXT NOT NULL",
        "status": "TEXT NOT NULL DEFAULT 'aguardando_retentativa'",
        "tentativas": "INTEGER NOT NULL DEFAULT 0", "ultimo_erro": "TEXT",
        "erro_amigavel": "TEXT", "disponivel_em": "TEXT", "atestado_id": "INTEGER",
        "criado_em": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
        "atualizado_em": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
        "data_recebimento": "TEXT", "unidade": "TEXT", "polo": "TEXT",
        "origem": "TEXT NOT NULL DEFAULT 'painel'", "operador_id": "INTEGER",
        "lock_token": "TEXT", "lock_expires_em": "TEXT",
    }
    columns = {row[1] for row in connection.execute("PRAGMA table_info(fila_processamento)")}
    indexes = connection.execute("PRAGMA index_list(fila_processamento)").fetchall()
    needs_rebuild = columns != set(definitions) or any(row[2] for row in indexes)
    # executescript não é usado aqui: ele faria COMMIT implícito no meio da migração.
    connection.execute("SAVEPOINT migracao_fila")
    try:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "token_servico_id" in columns and "tokens_servico" in tables:
            if "operador_id" not in columns:
                connection.execute("ALTER TABLE fila_processamento ADD COLUMN operador_id INTEGER")
                columns.add("operador_id")
            connection.execute("""UPDATE fila_processamento SET operador_id=(
                SELECT criado_por FROM tokens_servico WHERE id=fila_processamento.token_servico_id)
                WHERE operador_id IS NULL""")
        if needs_rebuild:
            ddl = ",".join(f'"{name}" {kind}' for name, kind in definitions.items())
            connection.execute(f"CREATE TABLE fila_nova ({ddl}, FOREIGN KEY(atestado_id) REFERENCES atestados(id))")
            common = [name for name in definitions if name in columns]
            names = ",".join(f'"{name}"' for name in common)
            connection.execute(f"INSERT INTO fila_nova ({names}) SELECT {names} FROM fila_processamento")
            connection.execute("DROP TABLE fila_processamento")
            connection.execute("ALTER TABLE fila_nova RENAME TO fila_processamento")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_fila_status ON fila_processamento(status, disponivel_em)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_fila_arquivo_hash ON fila_processamento(arquivo_hash)")
        connection.execute("UPDATE fila_processamento SET status='processando' WHERE status='processando_manual'")
        connection.execute("""UPDATE atestados SET operador_envio_id=(
            SELECT operador_id FROM fila_processamento WHERE atestado_id=atestados.id
            AND operador_id IS NOT NULL ORDER BY id DESC LIMIT 1)
            WHERE operador_envio_id IS NULL""")
        connection.execute("DROP TABLE IF EXISTS codigos_pareamento")
        connection.execute("DROP TABLE IF EXISTS tokens_servico")
        # Campos antigos do usuário são ignorados para preservar contas existentes.
        connection.execute("RELEASE SAVEPOINT migracao_fila")
    except Exception:
        connection.execute("ROLLBACK TO SAVEPOINT migracao_fila")
        connection.execute("RELEASE SAVEPOINT migracao_fila")
        raise


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection
