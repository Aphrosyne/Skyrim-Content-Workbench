"""最近使用标签记录（UI合理性8 / 操作便捷性4，2026-08-02）。

记录最近 N 个被成功添加的标签（按 tag_id，去重置顶），QSettings 持久化。
供 MetadataPanel「最近使用」区域与右键「添加最近标签 ▸」子菜单使用。

存储 tag_id 而非 name（标签唯一约束为 (name, category_id)，name 可跨分类重名）。
显示时由调用方通过 TagService 映射 id → name；标签被删除时跳过（不报错）。
"""

from __future__ import annotations

from PySide6.QtCore import QSettings


class RecentTags:
    """最近使用标签列表（QSettings 持久化）。"""

    DEFAULT_MAX_TAGS = 10
    _SETTINGS_KEY = "recent_tags"

    def __init__(self, settings: QSettings, max_tags: int = DEFAULT_MAX_TAGS) -> None:
        """初始化最近标签记录。

        Args:
            settings: QSettings 实例（由 MainWindow 注入）。
            max_tags: 保留的最大条目数。
        """
        self._settings = settings
        self._max_tags = max(1, max_tags)

    def record(self, tag_id: str) -> None:
        """记录一次成功添加的标签（去重置顶，超限丢弃最旧）。"""
        if not tag_id:
            return
        kept = [t for t in self._read() if t != tag_id]
        kept.insert(0, tag_id)
        self._write(kept[: self._max_tags])

    def list_recent(self) -> list[str]:
        """按最近使用顺序返回 tag_id 列表（新→旧）。"""
        return self._read()

    # --- 内部：QSettings 读写 ---

    def _read(self) -> list[str]:
        value = self._settings.value(self._SETTINGS_KEY, [])
        if not value:
            return []
        if isinstance(value, str):
            return [value]
        return [str(v) for v in value]

    def _write(self, tag_ids: list[str]) -> None:
        self._settings.setValue(self._SETTINGS_KEY, tag_ids)
        self._settings.sync()
