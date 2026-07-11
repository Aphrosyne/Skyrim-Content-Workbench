"""素材池与 ModItem 列表 model 测试。

覆盖：
- 未归类素材只显示 mod_item_id 为 null 的素材；
- 成功关联后从素材池消失；
- 解除关联后重新出现；
- ModItem 列表正确刷新；
- 中文文件名/目录名展示；
- 文件夹型与文件型素材都支持。
"""

from __future__ import annotations

import sqlite3
import uuid

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.pool_model import ModItemListModel, UnassociatedPoolModel  # noqa: E402
from application.mod_assembly_service import ModAssemblyService  # noqa: E402
from domain.models import AssetKind, FileAsset, FileRole  # noqa: E402
from infrastructure.repositories.file_asset import FileAssetRepository  # noqa: E402
from infrastructure.repositories.mod_item import ModItemRepository  # noqa: E402


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    yield app


def _insert_asset(
    repo: FileAssetRepository,
    real_path: str = "D:/Mods/test.7z",
    filename: str = "test.7z",
    extension: str = ".7z",
    asset_kind: AssetKind = AssetKind.FILE,
    mod_item_id: str | None = None,
    role: FileRole = FileRole.UNKNOWN,
) -> FileAsset:
    asset = FileAsset(
        id=str(uuid.uuid4()),
        mod_item_id=mod_item_id,
        real_path=real_path,
        path_key=real_path.lower(),
        filename=filename,
        extension=extension,
        asset_kind=asset_kind,
        role=role,
        size_bytes=100,
        modified_at="2026-07-07T00:00:00Z",
        imported_at="2026-07-07T00:00:00Z",
    )
    return repo.create(asset)


def _make_service(db_connection: sqlite3.Connection) -> ModAssemblyService:
    return ModAssemblyService(ModItemRepository(db_connection), FileAssetRepository(db_connection))


def test_pool_model_empty(db_connection: sqlite3.Connection, qapp: QApplication) -> None:
    """无数据时素材池 model 为空。"""
    service = _make_service(db_connection)
    model = UnassociatedPoolModel(service)
    model.refresh()
    assert model.asset_count() == 0
    assert model.rowCount() == 0


def test_pool_model_shows_only_unassociated(
    db_connection: sqlite3.Connection, qapp: QApplication
) -> None:
    """素材池只显示 mod_item_id 为 None 的素材。"""
    repo = FileAssetRepository(db_connection)
    service = _make_service(db_connection)

    # 创建一个 ModItem
    mod = service.create_mod_item(display_name="测试")

    # 3 个未关联 + 2 个已关联
    _insert_asset(repo, real_path="D:/A.7z", filename="A.7z")
    _insert_asset(repo, real_path="D:/B.zip", filename="B.zip")
    _insert_asset(repo, real_path="D:/C.webp", filename="C.webp")
    _insert_asset(
        repo, real_path="D:/D.7z", filename="D.7z", mod_item_id=mod.id, role=FileRole.MAIN_MOD
    )
    _insert_asset(
        repo, real_path="D:/E.txt", filename="E.txt", mod_item_id=mod.id, role=FileRole.README
    )
    db_connection.commit()

    model = UnassociatedPoolModel(service)
    model.refresh()
    assert model.asset_count() == 3

    # 验证显示名包含文件名
    idx = model.index(0)
    display = model.data(idx, Qt.DisplayRole)
    assert "A.7z" in display or "B.zip" in display or "C.webp" in display


def test_pool_model_disappears_after_associate(
    db_connection: sqlite3.Connection, qapp: QApplication
) -> None:
    """关联后素材从池中消失。"""
    repo = FileAssetRepository(db_connection)
    service = _make_service(db_connection)

    mod = service.create_mod_item(display_name="测试")
    asset = _insert_asset(repo, real_path="D:/本体.7z", filename="本体.7z")
    db_connection.commit()

    model = UnassociatedPoolModel(service)
    model.refresh()
    assert model.asset_count() == 1

    # 关联
    service.add_member(mod.id, asset.id, FileRole.MAIN_MOD)
    db_connection.commit()

    model.refresh()
    assert model.asset_count() == 0


def test_pool_model_reappears_after_remove(
    db_connection: sqlite3.Connection, qapp: QApplication
) -> None:
    """解除关联后素材重新出现。"""
    repo = FileAssetRepository(db_connection)
    service = _make_service(db_connection)

    mod = service.create_mod_item(display_name="测试")
    asset = _insert_asset(repo, real_path="D:/汉化.zip", filename="汉化.zip")
    service.add_member(mod.id, asset.id, FileRole.TRANSLATION)
    db_connection.commit()

    model = UnassociatedPoolModel(service)
    model.refresh()
    assert model.asset_count() == 0

    # 解除关联
    service.remove_member(mod.id, asset.id)
    db_connection.commit()

    model.refresh()
    assert model.asset_count() == 1


