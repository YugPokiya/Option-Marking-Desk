import os

# Unit tests must never touch real services; integration tests override these via env.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://omd:omd@localhost:5432/omd_test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
