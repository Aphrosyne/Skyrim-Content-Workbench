"""ModeManager 单元测试（roadmap 阶段 2 Task 5）。

覆盖：
- 初始模式为 browse
- 切换到 organize
- 切换回 browse
- 相同模式重复设置不 emit 信号
- mode_changed 信号正确发射
- is_browse / is_organize 辅助方法
"""

from __future__ import annotations

import pytest

from app.mode_manager import ModeManager
from domain.models import AppMode


@pytest.fixture
def manager(qapp) -> ModeManager:  # noqa: ANN001
    return ModeManager()


class TestModeManager:
    def test_initial_mode_is_browse(self, manager: ModeManager) -> None:
        assert manager.mode == AppMode.browse
        assert manager.is_browse() is True
        assert manager.is_organize() is False

    def test_switch_to_organize(self, manager: ModeManager) -> None:
        manager.set_mode(AppMode.organize)
        assert manager.mode == AppMode.organize
        assert manager.is_browse() is False
        assert manager.is_organize() is True

    def test_switch_back_to_browse(self, manager: ModeManager) -> None:
        manager.set_mode(AppMode.organize)
        manager.set_mode(AppMode.browse)
        assert manager.mode == AppMode.browse
        assert manager.is_browse() is True

    def test_same_mode_no_emit(self, manager: ModeManager) -> None:
        """相同模式重复设置不 emit 信号。"""
        emit_count = 0

        def on_changed(_mode: AppMode) -> None:
            nonlocal emit_count
            emit_count += 1

        manager.mode_changed.connect(on_changed)
        manager.set_mode(AppMode.browse)  # 与初始相同
        assert emit_count == 0

    def test_mode_changed_signal_emitted(self, manager: ModeManager) -> None:
        """切换模式时信号正确发射，参数为 AppMode。"""
        received: list[AppMode] = []
        manager.mode_changed.connect(lambda m: received.append(m))

        manager.set_mode(AppMode.organize)
        assert received == [AppMode.organize]

        manager.set_mode(AppMode.browse)
        assert received == [AppMode.organize, AppMode.browse]
