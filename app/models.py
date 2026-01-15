from pydantic import BaseModel
from datetime import datetime
from typing import NamedTuple

from sqlmodel import SQLModel, Field

CURRENT_VERSION_NUMBER = 1


class Status(NamedTuple):
    downloading: str = "downloading"
    downloaded: str = "downloaded"


STATUS = Status()


class Version(BaseModel):
    app_version: str
    db_schema_version: int
    db_version: str | None


class CogFileStatus(BaseModel):
    url: str
    abs_file_path: str
    request_dt: datetime
    delete_after: datetime
    status: str
    total_size_bytes: int
    downloaded_bytes: int
    download_pct: float
    tile_endpoint: str | None


class SchemaVersion(SQLModel, table=True):
    version_number: int = Field(default=None, primary_key=True)


class CogFile(SQLModel, table=True):
    url: str = Field(default=None, primary_key=True)
    abs_file_path: str
    request_dt: datetime
    delete_after: datetime
    status: str
    total_size_bytes: int
    downloaded_bytes: int
    download_pct: float
