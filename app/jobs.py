import asyncio
import io
import re
from datetime import timedelta
from pathlib import Path

import aiofiles
import httpx
import morecantile
from rio_cogeo.cogeo import cog_translate
from rio_cogeo.profiles import cog_profiles
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, AsyncSession

from app.models import STATUS, CogFile


def _translate(src_path, dst_path, progress_out=None, **options):
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
        quiet=False if progress_out else True,
        tms=morecantile.tms.get("WebMercatorQuad"), # pyright: ignore[reportPrivateImportUsage]
        progress_out=progress_out,
        **options,
    )


# based on example from the bottom of the api docs page: https://cogeotiff.github.io/rio-cogeo/API/
def _get_percentage_from_buffer(buffer_content: str) -> float | None:
    """Extract percentage from progress buffer."""
    matches = re.findall(r"\d+(?:\.\d+)?[ ]?%", buffer_content)
    if matches:
        return float(matches[-1].replace("%", "")) / 100
    return None


async def _update_convert_progress(buffer: io.StringIO, db_session: AsyncSession, metadata: CogFile, update_interval_seconds: float = 1.0):
    """Periodically read conversion progress and update DB."""
    try:
        while True:
            current_content = buffer.getvalue()
            progress = _get_percentage_from_buffer(current_content)
            if progress is not None and progress > 0:
                metadata.convert_pct = progress
                db_session.add(metadata)
                await db_session.commit()
                await db_session.refresh(metadata)
            # If progress reached 100%, stop monitoring
            if progress is not None and progress >= 1.0:
                break
            await asyncio.sleep(update_interval_seconds)
    except asyncio.CancelledError:
        pass


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

            # Create progress buffer for tracking conversion
            progress_buffer = io.StringIO()
            progress_buffer.isatty = lambda: True  # docs say it must be interactive?

            # Create monitoring task to update progress in DB
            monitor_task = asyncio.create_task(_update_convert_progress(progress_buffer, db_session, metadata))

            # Run the synchronous CPU-intensive operation in a thread pool
            loop = asyncio.get_event_loop()
            conversion_future = loop.run_in_executor(None, _translate, tempfile, local_path, progress_buffer)

            try:
                # Wait for conversion to complete
                await conversion_future
            finally:
                # Cancel monitoring task
                monitor_task.cancel()
                try:
                    await monitor_task
                except asyncio.CancelledError:
                    pass

            # Final update to ensure convert_pct is at 100% or final value
            final_progress = _get_percentage_from_buffer(progress_buffer.getvalue())
            metadata.convert_pct = final_progress
            
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
