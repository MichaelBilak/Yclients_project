"""
Модуль для работы с базой данных PostgreSQL
"""
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import SQLAlchemyError
from models import Base
from typing import Generator


class Database:
    """Класс для работы с локальной базой данных PostgreSQL"""

    def __init__(self, host: str, port: int, name: str, user: str, password: str = ''):
        if password:
            self.database_url = f'postgresql+psycopg2://{user}:{password}@{host}:{port}/{name}'
        else:
            self.database_url = f'postgresql+psycopg2://{user}@{host}:{port}/{name}'

        self.engine = create_engine(
            self.database_url,
            pool_pre_ping=True,
            pool_recycle=300,
        )
        self.SessionLocal = sessionmaker(bind=self.engine)

    def create_tables(self) -> bool:
        try:
            self.ensure_system_schema()
            Base.metadata.create_all(self.engine)
            self.migrate_legacy_sync_state()
            self.create_indexes()
            print("✓ Таблицы созданы/проверены")
            return True
        except SQLAlchemyError as e:
            print(f"✗ Ошибка при создании таблиц: {e}")
            return False

    def ensure_system_schema(self) -> None:
        with self.engine.begin() as conn:
            conn.execute(text("CREATE SCHEMA IF NOT EXISTS system"))

    def migrate_legacy_sync_state(self) -> None:
        inspector = inspect(self.engine)
        if not inspector.has_table('sync_state', schema='public'):
            return
        if not inspector.has_table('sync_state', schema='system'):
            return

        with self.engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO system.sync_state (key, value, updated_at)
                SELECT key, value, updated_at
                FROM public.sync_state
                ON CONFLICT (key) DO NOTHING
            """))

    def create_indexes(self) -> None:
        for table in Base.metadata.tables.values():
            for index in table.indexes:
                index.create(bind=self.engine, checkfirst=True)

    def get_session(self) -> Generator[Session, None, None]:
        """Получить сессию (для FastAPI Depends)"""
        db = self.SessionLocal()
        try:
            yield db
        finally:
            db.close()

    def get_db(self) -> Session:
        """Получить сессию (для прямого использования)"""
        return self.SessionLocal()

    def test_connection(self) -> bool:
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            print("✓ Подключение к базе данных успешно")
            return True
        except SQLAlchemyError as e:
            print(f"✗ Ошибка подключения к базе данных: {e}")
            return False


db_instance: Database = None


def init_database(host: str, port: int, name: str, user: str, password: str = '') -> Database:
    global db_instance
    db_instance = Database(host, port, name, user, password)
    return db_instance


def get_db() -> Generator[Session, None, None]:
    """Получить сессию базы данных (для FastAPI Depends)"""
    if db_instance is None:
        raise RuntimeError("База данных не инициализирована. Вызовите init_database()")
    yield from db_instance.get_session()
