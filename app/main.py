from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path
import urllib.parse
from typing import Annotated

import aiofiles
from apscheduler.schedulers.asyncio import BaseScheduler, AsyncIOScheduler
from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
import httpx
from sqlalchemy import Engine
from sqlmodel import Session
from starlette.middleware.cors import CORSMiddleware
from titiler.core.factory import TilerFactory

from app import utils
from app.config import settings
from app.db import create_db_and_tables, get_engine
from app.models import CURRENT_VERSION_NUMBER, STATUS, CogFile, CogFileStatus
from app.models import Version

APP_NAME = "temportofoto"


def get_db_session():
    with Session(db_engine) as db_session:
        yield db_session


def get_scheduler():
    yield scheduler


DbSessionDep = Annotated[Session, Depends(get_db_session)]
SchedulerDep = Annotated[BaseScheduler, Depends(get_scheduler)]


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    # startup operations:
    scheduler.start()
    create_db_and_tables(db_engine)
    # ---
    yield  # app is launched and this contextmanager is suspended until app is closed
    # shutdown operations:
    scheduler.shutdown(wait=True)
    # ---


scheduler = AsyncIOScheduler()
db_engine = get_engine(settings)
app = FastAPI(
    title=APP_NAME,
    summary="Aplikacja pozwalająca na używanie arkuszy ortofotomap udostepnianych przez Główny Urząd Geodezji i Kartografii w Geoportalu.",
    description="Aplikacja pobiera wskazany przez użytkownika arkusz ortofotomapy i udostępnia go w postaci kafelków rastrowych (XYZ), które można podpiąć w edytorach OSM. Pliki są przechowywane ograniczony czas.",
    version=utils.get_version_from_pyproject_file(),
    lifespan=app_lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create a TilerFactory for Cloud-Optimized GeoTIFFs
cog = TilerFactory(router_prefix="/titiler")
# Register all the COG endpoints automatically
app.include_router(cog.router, prefix="/titiler", tags=["TiTiler for Cloud Optimized GeoTIFF"])


@app.get("/version", response_model=Version)
async def version():
    try:
        dialect = db_engine.dialect.name
        version_tuple = db_engine.dialect.server_version_info or tuple()
    except Exception as e:
        dialect = "unknown"
        version_tuple = tuple()
    return Version(
        app_version=utils.get_version_from_pyproject_file(),
        db_schema_version=CURRENT_VERSION_NUMBER,
        db_version=f"{dialect}: {'.'.join(map(str, version_tuple))}",
    )


@app.get(
    "/file",
    response_model=CogFileStatus,
    responses={
        404: {"description": "Item not found."},
    },
)
async def file_status(db_session: DbSessionDep, file_url: str):
    """Returns status for a given file url."""
    f = db_session.get(CogFile, file_url)
    if f is None:
        return JSONResponse(
            status_code=404,
            content=f"Plik z url: {file_url} nie został jeszcze pobrany lub został już usunięty i nie jest dostepny.",
        )
    return CogFileStatus(
        url=f.url,
        abs_file_path=f.abs_file_path,
        request_dt=f.request_dt,
        delete_after=f.delete_after,
        status=f.status,
        total_size_bytes=f.total_size_bytes,
        downloaded_bytes=f.downloaded_bytes,
        download_pct=f.download_pct,
        tile_endpoint=settings.base_url
        + "/titiler/tiles/WebMercatorQuad/{z}/{x}/{y}@1x?url="
        + urllib.parse.quote_plus("file://" + f.abs_file_path),
    )


@app.post(
    "/file",
    responses={
        202: {"description": "Przyjęto żądanie. Plik będzie pobierany w tle."},
        409: {"description": "Plik z podanego url już jest procesowany."},
        503: {"description": "Serwer udostępniający plik nie odpowiedział poprawnie na zapytanie HEAD."},
    },
)
async def file_download(db_session: DbSessionDep, scheduler: SchedulerDep, file_url: str):
    """Requests backend to download a specified Cloud Optimized GeoTiff file from given URL
    and make it available in TiTiler endpoints serving XYZ raster tiles."""
    request_dt_utc = datetime.now(tz=UTC)
    f = db_session.get(CogFile, file_url)
    if f is not None:
        return JSONResponse(status_code=409, content=f"Plik z url: {file_url} jest już w bazie. Sprawdź jego status.")
    parsed_url = urllib.parse.urlparse(file_url)
    local_file_path = Path(settings.data_dir) / parsed_url.path.lstrip("/")
    local_file_path.parent.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient() as client:
        r = await client.head(url=file_url)
        cl = r.headers.get("Content-Length", None)
        total_size_bytes = int(cl) if cl else None
    if total_size_bytes is None:
        return JSONResponse(status_code=503, content="Serwer udostępniający plik nie podał rozmiaru pliku pod tym URL.")
    f = CogFile(
        url=file_url,
        abs_file_path=local_file_path.absolute().as_posix(),
        request_dt=request_dt_utc,
        delete_after=request_dt_utc + timedelta(days=7),
        status=STATUS.downloading,
        total_size_bytes=total_size_bytes,
        downloaded_bytes=0,
        download_pct=0.0,
    )
    db_session.add(f)
    db_session.commit()
    func = partial(download_file, file_url=file_url, local_path=local_file_path, db_engine=db_engine)
    job = scheduler.add_job(func, id=file_url, max_instances=1)
    return JSONResponse(
        status_code=202,
        content=f"Dodano zadanie pobrania pliku. Możesz sprawdzać jego status używając requesta GET z tym samym endpointem.",
    )


async def download_file(file_url: str, local_path: Path, db_engine: Engine):
    print("Starting background download job for url:", file_url)
    with Session(db_engine) as db_session:
        metadata = db_session.get(CogFile, file_url)
        if metadata is None:
            raise Exception(f"Did not find entry in DB for url: {file_url}")
        async with httpx.AsyncClient() as client, aiofiles.open(local_path, "wb") as fp:
            print("Starting download of:", file_url)
            async with client.stream(
                method="GET", url=file_url, timeout=timedelta(hours=1).total_seconds()
            ) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes(8 * 1024 * 1024):
                    num_bytes = len(chunk)
                    await fp.write(chunk)
                    metadata.downloaded_bytes += num_bytes
                    metadata.download_pct = metadata.downloaded_bytes / metadata.total_size_bytes
                    db_session.add(metadata)
                    db_session.commit()
                    db_session.refresh(metadata)
    metadata.status = STATUS.downloaded
    db_session.add(metadata)
    db_session.commit()
    db_session.refresh(metadata)
    print("Finished background download job for url:", file_url)
    print("Status object:", metadata)
