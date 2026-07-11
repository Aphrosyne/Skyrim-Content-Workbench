"""MainWindow 测试。

覆盖：
- 构造（依赖注入）；
- 根目录列表显示；
- 扫描按钮在无选择时不可用；
- 扫描状态文本变化可测试（通过公共接口）。

若 PySide6 未安装则跳过整个模块。
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QListWidget  # noqa: E402

from app.main_window import MainWindow  # noqa: E402
from application.folder_tree_service import FolderTreeService  # noqa: E402
from application.managed_root_service import ManagedRootService  # noqa: E402
from application.mod_assembly_service import ModAssemblyService  # noqa: E402
from infrastructure.repositories.file_asset import FileAssetRepository  # noqa: E402
from infrastructure.repositories.folder_node import FolderNodeRepository  # noqa: E402
from infrastructure.repositories.managed_root import ManagedRootRepository  # noqa: E402
from infrastructure.repositories.mod_item import ModItemRepository  # noqa: E402


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    yield app


def _make_window(db_connection, db_path: Path) -> MainWindow:
    """构造 MainWindow，注入已配置的 service。"""
    service = ManagedRootService(ManagedRootRepository(db_connection))
    tree_service = FolderTreeService(
        ManagedRootRepository(db_connection), FolderNodeRepository(db_connection)
    )
    mod_service = ModAssemblyService(
        ModItemRepository(db_connection), FileAssetRepository(db_connection)
    )
    return MainWindow(
        service, tree_service, mod_service, db_path, commit_callback=db_connection.commit
    )


def test_main_window_constructs(qapp: QApplication, db_connection, db_path: Path) -> None:
    """主窗口可正常构造，标题与初始状态正确。"""
    window = _make_window(db_connection, db_path)
    assert window.windowTitle() == "Skyrim Mod Workbench"
    assert window.root_count() == 0
    # 初始无选中，扫描按钮应禁用
    assert window.is_scan_button_enabled() is False
    # 初始状态文本
    assert window.status_text() == "就绪"


def test_main_window_shows_existing_roots(
    qapp: QApplication, db_connection, db_path: Path, tmp_path: Path
) -> None:
    """已保存的根目录在窗口启动时应在列表中显示。"""
    # 先在数据库中添加一个根目录
    service = ManagedRootService(
        ManagedRootRepository(db_connection),
        now_provider=lambda: "2026-07-07T00:00:00Z",
        uuid_provider=lambda: "uuid-1",
    )
    mods = tmp_path / "已保存模组"
    mods.mkdir()
    service.add_root(mods)

    # 新建窗口应能看到已保存的根目录
    window = _make_window(db_connection, db_path)
    assert window.root_count() == 1


def test_main_window_scan_button_disabled_without_selection(
    qapp: QApplication, db_connection, db_path: Path, tmp_path: Path
) -> None:
    """有根目录但未选中时，扫描按钮应禁用。"""
    service = ManagedRootService(
        ManagedRootRepository(db_connection),
        now_provider=lambda: "2026-07-07T00:00:00Z",
        uuid_provider=lambda: "uuid-1",
    )
    mods = tmp_path / "Mods"
    mods.mkdir()
    service.add_root(mods)

    window = _make_window(db_connection, db_path)
    assert window.root_count() == 1
    # 默认未选中
    assert window.is_scan_button_enabled() is False


def test_main_window_scan_button_enabled_with_selection(
    qapp: QApplication, db_connection, db_path: Path, tmp_path: Path
) -> None:
    """选中根目录后扫描按钮应可用。"""
    service = ManagedRootService(
        ManagedRootRepository(db_connection),
        now_provider=lambda: "2026-07-07T00:00:00Z",
        uuid_provider=lambda: "uuid-1",
    )
    mods = tmp_path / "Mods"
    mods.mkdir()
    service.add_root(mods)

    window = _make_window(db_connection, db_path)
    # 模拟选中第一项
    list_widget = window.findChild(QListWidget)
    assert list_widget is not None
    list_widget.setCurrentRow(0)

    assert window.is_scan_button_enabled() is True


def test_main_window_status_text_settable(qapp: QApplication, db_connection, db_path: Path) -> None:
    """status_text 可读取初始状态。"""
    window = _make_window(db_connection, db_path)
    assert window.status_text() == "就绪"


def test_main_window_scan_completes_without_crash(
    qapp: QApplication, db_path: Path, sample_mod_tree: Path
) -> None:
    """扫描完成后进程不应因 QThread 析构 CTD；按钮恢复、状态更新。

    回归测试：修复前 _end_scanning 清空 _thread 引用，QThread 在 Running
    状态被析构，扫描完成后进程崩溃（QThread: Destroyed while thread is still running）。
    """
    from infrastructure.db import get_connection, init_db
    from infrastructure.repositories.managed_root import ManagedRootRepository

    init_db(db_path)
    conn = get_connection(db_path)
    conn.row_factory = __import__("sqlite3").Row
    try:
        service = ManagedRootService(
            ManagedRootRepository(conn),
            now_provider=lambda: "2026-07-07T00:00:00Z",
            uuid_provider=lambda: "scan-crash-test",
        )
        service.add_root(sample_mod_tree)
        conn.commit()
    finally:
        conn.close()

    # 用独立 service 构造窗口（不依赖已关闭连接）
    conn2 = get_connection(db_path)
    conn2.row_factory = __import__("sqlite3").Row
    service2 = ManagedRootService(ManagedRootRepository(conn2))
    tree_service2 = FolderTreeService(ManagedRootRepository(conn2), FolderNodeRepository(conn2))
    mod_service2 = ModAssemblyService(ModItemRepository(conn2), FileAssetRepository(conn2))
    window = MainWindow(
        service2, tree_service2, mod_service2, db_path, commit_callback=conn2.commit
    )
    assert window.root_count() == 1

    # 选中根目录并触发扫描
    list_widget = window.findChild(QListWidget)
    assert list_widget is not None
    list_widget.setCurrentRow(0)
    assert window.is_scan_button_enabled() is True

    window._on_scan()  # noqa: SLF001  直接触发，避免按钮事件封装
    assert window._is_scanning is True  # noqa: SLF001
    assert window.is_scan_button_enabled() is False

    # 等待扫描线程退出（最长 30 秒）
    import time

    deadline = time.monotonic() + 30.0
    while window._thread is not None and time.monotonic() < deadline:  # noqa: SLF001
        qapp.processEvents()
        time.sleep(0.05)

    # 线程引用应已被 _on_thread_finished 清空（证明线程安全退出）
    assert window._thread is None, "扫描线程未在超时内退出"
    assert window._worker is None  # noqa: SLF001
    # 按钮恢复
    assert window.is_scan_button_enabled() is True
    # 状态文本应包含扫描完成摘要
    status = window.status_text()
    assert "扫描完成" in status or "扫描失败" in status, f"状态文本异常：{status}"

    conn2.close()


def test_main_window_close_event_safe_when_idle(
    qapp: QApplication, db_connection, db_path: Path
) -> None:
    """无扫描进行时 closeEvent 应正常执行，不抛异常。"""
    window = _make_window(db_connection, db_path)
    from PySide6.QtGui import QCloseEvent

    window.closeEvent(QCloseEvent())
    # 无异常即通过


def test_main_window_has_tree_view(qapp: QApplication, db_connection, db_path: Path) -> None:
    """主窗口包含目录树视图。"""
    from PySide6.QtWidgets import QTreeView

    window = _make_window(db_connection, db_path)
    tree_view = window.findChild(QTreeView)
    assert tree_view is not None
    # 初始无根目录，树顶层节点数为 0
    assert window.tree_root_count() == 0


def test_main_window_tree_shows_unscanned_root(
    qapp: QApplication, db_connection, db_path: Path, tmp_path: Path
) -> None:
    """已配置但未扫描的根目录在树中显示为"未扫描"。"""
    service = ManagedRootService(
        ManagedRootRepository(db_connection),
        now_provider=lambda: "2026-07-07T00:00:00Z",
        uuid_provider=lambda: "uuid-1",
    )
    mods = tmp_path / "未扫描目录"
    mods.mkdir()
    service.add_root(mods)

    window = _make_window(db_connection, db_path)
    assert window.tree_root_count() == 1


def test_main_window_detail_updates_on_tree_selection(
    qapp: QApplication, db_connection, db_path: Path, sample_mod_tree: Path
) -> None:
    """选中目录树节点后详情区域更新。"""
    from PySide6.QtWidgets import QTreeView

    # 添加并扫描根目录
    service = ManagedRootService(
        ManagedRootRepository(db_connection),
        now_provider=lambda: "2026-07-07T00:00:00Z",
        uuid_provider=lambda: "uuid-1",
    )
    service.add_root(sample_mod_tree)
    from infrastructure.file_scanner import FileScanner, persist_scan_result
    from infrastructure.repositories.file_asset import FileAssetRepository
    from infrastructure.repositories.folder_node import FolderNodeRepository

    scanner = FileScanner()
    result = scanner.scan(sample_mod_tree)
    persist_scan_result(
        result,
        FolderNodeRepository(db_connection),
        FileAssetRepository(db_connection),
    )
    db_connection.commit()

    window = _make_window(db_connection, db_path)
    assert window.tree_root_count() == 1

    # 初始详情为提示
    assert "未选中" in window.detail_text()

    # 选中根节点
    tree_view = window.findChild(QTreeView)
    assert tree_view is not None

    model = tree_view.model()
    root_idx = model.index(0, 0)
    tree_view.setCurrentIndex(root_idx)

    detail = window.detail_text()
    assert sample_mod_tree.name in detail
    assert str(sample_mod_tree) in detail
    assert "受管理根目录" in detail


def test_main_window_tree_refresh_after_scan(
    qapp: QApplication, db_path: Path, sample_mod_tree: Path
) -> None:
    """扫描完成后目录树刷新，展示扫描得到的子目录。"""
    from infrastructure.db import get_connection, init_db
    from infrastructure.repositories.folder_node import FolderNodeRepository

    init_db(db_path)
    conn = get_connection(db_path)
    conn.row_factory = __import__("sqlite3").Row
    try:
        service = ManagedRootService(
            ManagedRootRepository(conn),
            now_provider=lambda: "2026-07-07T00:00:00Z",
            uuid_provider=lambda: "scan-tree-test",
        )
        service.add_root(sample_mod_tree)
        conn.commit()
    finally:
        conn.close()

    # 构造窗口（扫描前树显示为未扫描）
    conn2 = get_connection(db_path)
    conn2.row_factory = __import__("sqlite3").Row
    service2 = ManagedRootService(ManagedRootRepository(conn2))
    tree_service2 = FolderTreeService(ManagedRootRepository(conn2), FolderNodeRepository(conn2))
    mod_service2 = ModAssemblyService(ModItemRepository(conn2), FileAssetRepository(conn2))
    window = MainWindow(
        service2, tree_service2, mod_service2, db_path, commit_callback=conn2.commit
    )
    assert window.tree_root_count() == 1

    # 选中并扫描
    list_widget = window.findChild(QListWidget)
    assert list_widget is not None
    list_widget.setCurrentRow(0)
    window._on_scan()  # noqa: SLF001

    # 等待扫描完成
    import time

    deadline = time.monotonic() + 30.0
    while window._thread is not None and time.monotonic() < deadline:  # noqa: SLF001
        qapp.processEvents()
        time.sleep(0.05)

    assert window._thread is None  # noqa: SLF001
    # 扫描完成后树仍为 1 个顶层节点（根），但根已关联 FolderNode
    assert window.tree_root_count() == 1

    # 回归验证：扫描结果必须已持久化，根节点不再是"未扫描"，
    # 且可展开有子节点（修复前因事务未提交，根仍为未扫描、无子节点）。
    from PySide6.QtWidgets import QTreeView

    tree_view = window.findChild(QTreeView)
    assert tree_view is not None
    model = tree_view.model()
    root_idx = model.index(0, 0)
    assert root_idx.isValid()
    # 根节点 display name 不应包含"未扫描"
    root_display = model.data(root_idx, Qt.DisplayRole)
    assert "未扫描" not in root_display, f"扫描后根目录仍为未扫描：{root_display}"
    # 可展开有子节点
    assert model.canFetchMore(root_idx) is True or model.rowCount(root_idx) > 0
    model.fetchMore(root_idx)
    assert model.rowCount(root_idx) > 0, "扫描后根目录无可展开的子节点"

    conn2.close()


# === Task 3：素材池与 Mod 组装 UI 测试 ===


def test_main_window_pool_empty_on_init(qapp: QApplication, db_connection, db_path: Path) -> None:
    """初始无扫描数据时素材池为空。"""
    window = _make_window(db_connection, db_path)
    assert window.pool_count() == 0
    assert window.mod_list_count() == 0


def test_main_window_pool_shows_unassociated_after_scan(
    qapp: QApplication, db_connection, db_path: Path, sample_mod_tree: Path
) -> None:
    """扫描后未关联素材进入素材池。"""
    from infrastructure.file_scanner import FileScanner, persist_scan_result
    from infrastructure.repositories.file_asset import FileAssetRepository

    service = ManagedRootService(
        ManagedRootRepository(db_connection),
        now_provider=lambda: "2026-07-07T00:00:00Z",
        uuid_provider=lambda: "uuid-pool",
    )
    service.add_root(sample_mod_tree)
    scanner = FileScanner()
    result = scanner.scan(sample_mod_tree)
    persist_scan_result(
        result,
        FolderNodeRepository(db_connection),
        FileAssetRepository(db_connection),
    )
    db_connection.commit()

    window = _make_window(db_connection, db_path)
    # sample_mod_tree 含 7 个文件 + 3 个子文件夹 = 10 个 FileAsset，全部未关联
    assert window.pool_count() == 10
    assert window.mod_list_count() == 0


def test_main_window_associate_assets_to_new_mod(
    qapp: QApplication, db_connection, db_path: Path, sample_mod_tree: Path
) -> None:
    """创建 ModItem 并关联素材后，素材从素材池消失、出现在成员表。"""
    from infrastructure.file_scanner import FileScanner, persist_scan_result
    from infrastructure.repositories.file_asset import FileAssetRepository

    service = ManagedRootService(
        ManagedRootRepository(db_connection),
        now_provider=lambda: "2026-07-07T00:00:00Z",
        uuid_provider=lambda: "uuid-assoc",
    )
    service.add_root(sample_mod_tree)
    scanner = FileScanner()
    result = scanner.scan(sample_mod_tree)
    persist_scan_result(
        result,
        FolderNodeRepository(db_connection),
        FileAssetRepository(db_connection),
    )
    db_connection.commit()

    window = _make_window(db_connection, db_path)
    assert window.pool_count() == 10

    # 创建 ModItem
    mod_service = ModAssemblyService(
        ModItemRepository(db_connection), FileAssetRepository(db_connection)
    )
    mod_service.create_mod_item(display_name="测试条目")
    db_connection.commit()
    window._refresh_mod_list()  # noqa: SLF001
    assert window.mod_list_count() == 1

    # 选中 ModItem
    model = window._mod_list_model  # noqa: SLF001
    idx = model.index(0)
    window._mod_list_view.setCurrentIndex(idx)  # noqa: SLF001
    qapp.processEvents()

    # 验证详情加载
    assert window.mod_detail_name() == "测试条目"
    assert window.members_table_row_count() == 0

    # 选中素材池前 3 个素材
    pool_model = window._pool_model  # noqa: SLF001
    from PySide6.QtCore import QItemSelectionModel

    for i in range(3):
        idx = pool_model.index(i)
        window._pool_view.selectionModel().select(  # noqa: SLF001
            idx, QItemSelectionModel.SelectionFlag.Select
        )
    qapp.processEvents()

    # 关联
    window._on_associate()  # noqa: SLF001

    # 素材池减少 3 个
    assert window.pool_count() == 7
    # 成员表增加 3 个
    assert window.members_table_row_count() == 3


def test_main_window_remove_member_returns_to_pool(
    qapp: QApplication, db_connection, db_path: Path, sample_mod_tree: Path
) -> None:
    """移除成员后素材回到素材池。"""
    from infrastructure.file_scanner import FileScanner, persist_scan_result
    from infrastructure.repositories.file_asset import FileAssetRepository

    service = ManagedRootService(
        ManagedRootRepository(db_connection),
        now_provider=lambda: "2026-07-07T00:00:00Z",
        uuid_provider=lambda: "uuid-remove",
    )
    service.add_root(sample_mod_tree)
    scanner = FileScanner()
    result = scanner.scan(sample_mod_tree)
    persist_scan_result(
        result,
        FolderNodeRepository(db_connection),
        FileAssetRepository(db_connection),
    )
    db_connection.commit()

    # 先通过 service 关联一个素材到 ModItem
    mod_service = ModAssemblyService(
        ModItemRepository(db_connection), FileAssetRepository(db_connection)
    )
    mod_item = mod_service.create_mod_item(display_name="移除测试")
    unassociated = mod_service.list_unassociated_assets()
    assert len(unassociated) > 0
    first_asset = unassociated[0]
    from domain.models import FileRole

    mod_service.add_member(mod_item.id, first_asset.id, FileRole.MAIN_MOD)
    db_connection.commit()

    window = _make_window(db_connection, db_path)
    # 素材池少 1 个
    assert window.pool_count() == 9

    # 选中 ModItem
    model = window._mod_list_model  # noqa: SLF001
    idx = model.index(0)
    window._mod_list_view.setCurrentIndex(idx)  # noqa: SLF001
    qapp.processEvents()

    assert window.members_table_row_count() == 1

    # 移除成员
    window._on_remove_member(first_asset.id)  # noqa: SLF001

    # 素材池恢复
    assert window.pool_count() == 10
    assert window.members_table_row_count() == 0


def test_main_window_save_metadata_persists(
    qapp: QApplication, db_connection, db_path: Path
) -> None:
    """编辑元数据后保存，重新加载仍保留。"""
    mod_service = ModAssemblyService(
        ModItemRepository(db_connection), FileAssetRepository(db_connection)
    )
    mod_item = mod_service.create_mod_item(display_name="原名")
    db_connection.commit()

    window = _make_window(db_connection, db_path)
    # 选中 ModItem
    model = window._mod_list_model  # noqa: SLF001
    idx = model.index(0)
    window._mod_list_view.setCurrentIndex(idx)  # noqa: SLF001
    qapp.processEvents()

    # 编辑元数据
    window._name_edit.setText("新名称")  # noqa: SLF001
    window._desc_edit.setPlainText("测试说明")  # noqa: SLF001
    window._tags_edit.setText("护甲，魔法")  # noqa: SLF001
    window._on_save_metadata()  # noqa: SLF001

    # 重新从 DB 查询验证（commit_callback 已提交，无需手动 commit）
    repo = ModItemRepository(db_connection)
    loaded = repo.get_by_id(mod_item.id)
    assert loaded is not None
    assert loaded.display_name == "新名称"
    assert loaded.description == "测试说明"
    assert loaded.tags == {"护甲", "魔法"}


def test_main_window_associate_no_selection_protected(
    qapp: QApplication, db_connection, db_path: Path
) -> None:
    """无选中素材或 ModItem 时关联按钮禁用。"""
    window = _make_window(db_connection, db_path)
    assert window._associate_button.isEnabled() is False  # noqa: SLF001


def test_main_window_new_mod_button_disabled_without_pool_selection(
    qapp: QApplication, db_connection, db_path: Path, sample_mod_tree: Path
) -> None:
    """素材池无选择时「新建 Mod 条目」按钮禁用。"""
    from infrastructure.file_scanner import FileScanner, persist_scan_result
    from infrastructure.repositories.file_asset import FileAssetRepository

    service = ManagedRootService(
        ManagedRootRepository(db_connection),
        now_provider=lambda: "2026-07-07T00:00:00Z",
        uuid_provider=lambda: "uuid-newmod-btn",
    )
    service.add_root(sample_mod_tree)
    scanner = FileScanner()
    result = scanner.scan(sample_mod_tree)
    persist_scan_result(
        result,
        FolderNodeRepository(db_connection),
        FileAssetRepository(db_connection),
    )
    db_connection.commit()

    window = _make_window(db_connection, db_path)
    # 素材池有数据但未选择
    assert window.pool_count() == 10
    assert window._new_mod_button.isEnabled() is False  # noqa: SLF001

    # 选中一个素材后按钮启用
    pool_model = window._pool_model  # noqa: SLF001
    from PySide6.QtCore import QItemSelectionModel

    idx = pool_model.index(0)
    window._pool_view.selectionModel().select(  # noqa: SLF001
        idx, QItemSelectionModel.SelectionFlag.Select
    )
    qapp.processEvents()
    assert window._new_mod_button.isEnabled() is True  # noqa: SLF001


def test_main_window_new_mod_auto_associates_selected_assets(
    qapp: QApplication, db_connection, db_path: Path, sample_mod_tree: Path
) -> None:
    """「新建 Mod 条目」自动将选中素材关联到新条目。"""
    from infrastructure.file_scanner import FileScanner, persist_scan_result
    from infrastructure.repositories.file_asset import FileAssetRepository

    service = ManagedRootService(
        ManagedRootRepository(db_connection),
        now_provider=lambda: "2026-07-07T00:00:00Z",
        uuid_provider=lambda: "uuid-auto-assoc",
    )
    service.add_root(sample_mod_tree)
    scanner = FileScanner()
    result = scanner.scan(sample_mod_tree)
    persist_scan_result(
        result,
        FolderNodeRepository(db_connection),
        FileAssetRepository(db_connection),
    )
    db_connection.commit()

    window = _make_window(db_connection, db_path)
    assert window.pool_count() == 10

    # 选中素材池前 2 个素材
    pool_model = window._pool_model  # noqa: SLF001
    from PySide6.QtCore import QItemSelectionModel

    for i in range(2):
        idx = pool_model.index(i)
        window._pool_view.selectionModel().select(  # noqa: SLF001
            idx, QItemSelectionModel.SelectionFlag.Select
        )
    qapp.processEvents()

    # Mock QInputDialog 返回名称
    from unittest.mock import patch

    with patch("app.main_window.QInputDialog.getText", return_value=("自动关联测试", True)):
        window._on_new_mod()  # noqa: SLF001

    # 素材池减少 2 个
    assert window.pool_count() == 8
    # ModItem 列表有 1 个
    assert window.mod_list_count() == 1
    # 成员表有 2 个
    assert window.members_table_row_count() == 2


def test_main_window_pool_display_shows_full_path(
    qapp: QApplication, db_connection, db_path: Path, sample_mod_tree: Path
) -> None:
    """素材池显示文本包含文件名、类型和完整路径。"""
    from infrastructure.file_scanner import FileScanner, persist_scan_result
    from infrastructure.repositories.file_asset import FileAssetRepository

    service = ManagedRootService(
        ManagedRootRepository(db_connection),
        now_provider=lambda: "2026-07-07T00:00:00Z",
        uuid_provider=lambda: "uuid-path",
    )
    service.add_root(sample_mod_tree)
    scanner = FileScanner()
    result = scanner.scan(sample_mod_tree)
    persist_scan_result(
        result,
        FolderNodeRepository(db_connection),
        FileAssetRepository(db_connection),
    )
    db_connection.commit()

    window = _make_window(db_connection, db_path)
    pool_model = window._pool_model  # noqa: SLF001
    from PySide6.QtCore import Qt

    display = pool_model.data(pool_model.index(0), Qt.DisplayRole)
    # 显示文本应包含类型标记（文件或文件夹）
    assert "文件" in display
    # 显示文本应包含完整路径的一部分（sample_mod_tree 的路径）
    assert str(sample_mod_tree) in display or sample_mod_tree.name in display


def test_main_window_pool_shows_folders_after_scan(
    qapp: QApplication, db_connection, db_path: Path, sample_mod_tree: Path
) -> None:
    """素材池同时显示文件型和文件夹型 FileAsset（Task 3 缺口修复）。"""
    from infrastructure.file_scanner import FileScanner, persist_scan_result
    from infrastructure.repositories.file_asset import FileAssetRepository

    service = ManagedRootService(
        ManagedRootRepository(db_connection),
        now_provider=lambda: "2026-07-07T00:00:00Z",
        uuid_provider=lambda: "uuid-folders",
    )
    service.add_root(sample_mod_tree)
    scanner = FileScanner()
    result = scanner.scan(sample_mod_tree)
    persist_scan_result(
        result,
        FolderNodeRepository(db_connection),
        FileAssetRepository(db_connection),
    )
    db_connection.commit()

    window = _make_window(db_connection, db_path)
    # 7 文件 + 3 子文件夹 = 10
    assert window.pool_count() == 10

    # 验证素材池中同时存在文件和文件夹
    pool_model = window._pool_model  # noqa: SLF001
    from PySide6.QtCore import Qt

    has_file = False
    has_folder = False
    for i in range(pool_model.asset_count()):
        display = pool_model.data(pool_model.index(i), Qt.DisplayRole)
        if "文件夹" in display:
            has_folder = True
        if "文件" in display and "文件夹" not in display:
            has_file = True
    assert has_file, "素材池中未找到文件型素材"
    assert has_folder, "素材池中未找到文件夹型素材"


def test_main_window_role_change_persists_without_manual_commit(
    qapp: QApplication, db_connection, db_path: Path, sample_mod_tree: Path
) -> None:
    """成员角色修改后无需手动 commit 即持久化（Task 3 缺口修复）。"""
    from infrastructure.file_scanner import FileScanner, persist_scan_result
    from infrastructure.repositories.file_asset import FileAssetRepository

    service = ManagedRootService(
        ManagedRootRepository(db_connection),
        now_provider=lambda: "2026-07-07T00:00:00Z",
        uuid_provider=lambda: "uuid-role-persist",
    )
    service.add_root(sample_mod_tree)
    scanner = FileScanner()
    result = scanner.scan(sample_mod_tree)
    persist_scan_result(
        result,
        FolderNodeRepository(db_connection),
        FileAssetRepository(db_connection),
    )
    db_connection.commit()

    # 通过 service 创建 ModItem 并关联一个素材
    mod_service = ModAssemblyService(
        ModItemRepository(db_connection), FileAssetRepository(db_connection)
    )
    mod_item = mod_service.create_mod_item(display_name="角色持久化测试")
    unassociated = mod_service.list_unassociated_assets()
    first_asset = unassociated[0]
    from domain.models import FileRole

    mod_service.add_member(mod_item.id, first_asset.id, FileRole.UNKNOWN)
    db_connection.commit()

    window = _make_window(db_connection, db_path)
    # 选中 ModItem
    model = window._mod_list_model  # noqa: SLF001
    idx = model.index(0)
    window._mod_list_view.setCurrentIndex(idx)  # noqa: SLF001
    qapp.processEvents()

    assert window.members_table_row_count() == 1

    # 通过 UI 修改角色为 main_mod
    combo = window._members_table.cellWidget(0, 2)  # noqa: SLF001
    assert combo is not None

    role_index = combo.findData(FileRole.MAIN_MOD)
    assert role_index >= 0
    combo.setCurrentIndex(role_index)
    qapp.processEvents()

    # 不手动 commit —— commit_callback 应已提交

    # 直接从 repository 查询验证持久化
    repo = FileAssetRepository(db_connection)
    loaded = repo.get_by_id(first_asset.id)
    assert loaded is not None
    assert loaded.role == FileRole.MAIN_MOD
