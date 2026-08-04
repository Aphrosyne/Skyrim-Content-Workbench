"""归档内容清单生成（功能增加1，2026-08-04）。

迁移自用户参考脚本 ``src/archive_selector.py``（控制台交互版，已并入项目）：
- 仅记录目标目录的**直接子项**，不向内搜索；
- 文件夹在前、文件在后，各自按名称不区分大小写排序；
- 输出 ``{目标目录名}归档内容.txt``（UTF-8）到指定输出目录
  （归档根目录右键调用时输出到其上级目录，避免清单被再次归档）。

约束：只生成派生文本清单，不读取压缩包内部、不修改用户文件。
"""

from __future__ import annotations

from pathlib import Path


class ArchiveManifestService:
    """生成归档内容清单的 Application 服务。"""

    def generate_manifest(self, target_dir: Path, output_dir: Path) -> Path:
        """生成归档内容清单并返回输出文件路径。

        Args:
            target_dir: 归档根目录（仅记录其直接子项）。
            output_dir: 输出目录（通常为 target_dir 的上级目录）。

        Returns:
            生成的清单文件路径。

        Raises:
            OSError: 目录不可读 / 清单写入失败（由调用方转换为用户可读错误）。
        """
        items = sorted(
            target_dir.iterdir(),
            key=lambda p: (0 if p.is_dir() else 1, p.name.lower()),
        )
        output_file = output_dir / f"{target_dir.name}归档内容.txt"
        output_file.write_text("".join(f"{item.name}\n" for item in items), encoding="utf-8")
        return output_file
