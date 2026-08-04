"""ArchiveManifestService 单元测试（功能增加1 归档内容清单，2026-08-04）。"""

from __future__ import annotations

from pathlib import Path

from application.archive_manifest_service import ArchiveManifestService


def _make_archive_dir(tmp_path: Path) -> Path:
    """构造含文件夹/文件混合子项的归档目录。"""
    archive = tmp_path / "99_归档"
    archive.mkdir()
    (archive / "Beta").mkdir()
    (archive / "Alpha 文件夹").mkdir()
    (archive / "zeta.7z").write_bytes(b"\x00" * 10)
    (archive / "alpha.7z").write_bytes(b"\x00" * 10)
    return archive


def test_generate_manifest_folders_first_sorted(tmp_path: Path) -> None:
    """文件夹在前、文件在后，各自按名称不区分大小写排序；仅直接子项。"""
    archive = _make_archive_dir(tmp_path)
    (archive / "sub" / "nested.7z").parent.mkdir(exist_ok=True)
    (archive / "sub" / "nested.7z").write_bytes(b"\x00")
    service = ArchiveManifestService()

    output = service.generate_manifest(archive, tmp_path)

    assert output == tmp_path / "99_归档归档内容.txt"
    lines = output.read_text(encoding="utf-8").splitlines()
    assert lines == [
        "Alpha 文件夹",
        "Beta",
        "sub",
        "alpha.7z",
        "zeta.7z",
    ]
    # 不向内搜索：sub 内文件不出现
    assert "nested.7z" not in lines


def test_generate_manifest_utf8_and_empty(tmp_path: Path) -> None:
    """中文文件名 UTF-8 写出；空目录生成空清单。"""
    empty = tmp_path / "空归档"
    empty.mkdir()
    service = ArchiveManifestService()

    output = service.generate_manifest(empty, tmp_path)

    assert output.read_text(encoding="utf-8") == ""


def test_generate_manifest_overwrites_previous(tmp_path: Path) -> None:
    """重复生成覆盖旧清单（派生文件，非用户数据）。"""
    archive = _make_archive_dir(tmp_path)
    service = ArchiveManifestService()

    first = service.generate_manifest(archive, tmp_path)
    first.write_text("stale", encoding="utf-8")
    second = service.generate_manifest(archive, tmp_path)

    assert second == first
    assert "stale" not in second.read_text(encoding="utf-8")
