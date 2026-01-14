from sqlmodel import SQLModel, Session, create_engine, select

from app.models import CURRENT_VERSION_NUMBER, SchemaVersion


def get_engine(settings):
    connect_args = {"check_same_thread": False} if "sqlite" in settings.db_connection_string else {}
    engine = create_engine(settings.db_connection_string, connect_args=connect_args)
    return engine


def create_db_and_tables(engine):
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db_session:
        versions = db_session.exec(select(SchemaVersion)).all()
        if len(versions) == 0:
            db_session.add(SchemaVersion(version_number=CURRENT_VERSION_NUMBER))
            db_session.flush()
        elif len(versions) > 1:
            raise ValueError(f"Number of rows in SchemaVersion table is {len(versions)} when it should be 1.")
        elif versions[0].version_number < CURRENT_VERSION_NUMBER:
            raise NotImplementedError(
                "Schema needs to be updated but migrations were not implemented yet. You can clean all data and db manually and let app recreate it on next run."
            )
