from pathlib import Path
from urllib.parse import unquote, urlsplit


def download_path(file_url: str, data_dir: Path) -> Path:
    parsed = urlsplit(file_url)
    if parsed.scheme != "https" or parsed.netloc != "opendata.geoportal.gov.pl" or parsed.query or parsed.fragment:
        raise ValueError("Only HTTPS Geoportal imagery URLs are supported.")
    path = unquote(parsed.path)
    if not path.startswith("/ortofotomapa/") or ".." in path.split("/") or "\x00" in path:
        raise ValueError("Invalid imagery path.")
    destination = (data_dir.resolve() / path.lstrip("/")).resolve()
    if not destination.is_relative_to(data_dir.resolve() / "ortofotomapa") or destination.suffix.lower() not in {
        ".tif",
        ".tiff",
    }:
        raise ValueError("Invalid imagery path.")
    return destination


def dataset_path(url: str, data_dir: Path) -> Path:
    parsed = urlsplit(url)
    if parsed.scheme != "file" or parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("Only registered local imagery is available.")
    path = Path(unquote(parsed.path)).resolve()
    if not path.is_relative_to(data_dir.resolve() / "ortofotomapa"):
        raise ValueError("Invalid imagery path.")
    return path
