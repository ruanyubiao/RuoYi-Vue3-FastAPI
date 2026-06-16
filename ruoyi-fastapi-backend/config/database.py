from urllib.parse import quote_plus

from sqlalchemy import Engine, create_engine
from sqlalchemy.ext.asyncio import AsyncAttrs, AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy import event

from config.env import DataBaseConfig


def build_async_sqlalchemy_database_url() -> str:
    """
    构建异步 SQLAlchemy 数据库连接 URL

    :return: 异步 SQLAlchemy 数据库连接 URL
    """
    if DataBaseConfig.db_type == 'postgresql':
        return (
            f'postgresql+asyncpg://{DataBaseConfig.db_username}:{quote_plus(DataBaseConfig.db_password)}@'
            f'{DataBaseConfig.db_host}:{DataBaseConfig.db_port}/{DataBaseConfig.db_database}'
        )
    if DataBaseConfig.db_type == 'sqlite':
        # SQLite 使用文件路径作为数据库名，默认为当前目录下的 ruoyi-fastapi.db
        db_path = DataBaseConfig.db_database if DataBaseConfig.db_database.endswith('.db') else f'{DataBaseConfig.db_database}.db'
        return f'sqlite+aiosqlite:///{db_path}'
    return (
        f'mysql+asyncmy://{DataBaseConfig.db_username}:{quote_plus(DataBaseConfig.db_password)}@'
        f'{DataBaseConfig.db_host}:{DataBaseConfig.db_port}/{DataBaseConfig.db_database}'
    )


ASYNC_SQLALCHEMY_DATABASE_URL = build_async_sqlalchemy_database_url()


def build_sync_sqlalchemy_database_url() -> str:
    """
    构建同步 SQLAlchemy 数据库连接 URL

    :return: 同步 SQLAlchemy 数据库连接 URL
    """
    if DataBaseConfig.db_type == 'postgresql':
        return (
            f'postgresql+psycopg2://{DataBaseConfig.db_username}:{quote_plus(DataBaseConfig.db_password)}@'
            f'{DataBaseConfig.db_host}:{DataBaseConfig.db_port}/{DataBaseConfig.db_database}'
        )
    if DataBaseConfig.db_type == 'sqlite':
        # SQLite 使用文件路径作为数据库名，默认为当前目录下的 ruoyi-fastapi.db
        db_path = DataBaseConfig.db_database if DataBaseConfig.db_database.endswith('.db') else f'{DataBaseConfig.db_database}.db'
        return f'sqlite:///{db_path}'
    return (
        f'mysql+pymysql://{DataBaseConfig.db_username}:{quote_plus(DataBaseConfig.db_password)}@'
        f'{DataBaseConfig.db_host}:{DataBaseConfig.db_port}/{DataBaseConfig.db_database}'
    )


SYNC_SQLALCHEMY_DATABASE_URL = build_sync_sqlalchemy_database_url()


def create_async_db_engine(echo: bool | None = None) -> AsyncEngine:
    """
    创建异步 SQLAlchemy Engine

    :param echo: 可选，是否输出 SQLAlchemy SQL 日志
    :return: 异步 SQLAlchemy Engine
    """
    # SQLite 不支持连接池配置，需要特殊处理
    if DataBaseConfig.db_type == 'sqlite':
        engine = create_async_engine(
            ASYNC_SQLALCHEMY_DATABASE_URL,
            echo=DataBaseConfig.db_echo if echo is None else echo,
            # SQLite 使用 NullPool 或者 StaticPool
            poolclass=None,
        )

        # sqlite不支持find_in_set函数，注册自定义函数实现类似功能
        # 异步引擎需要监听 sync_engine，不能直接监听 AsyncEngine
        @event.listens_for(engine.sync_engine, "connect")
        def register_sqlite_functions(dbapi_connection, connection_record):
            def find_in_set(value, set_str):
                if not set_str:
                    return 0
                return 1 if str(value) in set_str.split(',') else 0
            dbapi_connection.create_function("find_in_set", 2, find_in_set)

        return engine


    return create_async_engine(
        ASYNC_SQLALCHEMY_DATABASE_URL,
        echo=DataBaseConfig.db_echo if echo is None else echo,
        max_overflow=DataBaseConfig.db_max_overflow,
        pool_size=DataBaseConfig.db_pool_size,
        pool_recycle=DataBaseConfig.db_pool_recycle,
        pool_timeout=DataBaseConfig.db_pool_timeout,
    )


def create_sync_db_engine(echo: bool | None = None) -> Engine:
    """
    创建同步 SQLAlchemy Engine

    :param echo: 可选，是否输出 SQLAlchemy SQL 日志
    :return: 同步 SQLAlchemy Engine
    """
    # SQLite 不支持连接池配置，需要特殊处理
    if DataBaseConfig.db_type == 'sqlite':
        engine = create_engine(
            SYNC_SQLALCHEMY_DATABASE_URL,
            echo=DataBaseConfig.db_echo if echo is None else echo,
            # SQLite 使用 StaticPool 以保持连接
            poolclass=None,
            connect_args={'check_same_thread': False},
        )

        # sqlite不支持find_in_set函数，注册自定义函数实现类似功能
        @event.listens_for(engine, "connect")
        def register_sqlite_functions(dbapi_connection, connection_record):
            def find_in_set(value, set_str):
                if not set_str:
                    return 0
                return 1 if str(value) in set_str.split(',') else 0
            dbapi_connection.create_function("find_in_set", 2, find_in_set)

        return engine

    return create_engine(
        SYNC_SQLALCHEMY_DATABASE_URL,
        echo=DataBaseConfig.db_echo if echo is None else echo,
        max_overflow=DataBaseConfig.db_max_overflow,
        pool_size=DataBaseConfig.db_pool_size,
        pool_recycle=DataBaseConfig.db_pool_recycle,
        pool_timeout=DataBaseConfig.db_pool_timeout,
    )


def create_async_session_local(engine: AsyncEngine) -> async_sessionmaker:
    """
    创建异步 Session 工厂

    :param engine: 异步 SQLAlchemy Engine
    :return: 异步 Session 工厂
    """
    return async_sessionmaker(autocommit=False, autoflush=False, bind=engine)


def create_sync_session_local(engine: Engine) -> sessionmaker:
    """
    创建同步 Session 工厂

    :param engine: 同步 SQLAlchemy Engine
    :return: 同步 Session 工厂
    """
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


async_engine = create_async_db_engine()
AsyncSessionLocal = create_async_session_local(async_engine)


class Base(AsyncAttrs, DeclarativeBase):
    pass
