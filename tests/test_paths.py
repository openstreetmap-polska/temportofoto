from pathlib import Path

import pytest

from app.paths import dataset_path, download_path


@pytest.mark.parametrize(
    "url",
    [
        "http://opendata.geoportal.gov.pl/ortofotomapa/a.tif",
        "https://example.org/ortofotomapa/a.tif",
        "https://opendata.geoportal.gov.pl@example.org/ortofotomapa/a.tif",
        "https://opendata.geoportal.gov.pl/ortofotomapa/../../app/main.py",
        "https://opendata.geoportal.gov.pl/ortofotomapa/%2e%2e/a.tif",
        "https://opendata.geoportal.gov.pl/ortofotomapa/a.tif?redirect=elsewhere",
        "https://opendata.geoportal.gov.pl/ortofotomapa/a.py",
        "https://opendata.geoportal.gov.pl/ortofotomapa/%00.tif",
        "https://[invalid/",
    ],
)
def test_download_rejects_untrusted_source_or_path(tmp_path: Path, url: str):
    with pytest.raises(ValueError):
        download_path(url, tmp_path)


def test_download_preserves_geoportal_layout(tmp_path: Path):
    assert (
        download_path("https://opendata.geoportal.gov.pl/ortofotomapa/83235/sheet.tif", tmp_path)
        == tmp_path / "ortofotomapa/83235/sheet.tif"
    )


def test_download_rejects_symlink_escape(tmp_path: Path):
    (tmp_path / "ortofotomapa").mkdir()
    (tmp_path / "ortofotomapa/escape").symlink_to(tmp_path.parent, target_is_directory=True)
    with pytest.raises(ValueError, match="Invalid imagery path"):
        download_path("https://opendata.geoportal.gov.pl/ortofotomapa/escape/sheet.tif", tmp_path)


@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "https://example.org/a.tif", "/vsicurl/https://example.org/a.tif"]
)
def test_dataset_rejects_external_paths(tmp_path: Path, url: str):
    with pytest.raises(ValueError):
        dataset_path(url, tmp_path)


def test_dataset_preserves_existing_file_urls(tmp_path: Path):
    path = tmp_path / "ortofotomapa/83235/sheet.tif"
    assert dataset_path(path.as_uri(), tmp_path) == path
