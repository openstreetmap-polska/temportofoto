from datetime import timedelta
from pathlib import Path

import aiofiles
import httpx
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, AsyncSession

from app.models import STATUS, CogFile


async def download_file(file_url: str, local_path: Path, db_engine: AsyncEngine):
    print("Starting background download job for url:", file_url)
    async_session = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as db_session, httpx.AsyncClient() as client, aiofiles.open(local_path, "wb") as fp:
        metadata = await db_session.get(CogFile, file_url)
        if metadata is None:
            raise Exception(f"Did not find entry in DB for url: {file_url}")
        print("Starting download of:", file_url)
        async with client.stream(method="GET", url=file_url, timeout=timedelta(hours=1).total_seconds()) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes(8 * 1024 * 1024):
                num_bytes = len(chunk)
                await fp.write(chunk)
                metadata.downloaded_bytes += num_bytes
                metadata.download_pct = metadata.downloaded_bytes / metadata.total_size_bytes
                db_session.add(metadata)
                await db_session.commit()
                await db_session.refresh(metadata)
    metadata.status = STATUS.downloaded
    db_session.add(metadata)
    await db_session.commit()
    await db_session.refresh(metadata)
    print("Finished background download job for url:", file_url, "meta:", metadata)
