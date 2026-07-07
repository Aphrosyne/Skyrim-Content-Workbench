"""FileAssetRepository。

负责 FileAsset dataclass 与 file_asset 表之间的转换。
不访问文件系统；real_path 仅作为字符串存储。
"""

from __future__ import annotations

import logging
import sqlite3

from domain.models import AssetKind, FileAsset, FileRole
from infrastructure.repositories.errors import (
    ConstraintViolationError,
    NotFoundError,
    RepositoryError,
)

logger = logging.getLogger(__name__)


class FileAssetRepository:
    """FileAsset 的 CRUD。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(self, asset: FileAsset) -> FileAsset:
        """插入 FileAsset。"""
        try:
            self._conn.execute(
                """
                INSERT INTO file_asset (
                    id, mod_item_id, real_path, path_key, filename, extension,
                    asset_kind, role, size_bytes, modified_at, imported_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    asset.id,
                    asset.mod_item_id,
                    asset.real_path,
                    asset.path_key,
                    asset.filename,
                    asset.extension,
                    asset.asset_kind.value,
                    asset.role.value,
                    asset.size_bytes,
                    asset.modified_at,
                    asset.imported_at,
                ),
            )
        except sqlite3.IntegrityError as e:
            raise ConstraintViolationError(f"无法创建 FileAsset：{e}") from e
        except sqlite3.Error as e:
            raise RepositoryError(f"无法创建 FileAsset：{e}") from e
        return self.get_by_id(asset.id)  # type: ignore[return-value]

    def get_by_id(self, asset_id: str) -> FileAsset | None:
        """按 ID 查询；不存在返回 None。"""
        try:
            row = self._conn.execute(
                "SELECT * FROM file_asset WHERE id = ?",
                (asset_id,),
            ).fetchone()
        except sqlite3.Error as e:
            raise RepositoryError(f"无法查询 FileAsset：{e}") from e
        if row is None:
            return None
        return self._row_to_model(row)

    def list_by_mod_item(self, mod_item_id: str) -> list[FileAsset]:
        """返回指定 ModItem 的全部成员。"""
        try:
            rows = self._conn.execute(
                "SELECT * FROM file_asset WHERE mod_item_id = ? ORDER BY imported_at",
                (mod_item_id,),
            ).fetchall()
        except sqlite3.Error as e:
            raise RepositoryError(f"无法列出 FileAsset：{e}") from e
        return [self._row_to_model(r) for r in rows]

    def list_unassociated(self) -> list[FileAsset]:
        """返回未关联任何 ModItem 的素材。"""
        try:
            rows = self._conn.execute(
                "SELECT * FROM file_asset WHERE mod_item_id IS NULL ORDER BY imported_at"
            ).fetchall()
        except sqlite3.Error as e:
            raise RepositoryError(f"无法列出未关联素材：{e}") from e
        return [self._row_to_model(r) for r in rows]

    def update(self, asset: FileAsset) -> FileAsset:
        """全字段更新。实体不存在时抛 NotFoundError。"""
        try:
            cur = self._conn.execute(
                """
                UPDATE file_asset SET
                    mod_item_id = ?,
                    real_path = ?,
                    path_key = ?,
                    filename = ?,
                    extension = ?,
                    asset_kind = ?,
                    role = ?,
                    size_bytes = ?,
                    modified_at = ?
                WHERE id = ?
                """,
                (
                    asset.mod_item_id,
                    asset.real_path,
                    asset.path_key,
                    asset.filename,
                    asset.extension,
                    asset.asset_kind.value,
                    asset.role.value,
                    asset.size_bytes,
                    asset.modified_at,
                    asset.id,
                ),
            )
        except sqlite3.IntegrityError as e:
            raise ConstraintViolationError(f"无法更新 FileAsset：{e}") from e
        except sqlite3.Error as e:
            raise RepositoryError(f"无法更新 FileAsset：{e}") from e
        if cur.rowcount == 0:
            raise NotFoundError(f"FileAsset 不存在：{asset.id}")
        return self.get_by_id(asset.id)  # type: ignore[return-value]

    @staticmethod
    def _row_to_model(row: sqlite3.Row) -> FileAsset:
        return FileAsset(
            id=row["id"],
            mod_item_id=row["mod_item_id"],
            real_path=row["real_path"],
            path_key=row["path_key"],
            filename=row["filename"],
            extension=row["extension"],
            asset_kind=AssetKind(row["asset_kind"]),
            role=FileRole(row["role"]),
            size_bytes=int(row["size_bytes"]),
            modified_at=row["modified_at"],
            imported_at=row["imported_at"],
        )
