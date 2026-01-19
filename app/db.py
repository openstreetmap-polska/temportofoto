from sqlmodel import SQLModel, select
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models import CURRENT_VERSION_NUMBER, SchemaVersion
from app.config import Settings


def get_engine(settings: Settings):
    connect_args = {"check_same_thread": False} if "sqlite" in settings.db_connection_string else {}
    engine = create_async_engine(settings.db_connection_string, connect_args=connect_args)
    return engine


async def create_db_and_tables(db_engine: AsyncEngine):
    async with db_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async_session = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as db_session:
        versions = (await db_session.exec(select(SchemaVersion))).all()
        if len(versions) == 0:
            db_session.add(SchemaVersion(version_number=CURRENT_VERSION_NUMBER))
            await db_session.commit()
        elif len(versions) > 1:
            raise ValueError(f"Number of rows in SchemaVersion table is {len(versions)} when it should be 1.")
        elif versions[0].version_number < CURRENT_VERSION_NUMBER:
            raise NotImplementedError(
                "Schema needs to be updated but migrations were not implemented yet. You can clean all data and db manually and let app recreate it on next run."
            )
