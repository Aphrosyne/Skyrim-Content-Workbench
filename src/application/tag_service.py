"""标签系统服务。

依据 docs/spec.md §10、docs/roadmap.md 阶段 4 Task 1。

职责：
- TagCategory CRUD（创建、查询、更新、删除）。
- Tag CRUD + 跨分类移动 + 删除（级联清理 content_unit_tag）。
- JSON 导入 / 导出（schema_version=1，扁平结构）。
- 预置标签库加载（default_tags.json，仅当 tag_category 表为空时）。

约束：
- 不访问文件系统；JSON 文件读写通过传入 Path 参数，由调用方（main.py / UI）负责。
- 写操作不自提交，由 application 层调用方控制事务边界（与现有 Service 一致）。
- 异常分层：repo 层 RepositoryError / ConstraintViolationError → service 层
  ApplicationError 子类（DuplicateTagCategoryNameError / TagCategoryNotFoundError 等）。

JSON 格式（schema_version=2；导入兼容旧 schema_version=1 的 color_hue 字段）：
```json
{
  "schema_version": 2,
  "categories": [
    {
      "name": "服装护甲",
      "color_hex": "#1A78D6",
      "tags": ["重甲", "轻甲", ...]
    },
    ...
  ]
}
```

导入策略（用户确认 E1）：合并跳过——同名分类整体跳过，不创建该分类；
不同名分类正常创建。导入失败全部回滚（事务原子性，E4）。
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from application.errors import (
    ContentUnitNotFoundError,
    DuplicateTagCategoryNameError,
    DuplicateTagNameError,
    InvalidTagJsonError,
    TagCategoryNotFoundError,
    TagNotFoundError,
)
from domain.models import Tag, TagCategory
from infrastructure.color_utils import hue_to_hex
from infrastructure.repositories.content_unit_tag import ContentUnitTagRepository
from infrastructure.repositories.errors import (
    ConstraintViolationError,
    NotFoundError,
    RepositoryError,
)
from infrastructure.repositories.tag import TagRepository
from infrastructure.repositories.tag_category import TagCategoryRepository

logger = logging.getLogger(__name__)

# JSON schema 版本号（v2：color_hue → color_hex；导入兼容 v1）
TAGS_JSON_SCHEMA_VERSION = 2


def _default_now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _default_uuid_provider() -> str:
    return str(uuid.uuid4())


class TagService:
    """标签分类与标签的 CRUD + JSON 导入导出 + 预置库加载。

    使用方式：
        service = TagService(category_repo, tag_repo, cut_repo)
        category = service.create_category("服装护甲", color_hex="#1A78D6")
        tag = service.create_tag("重甲", category.id)
        service.load_default_tags_if_empty(Path("default_tags.json"))
        service.export_to_json(Path("my_tags.json"))
    """

    def __init__(
        self,
        category_repo: TagCategoryRepository,
        tag_repo: TagRepository,
        content_unit_tag_repo: ContentUnitTagRepository,
        now_provider: Callable[[], str] | None = None,
        uuid_provider: Callable[[], str] | None = None,
    ) -> None:
        self._category_repo = category_repo
        self._tag_repo = tag_repo
        self._cut_repo = content_unit_tag_repo
        self._now = now_provider or _default_now_utc
        self._new_uuid = uuid_provider or _default_uuid_provider

    # --- TagCategory CRUD ---

    def create_category(self, name: str, color_hex: str = "#D61A1A") -> TagCategory:
        """创建标签分类。同名抛 DuplicateTagCategoryNameError。"""
        name = name.strip()
        if not name:
            raise InvalidTagJsonError("标签分类名称不能为空")
        if self._category_repo.get_by_name(name) is not None:
            raise DuplicateTagCategoryNameError(f"该分类已存在：{name}")
        category = TagCategory(
            id=self._new_uuid(),
            name=name,
            color_hex=color_hex,
        )
        try:
            return self._category_repo.create(category)
        except ConstraintViolationError as e:
            # TOCTOU 竞态：去重检查与 create 之间另一线程插入了相同 name
            raise DuplicateTagCategoryNameError(f"该分类已存在：{name}") from e
        except RepositoryError as e:
            raise InvalidTagJsonError(f"无法创建分类：{e}") from e

    def get_category(self, category_id: str) -> TagCategory:
        """查询指定分类；不存在抛 TagCategoryNotFoundError。"""
        category = self._category_repo.get_by_id(category_id)
        if category is None:
            raise TagCategoryNotFoundError(f"标签分类不存在：{category_id}")
        return category

    def list_categories(self) -> list[TagCategory]:
        """返回全部标签分类，按 name 排序。"""
        return self._category_repo.list_all()

    def rename_category(self, category_id: str, new_name: str) -> TagCategory:
        """重命名分类。重名抛 DuplicateTagCategoryNameError；不存在抛 TagCategoryNotFoundError。"""
        new_name = new_name.strip()
        if not new_name:
            raise InvalidTagJsonError("标签分类名称不能为空")
        category = self.get_category(category_id)
        if category.name == new_name:
            return category
        if self._category_repo.get_by_name(new_name) is not None:
            raise DuplicateTagCategoryNameError(f"该分类已存在：{new_name}")
        category.name = new_name
        try:
            return self._category_repo.update(category)
        except ConstraintViolationError as e:
            raise DuplicateTagCategoryNameError(f"该分类已存在：{new_name}") from e
        except RepositoryError as e:
            raise InvalidTagJsonError(f"无法重命名分类：{e}") from e

    def update_category_color(self, category_id: str, color_hex: str) -> TagCategory:
        """更新分类的完整颜色。不存在抛 TagCategoryNotFoundError。"""
        category = self.get_category(category_id)
        category.color_hex = color_hex
        try:
            return self._category_repo.update(category)
        except RepositoryError as e:
            raise InvalidTagJsonError(f"无法更新分类颜色：{e}") from e

    def delete_category(self, category_id: str) -> None:
        """删除分类及其下所有标签和内容单元关联。

        级联顺序：
        1. 通过 content_unit_tag_repo.detach_all_by_category 删除该分类下所有标签的关联。
        2. 通过 tag_repo.list_by_category + delete 删除该分类下所有标签。
        3. 通过 category_repo.delete 删除分类本身。

        任一数据库操作失败抛 RepositoryError。
        """
        # 先校验存在性（不存在抛 TagCategoryNotFoundError）
        self.get_category(category_id)
        try:
            # 1. 清理 content_unit_tag 关联
            self._cut_repo.detach_all_by_category(category_id)
            # 2. 删除该分类下所有标签
            for tag in self._tag_repo.list_by_category(category_id):
                self._tag_repo.delete(tag.id)
            # 3. 删除分类
            self._category_repo.delete(category_id)
        except NotFoundError as e:
            raise TagCategoryNotFoundError(f"标签分类不存在：{category_id}") from e
        except RepositoryError as e:
            raise InvalidTagJsonError(f"无法删除分类：{e}") from e

    # --- Tag CRUD ---

    def create_tag(self, name: str, category_id: str) -> Tag:
        """创建标签。

        - 同分类下同名抛 DuplicateTagNameError；
        - 分类不存在抛 TagCategoryNotFoundError。
        """
        name = name.strip()
        if not name:
            raise InvalidTagJsonError("标签名称不能为空")
        # 校验分类存在
        self.get_category(category_id)
        # 同分类重名检查
        if self._tag_repo.get_by_name_in_category(name, category_id) is not None:
            raise DuplicateTagNameError(f"该分类下已存在标签：{name}")
        tag = Tag(
            id=self._new_uuid(),
            name=name,
            category_id=category_id,
        )
        try:
            return self._tag_repo.create(tag)
        except ConstraintViolationError as e:
            raise DuplicateTagNameError(f"该分类下已存在标签：{name}") from e
        except RepositoryError as e:
            raise InvalidTagJsonError(f"无法创建标签：{e}") from e

    def get_tag(self, tag_id: str) -> Tag:
        """查询指定标签；不存在抛 TagNotFoundError。"""
        tag = self._tag_repo.get_by_id(tag_id)
        if tag is None:
            raise TagNotFoundError(f"标签不存在：{tag_id}")
        return tag

    def list_tags_by_category(self, category_id: str) -> list[Tag]:
        """返回指定分类下的全部标签，按 name 排序。"""
        return self._tag_repo.list_by_category(category_id)

    def list_all_tags(self) -> list[Tag]:
        """返回全部标签，按 name 排序。"""
        return self._tag_repo.list_all()

    def rename_tag(self, tag_id: str, new_name: str) -> Tag:
        """重命名标签。同分类下重名抛 DuplicateTagNameError；不存在抛 TagNotFoundError。"""
        new_name = new_name.strip()
        if not new_name:
            raise InvalidTagJsonError("标签名称不能为空")
        tag = self.get_tag(tag_id)
        if tag.name == new_name:
            return tag
        if self._tag_repo.get_by_name_in_category(new_name, tag.category_id) is not None:
            raise DuplicateTagNameError(f"该分类下已存在标签：{new_name}")
        tag.name = new_name
        try:
            return self._tag_repo.update(tag)
        except ConstraintViolationError as e:
            raise DuplicateTagNameError(f"该分类下已存在标签：{new_name}") from e
        except RepositoryError as e:
            raise InvalidTagJsonError(f"无法重命名标签：{e}") from e

    def move_tag_to_category(self, tag_id: str, target_category_id: str) -> Tag:
        """移动标签到其他分类。若目标分类下同名标签已存在抛 DuplicateTagNameError。"""
        tag = self.get_tag(tag_id)
        if tag.category_id == target_category_id:
            return tag
        # 校验目标分类存在
        self.get_category(target_category_id)
        # 检查目标分类下是否已有同名
        if self._tag_repo.get_by_name_in_category(tag.name, target_category_id) is not None:
            raise DuplicateTagNameError(f"目标分类下已存在同名标签：{tag.name}")
        tag.category_id = target_category_id
        try:
            return self._tag_repo.update(tag)
        except ConstraintViolationError as e:
            raise DuplicateTagNameError(f"目标分类下已存在同名标签：{tag.name}") from e
        except RepositoryError as e:
            raise InvalidTagJsonError(f"无法移动标签到其他分类：{e}") from e

    def delete_tag(self, tag_id: str) -> None:
        """删除标签，级联清理 content_unit_tag 中的关联。

        级联顺序：
        1. 通过 content_unit_tag_repo.detach_all_by_tag 删除该标签的所有关联。
        2. 通过 tag_repo.delete 删除标签本身。
        """
        # 先校验存在性
        self.get_tag(tag_id)
        try:
            self._cut_repo.detach_all_by_tag(tag_id)
            self._tag_repo.delete(tag_id)
        except NotFoundError as e:
            raise TagNotFoundError(f"标签不存在：{tag_id}") from e
        except RepositoryError as e:
            raise InvalidTagJsonError(f"无法删除标签：{e}") from e

    # --- 查询：分类 + 其下标签（用于 UI 一次性加载） ---

    def list_categories_with_tags(
        self,
    ) -> list[tuple[TagCategory, list[Tag]]]:
        """返回所有分类及其下标签（按分类 name 排序，分类内标签按 name 排序）。

        供 UI 标签管理对话框 / 筛选栏一次性加载。
        """
        categories = self._category_repo.list_all()
        result: list[tuple[TagCategory, list[Tag]]] = []
        for cat in categories:
            tags = self._tag_repo.list_by_category(cat.id)
            result.append((cat, tags))
        return result

    # --- 内容单元 ↔ 标签关联（Stage 4 Task 2） ---

    def attach_tag_to_unit(self, content_unit_id: str, tag_id: str) -> bool:
        """为内容单元添加标签。

        使用 INSERT OR IGNORE 幂等：重复 attach 同一对不会抛错。
        返回 True 表示新增关联，False 表示已存在。

        Raises:
            TagNotFoundError: tag_id 不存在。
            ContentUnitNotFoundError: content_unit_id 不存在（FK 违约）。
        """
        # 校验标签存在（同时给出清晰错误，而不是依赖 FK 违约）
        if self._tag_repo.get_by_id(tag_id) is None:
            raise TagNotFoundError(f"标签不存在：{tag_id}")
        try:
            return self._cut_repo.attach(content_unit_id, tag_id)
        except RepositoryError as e:
            # FK 违约通常表示 content_unit_id 不存在
            raise ContentUnitNotFoundError(f"内容单元不存在：{content_unit_id}") from e

    def detach_tag_from_unit(self, content_unit_id: str, tag_id: str) -> bool:
        """移除内容单元的标签关联。

        幂等：返回 True 表示实际移除一行，False 表示原本就无关联。
        """
        return self._cut_repo.detach(content_unit_id, tag_id)

    def list_tags_of_content_unit(
        self, content_unit_id: str
    ) -> list[tuple[TagCategory, list[Tag]]]:
        """返回指定内容单元的标签，按分类分组。

        每个元组为 (TagCategory, list[Tag])，分类按 name 排序，分类内标签按 name 排序。
        无标签时返回空列表。

        Raises:
            RepositoryError: 数据库查询失败。
        """
        rows = self._cut_repo.list_tag_rows_by_content_unit(content_unit_id)
        if not rows:
            return []

        # 收集所有相关分类（按首次出现顺序去重）
        category_map: dict[str, TagCategory] = {}
        for row in rows:
            cid = row["category_id"]
            if cid not in category_map:
                cat = self._category_repo.get_by_id(cid)
                if cat is not None:
                    category_map[cid] = cat

        # 按 category name 排序分类
        sorted_categories = sorted(category_map.values(), key=lambda c: c.name)

        # 按 category_id 分组标签
        result: list[tuple[TagCategory, list[Tag]]] = []
        for cat in sorted_categories:
            tags = [
                Tag(
                    id=row["id"],
                    name=row["name"],
                    category_id=row["category_id"],
                )
                for row in rows
                if row["category_id"] == cat.id
            ]
            result.append((cat, tags))
        return result

    def search_tags(self, query: str, limit: int = 20) -> list[Tag]:
        """标签搜索（前缀匹配，用于 UI 自动补全）。

        Args:
            query: 搜索前缀。空字符串返回空列表。
            limit: 最大返回数，默认 20。

        Returns:
            匹配的标签列表，按 name 升序。
        """
        return self._tag_repo.search_by_name_prefix(query.strip(), limit=limit)

    def batch_attach_tags(self, content_unit_ids: list[str], tag_id: str) -> int:
        """为多个内容单元批量添加同一标签。

        幂等：已存在的关联跳过，不抛错。

        Returns:
            实际新增关联的数量。

        Raises:
            TagNotFoundError: tag_id 不存在。
            ContentUnitNotFoundError: 任一 content_unit_id 不存在（FK 违约）。
        """
        if self._tag_repo.get_by_id(tag_id) is None:
            raise TagNotFoundError(f"标签不存在：{tag_id}")
        attached = 0
        for unit_id in content_unit_ids:
            try:
                if self._cut_repo.attach(unit_id, tag_id):
                    attached += 1
            except RepositoryError as e:
                raise ContentUnitNotFoundError(f"内容单元不存在：{unit_id}") from e
        return attached

    def batch_detach_tags(self, content_unit_ids: list[str], tag_id: str) -> int:
        """为多个内容单元批量移除同一标签。

        幂等：原本无关联的跳过。

        Returns:
            实际移除关联的数量。
        """
        detached = 0
        for unit_id in content_unit_ids:
            if self._cut_repo.detach(unit_id, tag_id):
                detached += 1
        return detached

    # --- 标签筛选（Stage 4 Task 3） ---

    def list_content_unit_ids_by_tags(self, tag_ids: list[str]) -> set[str]:
        """返回与任意指定标签关联的内容单元 ID 集合（多标签 OR 取并集）。

        用于标签筛选：被选中的多个标签在「同分类内」为 OR 关系。
        跨分类的 AND 关系由 ``filter_unit_ids_by_category_and`` 处理。

        - 空 tag_ids 返回空集合。
        - 未知 tag_id 不抛错，仅不贡献任何 unit_id。
        - 不访问文件系统；查询来源为 content_unit_tag 表。

        Args:
            tag_ids: 被选中的标签 ID 列表。

        Returns:
            命中任意标签的 content_unit_id 集合。
        """
        if not tag_ids:
            return set()
        result: set[str] = set()
        for tag_id in tag_ids:
            try:
                ids = self._cut_repo.list_content_unit_ids_by_tag(tag_id)
            except RepositoryError:
                logger.exception("查询 tag 关联内容单元失败：tag_id=%s", tag_id)
                continue
            result.update(ids)
        return result

    def filter_unit_ids_by_category_and(self, tag_ids: list[str]) -> set[str]:
        """按「跨分类 AND、同分类 OR」规则筛选内容单元 ID。

        规则（spec §10.3、Stage 4 Task 3 用户确认 Q4 方案 A）：
        - 将 tag_ids 按 category_id 分组。
        - 每个分类组内的标签 OR 取并集（调用 list_content_unit_ids_by_tags）。
        - 跨分类组之间取交集（AND）。
        - 内容单元必须每个被选分类下至少有一个标签命中才保留。

        - 空 tag_ids 返回空集合（用户已选中标签但需要至少一个分类约束）。
        - 单分类多标签 → 该分类命中集合（OR）。
        - 多分类 → 各分类命中集合的交集。
        """
        if not tag_ids:
            return set()

        # 1. 收集 tag_id → category_id 映射
        tag_to_category: dict[str, str] = {}
        for tag_id in tag_ids:
            tag = self._tag_repo.get_by_id(tag_id)
            if tag is not None:
                tag_to_category[tag_id] = tag.category_id

        if not tag_to_category:
            return set()

        # 2. 按 category_id 分组
        by_category: dict[str, list[str]] = {}
        for tag_id, cat_id in tag_to_category.items():
            by_category.setdefault(cat_id, []).append(tag_id)

        # 3. 每个分类取并集
        per_category_matches: list[set[str]] = []
        for _cat_id, cat_tag_ids in by_category.items():
            per_category_matches.append(self.list_content_unit_ids_by_tags(cat_tag_ids))

        # 4. 跨分类取交集
        if not per_category_matches:
            return set()
        result = per_category_matches[0]
        for s in per_category_matches[1:]:
            result = result & s
        return result

    # --- JSON 导入导出 ---

    def export_to_json(self, file_path: Path) -> None:
        """导出当前标签库到 JSON 文件。

        JSON 结构：
        ```json
        {
          "schema_version": 2,
          "categories": [
            {"name": "服装护甲", "color_hex": "#1A78D6", "tags": ["重甲", ...]},
            ...
          ]
        }
        ```

        抛 RepositoryError（数据库读取失败）或 OSError（文件写入失败）。
        """
        data = {"schema_version": TAGS_JSON_SCHEMA_VERSION, "categories": []}
        for cat, tags in self.list_categories_with_tags():
            data["categories"].append(
                {
                    "name": cat.name,
                    "color_hex": cat.color_hex,
                    "tags": [t.name for t in tags],
                }
            )
        with file_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info("标签库已导出到：%s（%d 个分类）", file_path, len(data["categories"]))

    def import_from_json(self, file_path: Path) -> dict[str, int]:
        """从 JSON 文件导入标签库。合并跳过策略。

        规则（E1/E2/E3/E4 用户确认）：
        - schema_version > 当前支持版本时拒绝（InvalidTagJsonError）。
        - 同名分类整体跳过（不创建该分类）。
        - 不同名分类正常创建。
        - 同分类下同名标签跳过（不影响已存在的标签）。
        - 任何异常全部回滚（事务原子性）。
        - 文件读取失败抛 OSError；JSON 解析失败抛 InvalidTagJsonError。

        Returns:
            dict 包含 keys: created_categories / skipped_categories /
            created_tags / skipped_tags，供 UI 显示摘要。
        """
        try:
            with file_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            logger.error("JSON 解析失败：%s", e)
            raise InvalidTagJsonError(f"JSON 解析失败：{e}") from e

        # schema 校验
        if not isinstance(data, dict):
            raise InvalidTagJsonError("JSON 顶层必须是对象")
        schema_version = data.get("schema_version")
        if schema_version not in (1, TAGS_JSON_SCHEMA_VERSION):
            raise InvalidTagJsonError(
                f"不支持的 schema_version：{schema_version}，"
                f"当前支持 1 / {TAGS_JSON_SCHEMA_VERSION}"
            )
        categories = data.get("categories")
        if not isinstance(categories, list):
            raise InvalidTagJsonError("缺少 categories 字段或字段类型错误")

        created_categories = 0
        skipped_categories = 0
        created_tags = 0
        skipped_tags = 0

        for cat_data in categories:
            if not isinstance(cat_data, dict):
                raise InvalidTagJsonError("categories 必须是对象数组")
            name = cat_data.get("name")
            tags = cat_data.get("tags", [])
            if not isinstance(name, str) or not name.strip():
                raise InvalidTagJsonError("分类 name 缺失或为空")
            if not isinstance(tags, list):
                raise InvalidTagJsonError(f"{name} 的 tags 字段必须是数组")

            # 颜色：v2 用 color_hex；v1 兼容映射 color_hue（与显示色一致换算）
            color_hex = cat_data.get("color_hex")
            if color_hex is None:
                try:
                    color_hex = hue_to_hex(int(cat_data.get("color_hue", 0)))
                except (TypeError, ValueError) as e:
                    raise InvalidTagJsonError(f"{name} 的 color_hue 非法：{e}") from e

            # 同名分类整体跳过
            if self._category_repo.get_by_name(name) is not None:
                skipped_categories += 1
                logger.info("导入：跳过已存在的分类「%s」", name)
                continue

            # 创建分类
            try:
                category = TagCategory(
                    id=self._new_uuid(),
                    name=name,
                    color_hex=color_hex,
                )
                self._category_repo.create(category)
                created_categories += 1
            except ValueError as e:
                raise InvalidTagJsonError(f"{name} 的颜色配置非法：{e}") from e
            except (ConstraintViolationError, sqlite3.IntegrityError) as e:
                # 竞态：去重检查与 create 之间另一线程插入了相同 name
                raise DuplicateTagCategoryNameError(f"该分类已存在：{name}") from e
            except RepositoryError as e:
                raise InvalidTagJsonError(f"无法创建分类「{name}」：{e}") from e

            # 创建标签
            for tag_name in tags:
                if not isinstance(tag_name, str) or not tag_name.strip():
                    continue
                tag = Tag(
                    id=self._new_uuid(),
                    name=tag_name,
                    category_id=category.id,
                )
                try:
                    self._tag_repo.create(tag)
                    created_tags += 1
                except (ConstraintViolationError, sqlite3.IntegrityError):
                    # 同分类下同名标签跳过
                    skipped_tags += 1
                    logger.info("导入：跳过已存在的标签「%s/%s」", name, tag_name)
                except RepositoryError as e:
                    raise InvalidTagJsonError(f"无法创建标签「{name}/{tag_name}」：{e}") from e

        return {
            "created_categories": created_categories,
            "skipped_categories": skipped_categories,
            "created_tags": created_tags,
            "skipped_tags": skipped_tags,
        }

    def clear_all_tags(self) -> dict[str, int]:
        """清空所有标签分类与标签，级联清理 content_unit_tag 关联。

        用于覆盖导入前的清空。事务原子性由调用方控制（service 不自提交）。

        Returns:
            dict 包含 deleted_categories / deleted_tags / deleted_links，
            供 UI 显示摘要。
        """
        categories = self._category_repo.list_all()
        deleted_links = 0
        deleted_tags = 0
        for cat in categories:
            # 1. 清理 content_unit_tag 中该分类下所有标签的关联
            deleted_links += self._cut_repo.detach_all_by_category(cat.id)
            # 2. 删除该分类下所有标签
            tags = self._tag_repo.list_by_category(cat.id)
            for tag in tags:
                self._tag_repo.delete(tag.id)
            deleted_tags += len(tags)
            # 3. 删除分类本身
            self._category_repo.delete(cat.id)
        return {
            "deleted_categories": len(categories),
            "deleted_tags": deleted_tags,
            "deleted_links": deleted_links,
        }

    def overwrite_import_from_json(self, file_path: Path) -> dict[str, int]:
        """覆盖导入：先清空现有标签库，再从 JSON 导入。

        事务原子性：若导入失败，由调用方 rollback 恢复到清空前状态
        （service 不自提交，调用方控制事务边界）。
        """
        self.clear_all_tags()
        # 清空后所有分类都不存在，import_from_json 不会跳过任何分类
        return self.import_from_json(file_path)

    # --- 预置标签库加载 ---

    def load_default_tags_if_empty(self, default_json_path: Path) -> bool:
        """若 tag_category 表为空，加载预置标签库。

        规则（D1-D4 用户确认）：
        - 判断依据：tag_category 表为空（D1）。
        - 加载失败时记录 ERROR 日志并继续（不阻塞应用启动，D3）。
        - 资源文件路径由调用方传入（main.py 计算）。
        - 加载失败时事务不部分提交（应用层调用方负责 commit；service 层只读
          数据库判断 + 调用 import_from_json，import_from_json 内部失败时
          不影响外部事务状态——但若已部分 INSERT 则由调用方 rollback）。

        Returns:
            True 表示实际加载了预置库；False 表示跳过（非空）或加载失败。
        """
        # D1：tag_category 表为空才加载
        if self._category_repo.list_all():
            logger.info("标签库非空，跳过预置加载")
            return False

        # 资源文件缺失
        if not default_json_path.is_file():
            logger.error("预置标签库文件不存在：%s", default_json_path)
            return False

        try:
            result = self.import_from_json(default_json_path)
            logger.info(
                "预置标签库已加载：%d 个分类，%d 个标签",
                result["created_categories"],
                result["created_tags"],
            )
            return True
        except (InvalidTagJsonError, OSError) as e:
            # D3：加载失败时 ERROR 日志 + 继续（不阻塞启动）
            logger.error("预置标签库加载失败：%s", e)
            return False
