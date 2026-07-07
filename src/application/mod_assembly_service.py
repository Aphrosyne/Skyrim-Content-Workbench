"""Mod 条目组装服务。

依据 docs/roadmap.md Task 4。
依据 docs/architecture.md §3：application 层协调 UI 与领域逻辑。
依据 docs/spec.md §6：ModItem 与 FileAsset 数据模型。

约束：
- 不访问文件系统；仅通过 Repository 读写 SQLite。
- 不自动根据文件名推断或合并成员（AGENTS 规则 7）。
- 不实现 ModItem.status（Q1）、FileAsset.batch_id（Q2）。
- 不实现候选成员关系生成（Q10）。
- 成员角色数量限制：MAIN_MOD≤1、README≤1；其他角色不限制（Q19）。
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from application.errors import (
    DuplicateMemberError,
    FileAssetNotFoundError,
    MemberLimitError,
    ModItemNotFoundError,
)
from domain.models import FileAsset, FileRole, ModItem
from infrastructure.repositories.file_asset import FileAssetRepository
from infrastructure.repositories.mod_item import ModItemRepository

logger = logging.getLogger(__name__)


def _default_now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _default_uuid_provider() -> str:
    return str(uuid.uuid4())


# 阶段 1 最小约束：每种角色的数量上限。
# None 表示不限制；整数表示最多 N 个。
# 依据 spec §6.2：MAIN_MOD 与 README 隐含唯一。
# 见 docs/open-questions.md Q19。
ROLE_LIMITS: dict[FileRole, int | None] = {
    FileRole.MAIN_MOD: 1,
    FileRole.TRANSLATION: None,
    FileRole.PREVIEW: None,
    FileRole.README: 1,
    FileRole.OPTIONAL_FILE: None,
    FileRole.UNKNOWN: None,
}


class ModAssemblyService:
    """Mod 条目组装服务。

    使用方式：
        service = ModAssemblyService(mod_repo, file_repo)
        mod = service.create_mod_item(display_name="寒霜之心")
        service.add_member(mod.id, file_asset_id, FileRole.MAIN_MOD)
        service.add_member(mod.id, another_asset_id, FileRole.TRANSLATION)
    """

    def __init__(
        self,
        mod_item_repo: ModItemRepository,
        file_asset_repo: FileAssetRepository,
        now_provider: Callable[[], str] | None = None,
        uuid_provider: Callable[[], str] | None = None,
    ) -> None:
        self._mod_repo = mod_item_repo
        self._file_repo = file_asset_repo
        self._now = now_provider or _default_now_utc
        self._new_uuid = uuid_provider or _default_uuid_provider

    # --- 创建 ModItem ---

    def create_mod_item(
        self,
        display_name: str | None = None,
        description: str | None = None,
        source_url: str | None = None,
        category_folder_id: str | None = None,
        tags: set[str] | None = None,
    ) -> ModItem:
        """创建一个空的 ModItem（无成员）。

        不自动关联任何 FileAsset；成员通过 add_member 添加。
        """
        now = self._now()
        item = ModItem(
            id=self._new_uuid(),
            created_at=now,
            updated_at=now,
            display_name=display_name,
            description=description,
            source_url=source_url,
            category_folder_id=category_folder_id,
            tags=tags if tags is not None else set(),
            cover_asset_id=None,
        )
        return self._mod_repo.create(item)

    # --- 成员关联 ---

    def add_member(
        self,
        mod_item_id: str,
        file_asset_id: str,
        role: FileRole,
    ) -> FileAsset:
        """将一个 FileAsset 关联到 ModItem，设置角色。

        规则：
        - mod_item_id 必须存在
        - file_asset_id 必须存在
        - 同一 FileAsset 不能重复关联到同一 ModItem
        - role 数量限制见 ROLE_LIMITS

        不自动推断角色；role 由调用方显式指定。
        """
        # 验证 ModItem 存在
        if self._mod_repo.get_by_id(mod_item_id) is None:
            raise ModItemNotFoundError(f"ModItem 不存在：{mod_item_id}")

        # 验证 FileAsset 存在
        asset = self._file_repo.get_by_id(file_asset_id)
        if asset is None:
            raise FileAssetNotFoundError(f"FileAsset 不存在：{file_asset_id}")

        # 检查重复关联
        if asset.mod_item_id == mod_item_id:
            raise DuplicateMemberError(f"FileAsset 已关联到该 ModItem：{file_asset_id}")

        # 检查角色数量限制
        self._check_role_limit(mod_item_id, role)

        # 设置关联
        asset.mod_item_id = mod_item_id
        asset.role = role
        return self._file_repo.update(asset)

    def set_member_role(
        self,
        mod_item_id: str,
        file_asset_id: str,
        role: FileRole,
    ) -> FileAsset:
        """更新已关联成员的角色。"""
        asset = self._get_member_or_raise(mod_item_id, file_asset_id)

        # 若角色未变，直接返回
        if asset.role == role:
            return asset

        # 检查新角色的数量限制（排除自身）
        self._check_role_limit(mod_item_id, role, exclude_asset_id=file_asset_id)

        asset.role = role
        return self._file_repo.update(asset)

    # --- 封面 ---

    def set_cover(self, mod_item_id: str, file_asset_id: str) -> ModItem:
        """设置 ModItem 的封面预览图。

        要求 file_asset_id 已关联到该 ModItem 且 role=PREVIEW。
        """
        asset = self._get_member_or_raise(mod_item_id, file_asset_id)
        if asset.role != FileRole.PREVIEW:
            raise ValueError(f"封面必须是 PREVIEW 角色，当前为 {asset.role.value}：{file_asset_id}")

        item = self._mod_repo.get_by_id(mod_item_id)
        if item is None:
            raise ModItemNotFoundError(f"ModItem 不存在：{mod_item_id}")

        item.cover_asset_id = file_asset_id
        item.updated_at = self._now()
        return self._mod_repo.update(item)

    # --- 查询 ---

    def get_mod_item(self, mod_item_id: str) -> ModItem:
        """查询 ModItem；不存在抛 ModItemNotFoundError。"""
        item = self._mod_repo.get_by_id(mod_item_id)
        if item is None:
            raise ModItemNotFoundError(f"ModItem 不存在：{mod_item_id}")
        return item

    def get_members(self, mod_item_id: str) -> list[FileAsset]:
        """返回 ModItem 的全部成员（按 imported_at 排序）。"""
        if self._mod_repo.get_by_id(mod_item_id) is None:
            raise ModItemNotFoundError(f"ModItem 不存在：{mod_item_id}")
        return self._file_repo.list_by_mod_item(mod_item_id)

    def get_mod_item_with_members(self, mod_item_id: str) -> tuple[ModItem, list[FileAsset]]:
        """返回 ModItem 及其成员列表。"""
        return self.get_mod_item(mod_item_id), self.get_members(mod_item_id)

    def list_mod_items(self) -> list[ModItem]:
        """返回全部 ModItem。"""
        return self._mod_repo.list_all()

    # --- 编辑 ---

    def update_mod_item(self, mod_item_id: str, **fields: object) -> ModItem:
        """更新 ModItem 的可编辑字段。

        可更新字段：display_name, description, source_url,
        category_folder_id, tags。
        """
        item = self.get_mod_item(mod_item_id)

        if "display_name" in fields:
            item.display_name = fields["display_name"]  # type: ignore[assignment]
        if "description" in fields:
            item.description = fields["description"]  # type: ignore[assignment]
        if "source_url" in fields:
            item.source_url = fields["source_url"]  # type: ignore[assignment]
        if "category_folder_id" in fields:
            item.category_folder_id = fields["category_folder_id"]  # type: ignore[assignment]
        if "tags" in fields:
            tags = fields["tags"]
            if not isinstance(tags, set):
                raise TypeError("tags 必须是 set[str]")
            item.tags = tags  # type: ignore[assignment]

        item.updated_at = self._now()
        return self._mod_repo.update(item)

    def remove_member(self, mod_item_id: str, file_asset_id: str) -> FileAsset:
        """解除成员关联（将 mod_item_id 置 None，role 置 UNKNOWN）。

        不删除 FileAsset 记录（spec §7.13 不提供删除）。
        若被移除的是 cover_asset_id，同时清除 cover。
        """
        asset = self._get_member_or_raise(mod_item_id, file_asset_id)

        # 若被移除的是 cover，清除 ModItem.cover_asset_id
        item = self._mod_repo.get_by_id(mod_item_id)
        if item is not None and item.cover_asset_id == file_asset_id:
            item.cover_asset_id = None
            item.updated_at = self._now()
            self._mod_repo.update(item)

        asset.mod_item_id = None
        asset.role = FileRole.UNKNOWN
        return self._file_repo.update(asset)

    # --- 内部辅助 ---

    def _check_role_limit(
        self,
        mod_item_id: str,
        role: FileRole,
        exclude_asset_id: str | None = None,
    ) -> None:
        """检查角色数量限制。exclude_asset_id 用于 set_member_role（排除自身）。"""
        limit = ROLE_LIMITS.get(role)
        if limit is None:
            return

        members = self._file_repo.list_by_mod_item(mod_item_id)
        count = sum(1 for m in members if m.role == role and m.id != exclude_asset_id)
        if count >= limit:
            raise MemberLimitError(f"角色 {role.value} 已达数量上限 {limit}，无法添加更多")

    def _get_member_or_raise(self, mod_item_id: str, file_asset_id: str) -> FileAsset:
        """获取已关联到指定 ModItem 的成员；不存在或未关联则抛错。"""
        asset = self._file_repo.get_by_id(file_asset_id)
        if asset is None:
            raise FileAssetNotFoundError(f"FileAsset 不存在：{file_asset_id}")
        if asset.mod_item_id != mod_item_id:
            raise FileAssetNotFoundError(f"FileAsset 未关联到该 ModItem：{file_asset_id}")
        return asset
