import os
from urllib.parse import quote_plus

from dotenv import load_dotenv


load_dotenv()

_database_url = os.getenv("DATABASE_URL", "").strip()
if _database_url.startswith("postgres://"):
    _database_url = "postgresql+psycopg://" + _database_url[len("postgres://"):]
elif _database_url.startswith("postgresql://"):
    _database_url = "postgresql+psycopg://" + _database_url[len("postgresql://"):]
if not _database_url:
    _db_user = quote_plus(os.getenv("POSTGRES_USER", "knowledge"))
    _db_password = quote_plus(os.getenv("POSTGRES_PASSWORD", "knowledge"))
    _db_host = os.getenv("POSTGRES_HOST", "localhost")
    _db_port = os.getenv("POSTGRES_PORT", "5432")
    _db_name = quote_plus(os.getenv("POSTGRES_DB", "knowledge"))
    _database_url = f"postgresql+psycopg://{_db_user}:{_db_password}@{_db_host}:{_db_port}/{_db_name}"
DATABASE_URL = _database_url
JWT_SECRET = os.getenv("JWT_SECRET", "local-development-secret-change-me")
ACCESS_TOKEN_MINUTES = int(os.getenv("ACCESS_TOKEN_MINUTES", "720"))
BOOTSTRAP_ADMIN_EMAIL = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "").strip().lower()
BOOTSTRAP_ADMIN_PASSWORD = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
OLLAMA_CHAT_MODEL = os.getenv("OLLAMA_CHAT_MODEL", "").strip()
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "").strip()
MAX_DOCUMENT_CHARS = int(os.getenv("MAX_DOCUMENT_CHARS", "1000000"))
