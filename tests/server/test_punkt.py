import warnings

import nltk
import pytest

from talemate.server import punkt

PUNKT_FILES = (
    "collocations.tab",
    "sent_starters.txt",
    "abbrev_types.txt",
    "ortho_context.tab",
)


def build_data_tree(root):
    """A real (if empty) punkt_tab/english tree the tokenizer can load."""
    english = root / "tokenizers" / "punkt_tab" / "english"
    english.mkdir(parents=True)
    for name in PUNKT_FILES:
        (english / name).write_text("")
    return root


def damage_ortho_context(root):
    (root / "tokenizers" / "punkt_tab" / "english" / "ortho_context.tab").write_text(
        "abc\t1\nxyz"
    )


def test_punkt_available_with_a_real_data_directory(tmp_path, monkeypatch):
    build_data_tree(tmp_path)
    monkeypatch.setattr(nltk.data, "path", [str(tmp_path)])

    with warnings.catch_warnings(record=True) as raised:
        warnings.simplefilter("always")
        assert punkt.punkt_available() is True

    assert raised == []


def test_punkt_available_false_when_the_language_directory_is_missing(
    tmp_path, monkeypatch
):
    (tmp_path / "tokenizers" / "punkt_tab").mkdir(parents=True)
    monkeypatch.setattr(nltk.data, "path", [str(tmp_path)])

    assert punkt.punkt_available() is False


def test_punkt_available_false_when_a_parameter_file_is_malformed(
    tmp_path, monkeypatch
):
    build_data_tree(tmp_path)
    damage_ortho_context(tmp_path)
    monkeypatch.setattr(nltk.data, "path", [str(tmp_path)])

    assert punkt.punkt_available() is False


@pytest.mark.asyncio
async def test_ensure_punkt_skips_download_when_available(tmp_path, monkeypatch):
    build_data_tree(tmp_path)
    monkeypatch.setattr(nltk.data, "path", [str(tmp_path)])
    downloads = []
    monkeypatch.setattr(nltk, "download", lambda package: downloads.append(package))

    with warnings.catch_warnings(record=True) as raised:
        warnings.simplefilter("always")
        await punkt.ensure_punkt()

    assert downloads == []
    assert raised == []


@pytest.mark.asyncio
async def test_ensure_punkt_downloads_both_when_data_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(nltk.data, "path", [str(tmp_path)])
    downloads = []

    def download(package):
        downloads.append(package)
        return True

    monkeypatch.setattr(nltk, "download", download)

    await punkt.ensure_punkt()

    assert downloads == ["punkt", "punkt_tab"]


@pytest.mark.asyncio
async def test_ensure_punkt_downloads_when_data_is_damaged(tmp_path, monkeypatch):
    build_data_tree(tmp_path)
    damage_ortho_context(tmp_path)
    monkeypatch.setattr(nltk.data, "path", [str(tmp_path)])
    downloads = []
    monkeypatch.setattr(nltk, "download", lambda package: downloads.append(package))

    await punkt.ensure_punkt()

    assert downloads == ["punkt", "punkt_tab"]
