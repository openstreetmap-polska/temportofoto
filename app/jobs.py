import asyncio
from datetime import timedelta
from pathlib import Path

import aiofiles
import httpx
import morecantile
from rio_cogeo.cogeo import cog_translate
from rio_cogeo.profiles import cog_profiles
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, AsyncSession

from app.models import STATUS, CogFile


def _translate(src_path, dst_path, **options):
    """Convert image to COG."""
    # Format creation option (see gdalwarp `-co` option)
    output_profile: dict = cog_profiles.get("jpeg")
    output_profile.update(dict(BIGTIFF="IF_SAFER"))
    output_profile.update(dict(JPEG_QUALITY="100"))

    # Dataset Open option (see gdalwarp `-oo` option)
    config = dict(
        GDAL_NUM_THREADS="1",  #"ALL_CPUS",
        GDAL_TIFF_INTERNAL_MASK=True,
        GDAL_TIFF_OVR_BLOCKSIZE="128",
    )

    cog_translate(
        src_path,
        dst_path,
        output_profile,
        config=config,
        in_memory=False,
        quiet=True,
        tms=morecantile.tms.get("WebMercatorQuad"),
        **options,
    )


async def download_file(file_url: str, local_path: Path, db_engine: AsyncEngine):
    print("Starting background download job for url:", file_url)
    async_session = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with (
        async_session() as db_session,
        httpx.AsyncClient() as client,
        aiofiles.tempfile.TemporaryDirectory() as tempd,
    ):
        tempdir = Path(tempd)
        tempfile = tempdir / local_path.name
        metadata = await db_session.get(CogFile, file_url)
        if metadata is None:
            raise Exception(f"Did not find entry in DB for url: {file_url}")
        try:
            print("Starting download of:", file_url)
            async with (
                client.stream(method="GET", url=file_url, timeout=timedelta(hours=1).total_seconds()) as response,
                aiofiles.open(tempfile, "wb") as tf,
            ):
                response.raise_for_status()
                async for chunk in response.aiter_bytes(8 * 1024 * 1024):
                    num_bytes = len(chunk)
                    await tf.write(chunk)
                    metadata.downloaded_bytes += num_bytes
                    metadata.download_pct = metadata.downloaded_bytes / metadata.total_size_bytes
                    db_session.add(metadata)
                    await db_session.commit()
                    await db_session.refresh(metadata)
            metadata.status = STATUS.downloaded
            db_session.add(metadata)
            await db_session.commit()
            await db_session.refresh(metadata)
            print(f"Downloaded file from url: {file_url}. Begin processing.")
            metadata.status = STATUS.processing
            db_session.add(metadata)
            await db_session.commit()
            await db_session.refresh(metadata)

            # Run the synchronous CPU-intensive operation in a thread pool
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, _translate, tempfile, local_path)
            
            print(f"Finished processing file from url: {file_url}")
            metadata.status = STATUS.ready
            db_session.add(metadata)
            await db_session.commit()
            await db_session.refresh(metadata)
        except Exception as e:
            print(f"There was an error in job for url: {file_url}", e)
            metadata.status = STATUS.error
            db_session.add(metadata)
            await db_session.commit()
            await db_session.refresh(metadata)
    print("Finished background download job for url:", file_url, "meta:", metadata)
