"""StripService（提取内容，操作便捷性1）测试。

覆盖：
- 正常剥离：子项移到上级 + 空文件夹进回收站 + strip/delete 历史
- 嵌套文件夹整体移动
- 内容单元（文件/子文件夹）路径随移动自动更新
- 冲突决策（重命名/跳过/覆盖）
- 前置校验：已标记文件夹拒绝 / 空文件夹拒绝
- 中文路径
- 部分失败（子项移动失败不中断，文件夹不清空则不删除）
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from application.content_service import ContentService
from application.errors import FileOperationError
from application.file_operation_service import FileOperationService
from application.strip_service import StripService
from infrastructure.db import get_connection, init_db
from infrastructure.repositories.content_unit import ContentUnitRepository
from infrastructure.repositories.operation_history import OperationHistoryRepository


@pytest.fixture
def strip_env(tmp_path: Path):
    """构造 StripService + ContentService + 已初始化 DB（真实 tmp_path 文件）。"""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row

    counter = {"n": 0}

    def fake_uuid() -> str:
        counter["n"] += 1
        return f"uuid-{counter['n']}"

    content_unit_repo = ContentUnitRepository(conn)
    file_op = FileOperationService(
        OperationHistoryRepository(conn),
        now_provider=lambda: "2026-08-04T00:00:00Z",
        uuid_provider=fake_uuid,
        content_unit_repo=content_unit_repo,
    )
    content_svc = ContentService(
        content_unit_repo,
        now_provider=lambda: "2026-08-04T00:00:00Z",
        uuid_provider=fake_uuid,
    )
    strip_svc = StripService(
        file_op,
        content_svc,
        OperationHistoryRepository(conn),
        now_provider=lambda: "2026-08-04T00:00:00Z",
        uuid_provider=fake_uuid,
    )

    yield strip_svc, content_svc, conn

    conn.close()


class TestStripBasic:
    def test_strip_moves_children_to_parent_and_removes_folder(
        self, strip_env, tmp_path: Path
    ) -> None:
        """正常剥离：子项到上级 + 空文件夹进回收站 + 历史记录。"""
        svc, _, conn = strip_env
        parent = tmp_path / "库"
        folder = parent / "包"
        folder.mkdir(parents=True)
        (folder / "a.txt").write_bytes(b"a")
        (folder / "b.7z").write_bytes(b"b")
        sub = folder / "子目录"
        sub.mkdir()
        (sub / "c.txt").write_bytes(b"c")

        plan = svc.prepare(folder)
        assert plan.child_count == 3
        # 冲突列表一项对应一个子项；父目录无同名条目 → 无实际冲突
        assert not any(c.default_dst.exists() for c in plan.conflicts)

        result = svc.strip(folder)

        assert result.moved_count == 3
        assert result.failure_count == 0
        assert result.folder_removed is True
        assert not folder.exists()
        assert (parent / "a.txt").read_bytes() == b"a"
        assert (parent / "b.7z").read_bytes() == b"b"
        assert (parent / "子目录" / "c.txt").read_bytes() == b"c"

        conn.commit()
        rows = conn.execute("SELECT * FROM operation_history").fetchall()
        types = [r["operation_type"] for r in rows]
        assert "strip" in types
        assert "delete" in types
        strip_rows = [r for r in rows if r["operation_type"] == "strip"]
        assert len(strip_rows) == 1
        assert strip_rows[0]["can_undo"] == 0
        assert strip_rows[0]["target_path"] == str(parent)

    def test_strip_chinese_path(self, strip_env, tmp_path: Path) -> None:
        """中文路径剥离。"""
        svc, _, _ = strip_env
        parent = tmp_path / "中文目录"
        folder = parent / "压缩包文件夹"
        folder.mkdir(parents=True)
        (folder / "汉化包.txt").write_text("内容", encoding="utf-8")

        result = svc.strip(folder)

        assert result.moved_count == 1
        assert result.folder_removed is True
        assert not folder.exists()
        assert (parent / "汉化包.txt").read_text(encoding="utf-8") == "内容"


class TestStripContentUnits:
    def test_file_unit_path_updated_after_strip(self, strip_env, tmp_path: Path) -> None:
        """文件夹内已标记文件：剥离后 ContentUnit.path 随移动更新。"""
        svc, content_svc, conn = strip_env
        parent = tmp_path / "Stash"
        folder = parent / "flat"
        folder.mkdir(parents=True)
        file = folder / "mod.7z"
        file.write_bytes(b"mod")
        unit = content_svc.mark_as_content_unit(file)

        result = svc.strip(folder)
        conn.commit()

        assert result.moved_count == 1
        assert result.folder_removed is True
        moved = content_svc.get_by_path(str(parent / "mod.7z"))
        assert moved is not None
        assert moved.id == unit.id

    def test_marked_subfolder_unit_path_updated_after_strip(
        self, strip_env, tmp_path: Path
    ) -> None:
        """文件夹内已标记子文件夹：剥离后路径前缀重写。"""
        svc, content_svc, conn = strip_env
        parent = tmp_path / "Stash"
        folder = parent / "flat"
        sub = folder / "mod组"
        sub.mkdir(parents=True)
        unit = content_svc.mark_as_content_unit(sub)

        result = svc.strip(folder)
        conn.commit()

        assert result.moved_count == 1
        assert result.folder_removed is True
        moved = content_svc.get_by_path(str(parent / "mod组"))
        assert moved is not None
        assert moved.id == unit.id
        assert (parent / "mod组").is_dir()


class TestStripConflicts:
    def test_conflict_rename_decision(self, strip_env, tmp_path: Path) -> None:
        """父目录已有同名条目：决策 rename 使用建议名。"""
        svc, _, _ = strip_env
        parent = tmp_path / "Stash"
        folder = parent / "flat"
        folder.mkdir(parents=True)
        (folder / "a.txt").write_bytes(b"new")
        (parent / "a.txt").write_bytes(b"old")
        (folder / "b.txt").write_bytes(b"b")

        plan = svc.prepare(folder)
        # 冲突列表一项对应一个子项；仅 a.txt 与父目录同名冲突
        assert len(plan.conflicts) == 2
        assert plan.conflicts[0].src.name == "a.txt"

        result = svc.strip(folder, decisions=["rename", "overwrite"])

        assert result.moved_count == 2
        assert result.folder_removed is True
        assert (parent / "a (1).txt").read_bytes() == b"new"
        assert (parent / "a.txt").read_bytes() == b"old"
        assert (parent / "b.txt").read_bytes() == b"b"

    def test_conflict_skip_decision(self, strip_env, tmp_path: Path) -> None:
        """决策 skip：同名条目跳过，其余继续。"""
        svc, _, _ = strip_env
        parent = tmp_path / "Stash"
        folder = parent / "flat"
        folder.mkdir(parents=True)
        (folder / "a.txt").write_bytes(b"new")
        (parent / "a.txt").write_bytes(b"old")
        (folder / "b.txt").write_bytes(b"b")

        result = svc.strip(folder, decisions=["skip", "overwrite"])

        assert result.moved_count == 1
        assert result.failure_count == 0
        assert (folder / "a.txt").exists()  # 跳过的条目留在原处
        assert (parent / "a.txt").read_bytes() == b"old"
        assert (parent / "b.txt").read_bytes() == b"b"
        assert folder.exists()  # 文件夹未清空 → 不删除
        assert result.folder_removed is False

    def test_conflict_overwrite_decision(self, strip_env, tmp_path: Path) -> None:
        """决策 overwrite：覆盖父目录同名条目。"""
        svc, _, _ = strip_env
        parent = tmp_path / "Stash"
        folder = parent / "flat"
        folder.mkdir(parents=True)
        (folder / "a.txt").write_bytes(b"new")
        (parent / "a.txt").write_bytes(b"old")

        result = svc.strip(folder, decisions=["overwrite"])

        assert result.moved_count == 1
        assert result.folder_removed is True
        assert (parent / "a.txt").read_bytes() == b"new"


class TestStripPreconditions:
    def test_marked_folder_rejected(self, strip_env, tmp_path: Path) -> None:
        """已标记为内容单元的文件夹拒绝剥离。"""
        svc, content_svc, _ = strip_env
        folder = tmp_path / "marked"
        folder.mkdir()
        (folder / "a.txt").write_bytes(b"a")
        content_svc.mark_as_content_unit(folder)

        with pytest.raises(FileOperationError, match="内容单元"):
            svc.prepare(folder)

    def test_empty_folder_rejected(self, strip_env, tmp_path: Path) -> None:
        """空文件夹拒绝剥离。"""
        svc, _, _ = strip_env
        folder = tmp_path / "empty"
        folder.mkdir()

        with pytest.raises(FileOperationError, match="为空"):
            svc.prepare(folder)

    def test_file_not_folder_rejected(self, strip_env, tmp_path: Path) -> None:
        """文件（非文件夹）拒绝剥离。"""
        svc, _, _ = strip_env
        file = tmp_path / "a.7z"
        file.write_bytes(b"x")

        with pytest.raises(FileOperationError, match="文件夹"):
            svc.prepare(file)

    def test_decision_count_mismatch(self, strip_env, tmp_path: Path) -> None:
        """决策数量与冲突数量不匹配时抛错。"""
        svc, _, _ = strip_env
        parent = tmp_path / "Stash"
        folder = parent / "flat"
        folder.mkdir(parents=True)
        (folder / "a.txt").write_bytes(b"a")
        (parent / "a.txt").write_bytes(b"old")

        with pytest.raises(FileOperationError, match="不匹配"):
            svc.strip(folder, decisions=[])


class TestStripPartialFailure:
    def test_partial_failure_keeps_folder_and_errors(
        self, strip_env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """某个子项移动失败：其余继续，文件夹未清空则不删除，错误汇总返回。"""
        svc, _, conn = strip_env
        folder = tmp_path / "flat"
        folder.mkdir()
        (folder / "ok.txt").write_bytes(b"ok")
        bad = folder / "bad.txt"
        bad.write_bytes(b"bad")

        original_move = svc._file_op.move  # noqa: SLF001

        def fake_move(src: Path, dst: Path, **kwargs):
            if src == bad:
                raise FileOperationError("模拟移动失败")
            return original_move(src, dst, **kwargs)

        monkeypatch.setattr(svc._file_op, "move", fake_move)

        result = svc.strip(folder)
        conn.commit()

        assert result.moved_count == 1
        assert result.failure_count == 1
        assert len(result.errors) == 1
        assert "模拟移动失败" in result.errors[0]
        assert (folder / "bad.txt").exists()
        assert folder.exists()
        assert result.folder_removed is False