def test_pool_model_chinese_filename(db_connection: sqlite3.Connection, qapp: QApplication) -> None:
    """中文文件名正确展示。"""
    repo = FileAssetRepository(db_connection)
    service = _make_service(db_connection)

    _insert_asset(repo, real_path="D:/Mods/寒霜之心.7z", filename="寒霜之心.7z")
    _insert_asset(repo, real_path="D:/Mods/预览.webp", filename="预览.webp")
    db_connection.commit()

    model = UnassociatedPoolModel(service)
    model.refresh()
    assert model.asset_count() == 2

    names = [model.data(model.index(i), Qt.DisplayRole) for i in range(2)]
    flat = " ".join(names)
    assert "寒霜之心" in flat
    assert "预览" in flat


def test_pool_model_folder_kind(db_connection: sqlite3.Connection, qapp: QApplication) -> None:
    """文件夹型素材正确展示。"""
    repo = FileAssetRepository(db_connection)
    service = _make_service(db_connection)

    _insert_asset(
        repo,
        real_path="D:/Mods/护甲包",
        filename="护甲包",
        extension="",
        asset_kind=AssetKind.FOLDER,
    )
    db_connection.commit()

    model = UnassociatedPoolModel(service)
    model.refresh()
    assert model.asset_count() == 1

    display = model.data(model.index(0), Qt.DisplayRole)
    assert "护甲包" in display
    # 文件夹标记
    assert "📁" in display

    # tooltip 应包含"文件夹"
    tooltip = model.data(model.index(0), Qt.ToolTipRole)
    assert "文件夹" in tooltip


def test_pool_model_file_kind_tooltip(
    db_connection: sqlite3.Connection, qapp: QApplication
) -> None:
    """文件型素材 tooltip 包含"文件"。"""
    repo = FileAssetRepository(db_connection)
    service = _make_service(db_connection)

    _insert_asset(repo, real_path="D:/test.7z", filename="test.7z")
    db_connection.commit()

    model = UnassociatedPoolModel(service)
    model.refresh()
    tooltip = model.data(model.index(0), Qt.ToolTipRole)
    assert "文件" in tooltip


def test_mod_item_list_model_empty(db_connection: sqlite3.Connection, qapp: QApplication) -> None:
    """无 ModItem 时列表为空。"""
    service = _make_service(db_connection)
    model = ModItemListModel(service)
    model.refresh()
    assert model.item_count() == 0


def test_mod_item_list_model_shows_items(
    db_connection: sqlite3.Connection, qapp: QApplication
) -> None:
    """列表正确显示 ModItem。"""
    service = _make_service(db_connection)
    service.create_mod_item(display_name="条目一")
    service.create_mod_item(display_name="条目二")
    db_connection.commit()

    model = ModItemListModel(service)
    model.refresh()
    assert model.item_count() == 2

    # 显示名
    name0 = model.data(model.index(0), Qt.DisplayRole)
    name1 = model.data(model.index(1), Qt.DisplayRole)
    assert "条目" in name0
    assert "条目" in name1


def test_mod_item_list_model_unnamed_display(
    db_connection: sqlite3.Connection, qapp: QApplication
) -> None:
    """display_name 为 None 时显示"（未命名）"。"""
    service = _make_service(db_connection)
    service.create_mod_item(display_name=None)
    db_connection.commit()

    model = ModItemListModel(service)
    model.refresh()
    assert model.item_count() == 1
    display = model.data(model.index(0), Qt.DisplayRole)
    assert "未命名" in display


def test_mod_item_list_model_refresh_after_create(
    db_connection: sqlite3.Connection, qapp: QApplication
) -> None:
    """创建后 refresh 能反映新增条目。"""
    service = _make_service(db_connection)
    model = ModItemListModel(service)
    model.refresh()
    assert model.item_count() == 0

    service.create_mod_item(display_name="新增")
    db_connection.commit()

    model.refresh()
    assert model.item_count() == 1


def test_mod_item_list_model_chinese_tags_tooltip(
    db_connection: sqlite3.Connection, qapp: QApplication
) -> None:
    """中文描述作为 tooltip 展示。"""
    service = _make_service(db_connection)
    service.create_mod_item(display_name="中文条目", description="这是一个测试说明")
    db_connection.commit()

    model = ModItemListModel(service)
    model.refresh()
    tooltip = model.data(model.index(0), Qt.ToolTipRole)
    assert "测试说明" in tooltip
