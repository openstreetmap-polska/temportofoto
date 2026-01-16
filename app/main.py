from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path
import urllib.parse
from typing import Annotated

from apscheduler.schedulers.asyncio import BaseScheduler, AsyncIOScheduler
from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
import httpx
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.ext.asyncio import async_sessionmaker
from starlette.middleware.cors import CORSMiddleware
from titiler.core.errors import DEFAULT_STATUS_CODES, add_exception_handlers
from titiler.core.factory import TilerFactory
from titiler.extensions.cogeo import cogValidateExtension
from titiler.extensions.viewer import cogViewerExtension

from app import utils
from app.config import settings
from app.db import create_db_and_tables, get_engine
from app.jobs import download_file
from app.models import CURRENT_VERSION_NUMBER, STATUS, CogFile, CogFileStatus
from app.models import Version

APP_NAME = "temportofoto"


async def get_db_engine():
    yield db_engine


async def get_db_session():
    async_session = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as db_session:
        yield db_session


async def get_scheduler():
    yield scheduler


DbEngineDep = Annotated[AsyncEngine, Depends(get_db_engine)]
DbSessionDep = Annotated[AsyncSession, Depends(get_db_session)]
SchedulerDep = Annotated[BaseScheduler, Depends(get_scheduler)]


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    # startup operations:
    scheduler.start()
    await create_db_and_tables(db_engine)
    # ---
    yield  # app is launched and this contextmanager is suspended until app is closed
    # shutdown operations:
    await db_engine.dispose(close=True)
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
cog = TilerFactory(
    router_prefix="/titiler",
    extensions=[
        cogValidateExtension(),  # the cogeoExtension will add a rio-cogeo /validate endpoint
        cogViewerExtension(),  # adds a /viewer endpoint which return an HTML viewer for simple COGs
    ],
)
# Register all the COG endpoints automatically
app.include_router(cog.router, prefix="/titiler", tags=["TiTiler for Cloud Optimized GeoTIFF"])
add_exception_handlers(app, DEFAULT_STATUS_CODES)

@app.get("/version", response_model=Version, tags=["api"])
async def version(db_engine: DbEngineDep):
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
    "/files",
    response_model=list[CogFileStatus],
    tags=["api"],
)
async def list_files(db_session: DbSessionDep):
    query = await db_session.exec(select(CogFile))
    result = []
    for f in query.all():
        if f.status == STATUS.ready:
            endpoint_url = (
                settings.base_url
                + "/titiler/tiles/WebMercatorQuad/{z}/{x}/{y}@1x.jpg?url="
                + urllib.parse.quote_plus("file://" + f.abs_file_path)
            )
        else:
            endpoint_url = None
        result.append(
            CogFileStatus(
                url=f.url,
                abs_file_path=f.abs_file_path,
                request_dt=f.request_dt,
                delete_after=f.delete_after,
                status=f.status,
                total_size_bytes=f.total_size_bytes,
                downloaded_bytes=f.downloaded_bytes,
                download_pct=f.download_pct,
                tile_endpoint=endpoint_url,
            )
        )
    return result


@app.get(
    "/file",
    response_model=CogFileStatus,
    responses={
        404: {"description": "Item not found."},
    },
    tags=["api"],
)
async def file_status(db_session: DbSessionDep, file_url: str):
    """Returns status for a given file url."""
    f = await db_session.get(CogFile, file_url)
    if f is None:
        return JSONResponse(
            status_code=404,
            content=f"Plik z url: {file_url} nie został jeszcze pobrany lub został już usunięty i nie jest dostepny.",
        )
    if f.status == STATUS.ready:
        endpoint_url = (
            settings.base_url
            + "/titiler/tiles/WebMercatorQuad/{z}/{x}/{y}@1x.jpg?url="
            + urllib.parse.quote_plus("file://" + f.abs_file_path)
        )
    else:
        endpoint_url = None
    return CogFileStatus(
        url=f.url,
        abs_file_path=f.abs_file_path,
        request_dt=f.request_dt,
        delete_after=f.delete_after,
        status=f.status,
        total_size_bytes=f.total_size_bytes,
        downloaded_bytes=f.downloaded_bytes,
        download_pct=f.download_pct,
        tile_endpoint=endpoint_url,
    )


@app.post(
    "/file",
    responses={
        202: {"description": "Przyjęto żądanie. Plik będzie pobierany w tle."},
        409: {"description": "Plik z podanego url już jest procesowany."},
        503: {"description": "Serwer udostępniający plik nie odpowiedział poprawnie na zapytanie HEAD."},
    },
    tags=["api"],
)
async def file_download(db_session: DbSessionDep, scheduler: SchedulerDep, file_url: str):
    """Requests backend to download a specified Cloud Optimized GeoTiff file from given URL
    and make it available in TiTiler endpoints serving XYZ raster tiles."""
    request_dt_utc = datetime.now(tz=UTC)
    f = await db_session.get(CogFile, file_url)
    if f is not None and f.status != STATUS.error:
        return JSONResponse(status_code=409, content=f"Plik z url: {file_url} jest już w bazie. Sprawdź jego status.")
    parsed_url = urllib.parse.urlparse(file_url)
    local_file_path = Path(settings.data_dir) / parsed_url.path.lstrip("/")
    local_file_path.parent.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient() as client:
        try:
            r = await client.head(url=file_url, timeout=15.0)
        except (httpx.ReadTimeout, httpx.ConnectTimeout):
            return JSONResponse(
                status_code=503,
                content="Serwer udostępniający plik nie podał rozmiaru pliku pod tym URL w wymaganym czasie. Spróbuj jeszcze raz później.",
            )
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
    await db_session.commit()
    func = partial(download_file, file_url=file_url, local_path=local_file_path, db_engine=db_engine)
    job = scheduler.add_job(func, id=file_url, max_instances=1)
    return JSONResponse(
        status_code=202,
        content=f"Dodano zadanie pobrania pliku. Możesz sprawdzać jego status używając requesta GET z tym samym endpointem.",
    )
