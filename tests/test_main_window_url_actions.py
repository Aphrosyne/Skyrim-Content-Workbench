"""MainWindow 网址/搜索右键动作测试（操作便捷性8/9，2026-08-04）。

覆盖：
- 右键菜单显示/隐藏（内容单元两项 / 普通条目仅浏览器搜索 / 多选全无）
- 自动填入网址：Nexus 命名文件/文件夹最小 ID、非 Nexus 静默、不覆盖已有 URL
- 打开网址：空 URL 先自动填入再打开、无法填入静默、已有 URL 直接打开
- 浏览器搜索：与创建 Mod 组同名提取 + _/- → 空格 + 前缀 + 搜索引擎
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402

from app import ui_constants as ui  # noqa: E402
from app.main_window import MainWindow  # noqa: E402
from application.content_service import ContentService  # noqa: E402
from application.file_operation_service import FileOperationService  # noqa: E402
from application.folder_tree_service import FolderTreeService  # noqa: E402
from application.managed_root_service import ManagedRootService  # noqa: E402
from application.scan_service import ScanService  # noqa: E402
from domain.models import FileEntry  # noqa: E402
from infrastructure.db import get_connection, init_db  # noqa: E402
from infrastructure.folder_cache_sync_helper import FolderCacheSyncHelper  # noqa: E402
from infrastructure.repositories.content_unit import ContentUnitRepository  # noqa: E402
from infrastructure.repositories.folder_cache import FolderCacheRepository  # noqa: E402
from infrastructure.repositories.managed_root import (  # noqa: E402
    ManagedRootRepository,
)
from infrastructure.repositories.operation_history import (  # noqa: E402
    OperationHistoryRepository,
)


def _make_tree(tmp_path: Path) -> Path:
    """构造测试目录树：Nexus 命名/非 Nexus 压缩包 + 本体文件夹 + 普通文件。"""
    root = tmp_path / "mods"
    root.mkdir()
    stash = root / "Stash"
    stash.mkdir()
    (stash / "Birthplace of a Kitsune-26416-1-1-1588673209.zip").write_bytes(b"\x00" * 100)
    (stash / "RealisticWater.7z").write_bytes(b"\x00" * 100)
    folder = stash / "Kitsune Mod"
    folder.mkdir()
    (folder / "Kitsune Mod-26416-1-0.zip").write_bytes(b"a")
    (folder / "汉化补丁-120000-1-0.zip").write_bytes(b"b")
    (stash / "readme.txt").write_text("hello", encoding="utf-8")
    return root


@pytest.fixture
def url_env(qapp, tmp_path: Path):
    """构造注入 ContentService/ScanService 的 MainWindow 测试环境。"""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row

    counter = {"n": 0}

    def fake_uuid() -> str:
        counter["n"] += 1
        return f"id-{counter['n']}"

    managed_service = ManagedRootService(
        ManagedRootRepository(conn),
        FolderCacheRepository(conn),
        ContentUnitRepository(conn),
        now_provider=lambda: "2026-08-04T00:00:00Z",
        uuid_provider=fake_uuid,
    )
    tree_service = FolderTreeService(
        ManagedRootRepository(conn),
        FolderCacheRepository(conn),
    )
    content_service = ContentService(ContentUnitRepository(conn))
    scan_service = ScanService(
        managed_root_repo=ManagedRootRepository(conn),
        folder_cache_repo=FolderCacheRepository(conn),
        content_unit_repo=ContentUnitRepository(conn),
        now_provider=lambda: "2026-08-04T00:00:00Z",
        uuid_provider=fake_uuid,
    )
    file_op_service = FileOperationService(
        OperationHistoryRepository(conn),
        folder_cache_helper=FolderCacheSyncHelper(FolderCacheRepository(conn)),
        content_unit_repo=ContentUnitRepository(conn),
    )

    root_dir = _make_tree(tmp_path)
    root = managed_service.add_root(root_dir)
    scan_service.scan_root(root.id, incremental=False)
    conn.commit()

    window = MainWindow(
        managed_service,
        tree_service,
        content_service,
        db_path,
        commit_callback=conn.commit,
        file_operation_service=file_op_service,
    )
    _select_staging(qapp, window)
    yield window, conn, root_dir

    window.close()
    conn.close()


def _select_staging(qapp, window: MainWindow) -> None:
    """在目录树中选中暂存区 Stash 节点。"""
    model = window._tree_model  # noqa: SLF001
    root_idx = model.index(0, 0)
    model.fetchMore(root_idx)
    for i in range(model.rowCount(root_idx)):
        child_idx = model.index(i, 0, root_idx)
        name = model.data(child_idx, Qt.DisplayRole)
        if name and "Stash" in name:
            window._tree_view.setCurrentIndex(child_idx)  # noqa: SLF001
            qapp.processEvents()
            return
    pytest.fail("未找到 Stash 节点")


def _find_entry_by_name(window: MainWindow, name: str) -> FileEntry | None:
    model = window._content_list_model  # noqa: SLF001
    for row in range(model.entry_count()):
        entry = model.entry_at(row)
        if entry is not None and entry.name == name:
            return entry
    return None


def _fake_open(record: list[str]):
    def _open(url: str) -> bool:
        record.append(url)
        return True

    return _open


class TestUrlMenu:
    def test_content_unit_shows_url_and_search_actions(self, qapp, url_env) -> None:
        """单选内容单元 → 自动填入网址 / 打开网址 / 浏览器搜索。"""
        window, _, _ = url_env
        entry = _find_entry_by_name(window, "Birthplace of a Kitsune-26416-1-1-1588673209.zip")
        assert entry is not None and entry.content_unit is not None

        labels = [a[0] for a in window._build_content_menu_actions([entry])]  # noqa: SLF001
        assert ui.MENU_AUTOFILL_URL in labels
        assert ui.MENU_OPEN_URL in labels
        assert ui.MENU_BROWSER_SEARCH in labels

    def test_plain_entry_shows_only_search(self, qapp, url_env) -> None:
        """单选非内容单元 → 仅浏览器搜索。"""
        window, _, _ = url_env
        entry = _find_entry_by_name(window, "readme.txt")
        assert entry is not None and entry.content_unit is None

        labels = [a[0] for a in window._build_content_menu_actions([entry])]  # noqa: SLF001
        assert ui.MENU_AUTOFILL_URL not in labels
        assert ui.MENU_OPEN_URL not in labels
        assert ui.MENU_BROWSER_SEARCH in labels

    def test_multiselect_shows_none(self, qapp, url_env) -> None:
        """多选 → 三个动作都不显示。"""
        window, _, _ = url_env
        a = _find_entry_by_name(window, "Birthplace of a Kitsune-26416-1-1-1588673209.zip")
        b = _find_entry_by_name(window, "RealisticWater.7z")
        assert a is not None and b is not None

        labels = [x[0] for x in window._build_content_menu_actions([a, b])]  # noqa: SLF001
        assert ui.MENU_AUTOFILL_URL not in labels
        assert ui.MENU_OPEN_URL not in labels
        assert ui.MENU_BROWSER_SEARCH not in labels


class TestAutofillUrl:
    def test_fills_nexus_file_url(self, qapp, url_env) -> None:
        """Nexus 命名文件 → 自动填入 prefix+ID。"""
        window, conn, _ = url_env
        entry = _find_entry_by_name(window, "Birthplace of a Kitsune-26416-1-1-1588673209.zip")
        assert entry is not None

        window._on_autofill_url(entry)  # noqa: SLF001
        conn.commit()

        unit = window._content_service.get_by_id(entry.content_unit.id)  # noqa: SLF001
        assert unit.source_url == ("https://www.nexusmods.com/skyrimspecialedition/mods/26416")

    def test_non_nexus_file_stays_empty_silently(self, qapp, url_env) -> None:
        """非 Nexus 压缩包 → 不填、静默（无 URL、无异常）。"""
        window, conn, _ = url_env
        entry = _find_entry_by_name(window, "RealisticWater.7z")
        assert entry is not None

        window._on_autofill_url(entry)  # noqa: SLF001
        conn.commit()

        unit = window._content_service.get_by_id(entry.content_unit.id)  # noqa: SLF001
        assert unit.source_url is None

    def test_folder_uses_min_id(self, qapp, url_env) -> None:
        """文件夹内容单元 → 内部文件取最小 ID（本体 26416 < 汉化 120000）。"""
        window, conn, root_dir = url_env
        folder_path = root_dir / "Stash" / "Kitsune Mod"
        unit = window._content_service.mark_as_content_unit(folder_path)  # noqa: SLF001
        conn.commit()
        entry = FileEntry(
            name=folder_path.name,
            path=str(folder_path),
            is_dir=True,
            modified_at="2026-08-04T00:00:00Z",
            size=None,
            content_unit=unit,
        )

        window._on_autofill_url(entry)  # noqa: SLF001
        conn.commit()

        fresh = window._content_service.get_by_id(unit.id)  # noqa: SLF001
        assert fresh.source_url == "https://www.nexusmods.com/skyrimspecialedition/mods/26416"

    def test_does_not_overwrite_existing_url(self, qapp, url_env) -> None:
        """已有 source_url → 不覆盖。"""
        window, conn, _ = url_env
        entry = _find_entry_by_name(window, "Birthplace of a Kitsune-26416-1-1-1588673209.zip")
        assert entry is not None
        window._content_service.update_metadata(  # noqa: SLF001
            entry.content_unit.id, source_url="https://example.com/manual"
        )
        conn.commit()

        window._on_autofill_url(entry)  # noqa: SLF001
        conn.commit()

        unit = window._content_service.get_by_id(entry.content_unit.id)  # noqa: SLF001
        assert unit.source_url == "https://example.com/manual"


class TestOpenUrl:
    def test_empty_url_fills_then_opens(
        self, qapp, url_env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """URL 为空 → 先自动填入再打开。"""
        window, conn, _ = url_env
        entry = _find_entry_by_name(window, "Birthplace of a Kitsune-26416-1-1-1588673209.zip")
        assert entry is not None
        opened: list[str] = []
        monkeypatch.setattr("app.content_list_controller.webbrowser.open", _fake_open(opened))

        window._on_open_url(entry)  # noqa: SLF001
        conn.commit()

        assert opened == ["https://www.nexusmods.com/skyrimspecialedition/mods/26416"]
        unit = window._content_service.get_by_id(entry.content_unit.id)  # noqa: SLF001
        assert unit.source_url == "https://www.nexusmods.com/skyrimspecialedition/mods/26416"

    def test_cannot_fill_does_nothing_silently(
        self, qapp, url_env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """无法识别 → 不打开、不填、静默。"""
        window, conn, _ = url_env
        entry = _find_entry_by_name(window, "RealisticWater.7z")
        assert entry is not None
        opened: list[str] = []
        monkeypatch.setattr("app.content_list_controller.webbrowser.open", _fake_open(opened))

        window._on_open_url(entry)  # noqa: SLF001
        conn.commit()

        assert opened == []
        unit = window._content_service.get_by_id(entry.content_unit.id)  # noqa: SLF001
        assert unit.source_url is None

    def test_existing_url_opens_directly(
        self, qapp, url_env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """已有 URL → 直接打开，不改变。"""
        window, conn, _ = url_env
        entry = _find_entry_by_name(window, "RealisticWater.7z")
        assert entry is not None
        window._content_service.update_metadata(  # noqa: SLF001
            entry.content_unit.id, source_url="https://example.com/set"
        )
        conn.commit()
        opened: list[str] = []
        monkeypatch.setattr("app.content_list_controller.webbrowser.open", _fake_open(opened))

        window._on_open_url(entry)  # noqa: SLF001

        assert opened == ["https://example.com/set"]


class TestBrowserSearch:
    def test_search_query_uses_extract_mod_name(
        self, qapp, url_env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Nexus 文件：去尾号 + _/-→空格 + 前缀，拼到搜索引擎。"""
        window, _, _ = url_env
        entry = _find_entry_by_name(window, "Birthplace of a Kitsune-26416-1-1-1588673209.zip")
        assert entry is not None
        opened: list[str] = []
        monkeypatch.setattr("app.content_list_controller.webbrowser.open", _fake_open(opened))

        window._on_browser_search(entry)  # noqa: SLF001

        assert len(opened) == 1
        # 不出现 `?q=q=…` 双查询参数（验收反馈 2026-08-04）
        assert "q=q=" not in opened[0]
        assert opened[0] == ("https://www.bing.com/search?q=skyrim+Birthplace+of+a+Kitsune")

    def test_search_plain_folder_name(self, qapp, url_env, monkeypatch: pytest.MonkeyPatch) -> None:
        """普通文件夹名：直接搜索（空格保留）。"""
        window, _, _ = url_env
        entry = _find_entry_by_name(window, "Kitsune Mod")
        assert entry is not None
        opened: list[str] = []
        monkeypatch.setattr("app.content_list_controller.webbrowser.open", _fake_open(opened))

        window._on_browser_search(entry)  # noqa: SLF001

        assert len(opened) == 1
        assert opened[0] == "https://www.bing.com/search?q=skyrim+Kitsune+Mod"
