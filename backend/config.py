"""
Configuration module for VeloRoster AI backend.
Reads system environment variables and cloud provider configurations (Render, Heroku, etc.).
"""

import os


class Settings:
    # Service Information
    APP_NAME: str = "VeloRoster AI"
    APP_VERSION: str = "2.5.0"
    COMPANY: str = "Ecstaticloud Technologies"

    # Server settings
    PORT: int = int(os.environ.get("PORT", "8000"))
    HOST: str = os.environ.get("HOST", "0.0.0.0")
    RENDER: bool = bool(os.environ.get("RENDER"))

    # Database
    DATABASE_URL: str = os.environ.get("DATABASE_URL", "")
    DATA_DIR: str = os.environ.get("DATA_DIR", "")
    SQLITE_DB_PATH: str = os.environ.get("SQLITE_DB_PATH", "")

    # SuperAdmin defaults
    SUPERADMIN_EMAIL: str = os.environ.get("SUPERADMIN_EMAIL", "admin@athletics.com")
    SUPERADMIN_PASSWORD: str = os.environ.get("SUPERADMIN_PASSWORD", "admin")
    SUPERADMIN_NAME: str = os.environ.get("SUPERADMIN_NAME", "Platform Administrator")

    # Anti-idle Keep-Alive
    KEEP_ALIVE_ENABLED: bool = os.environ.get("KEEP_ALIVE_ENABLED", "true").lower() in ("true", "1", "yes")
    KEEP_ALIVE_INTERVAL: int = int(os.environ.get("KEEP_ALIVE_INTERVAL", "600"))
    KEEP_ALIVE_URL: str = os.environ.get("KEEP_ALIVE_URL", "")
    RENDER_EXTERNAL_URL: str = os.environ.get("RENDER_EXTERNAL_URL", "")

    # Rembg model
    REMBG_MODEL: str = os.environ.get("REMBG_MODEL", "u2netp" if os.environ.get("RENDER") else "u2net")


settings = Settings()
