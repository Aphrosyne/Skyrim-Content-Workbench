"""Nexus 文件名解析共享模块（操作便捷性8/9，2026-08-04）。

集中 Nexus 下载文件名相关的纯函数（无 DB / 无 UI 依赖）：
- ``extract_mod_name``：提取主要内容名（创建 Mod 组与浏览器搜索共用，
  从 content_unit_creation_service 迁入，消除正则重复）。
- ``extract_nexus_id``：提取 N 网 Mod ID（用户称"尾号"）。
- ``build_nexus_url``：按内容单元路径生成 N 网来源 URL——
  文件用自身文件名；文件夹优先自身名，否则取内部文件**最小 ID**
  （汉化一定比本体后发，其 ID 更大，最小者即本体，用户确认 2026-08-04）。
- ``mod_search_query``：构造浏览器搜索词（extract_mod_name 去尾号 +
  下划线/横线替换为空格 + 前缀）。

格式检查（用户确认 2026-08-04）：不匹配 Nexus 模式的文件名一律返回 None，
调用方必须静默跳过——不填、不报错、不弹窗，绝不允许"前缀+空值"。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


# Nexus Mods 下载文件名正则模式。
#
# Nexus 下载文件命名规律：`Mod名称-数字ID-版本号-时间戳`
# 例如：
#   "Alt-Tab Fix-148466-1-0-0-1745430887.zip"
#   "monster race crash fix-19899-1-2-1583905408.zip"
#   "Erin Suzu preset-173150-1-0-1771738716"
#   "Birthplace of a Kitsune-26416-1-1-1588673209.zip" → ID 26416
#
# 关键特征：第一个以 `-` 分隔的纯数字段是 Nexus Mod ID，
# ID 之后的所有内容（版本号、时间戳）都应剔除，
# ID 之前的内容是 Mod 名称（保留原样，包括名称内部的 `-`）。
#
# 非贪婪 + 后续至少一个数字段，确保 name 不会吞掉 ID。
# 要求 ID 后至少有一个段，避免误匹配 "Mod-123" 这种短名。
_NEXUS_PATTERN = re.compile(r"^(?P<name>.+?)-(?P<id>\d+)(?:-\d+)+$")


# 通用版本号正则模式（extract_mod_name 回退策略，用于非 Nexus 命名）
# 匹配末尾的 " 1.0" / " v2.3" / " - 3.1" / " 1.0.0" / " 5.1 SE" 等形式
# 不匹配下划线分隔（避免误剔除 "ModName_1.0" 这种可能是名字本身的情况）
_VERSION_PATTERN = re.compile(
    r"""
    \s*              # 前导空白（可选）
    (?:-\s*)?        # 可选的 - 分隔符
    v?               # 可选的 v 前缀
    \d+              # 至少一位数字
    (?:\.\d+)+       # 至少一个 .数字 组合（如 .0 / .1.0 / .5.1）
    (?:\s*(?:SE|LE|SSE|AE))?  # 可选的 SE/LE/SSE/AE 后缀
    \s*$             # 末尾空白（可选）
    """,
    re.IGNORECASE | re.VERBOSE,
)


def extract_mod_name(filename: str) -> str:
    """从文件名提取主要名称。

    支持两种命名规则：

    1. Nexus Mods 下载命名：`Mod名称-数字ID-版本号-时间戳`
       例如：
         "Alt-Tab Fix-148466-1-0-0-1745430887.zip" → "Alt-Tab Fix"
         "monster race crash fix-19899-1-2-1583905408.zip" → "monster race crash fix"
         "Erin Suzu preset-173150-1-0-1771738716" → "Erin Suzu preset"

    2. 通用命名（社区分享、汉化包等）：剔除末尾版本号
       例如：
         "BDOR Black Knight 1.0.7z" → "BDOR Black Knight"
         "SkyUI 5.1 SE.zip" → "SkyUI"
         "Armor Pack - 2.3.7z" → "Armor Pack"
         "RealisticWater.7z" → "RealisticWater"（无版本号，仅去扩展名）
         "寒霜之心 1.0.7z" → "寒霜之心"

    Args:
        filename: 文件名（含扩展名，不含目录路径）。

    Returns:
        提取的主要名称。若无版本号且非 Nexus 命名，返回去扩展名的部分。
    """
    # 先去扩展名（Path.stem 处理多扩展名场景，如 "file.1.0.7z" → "file.1.0"）
    stem = Path(filename).stem

    # 优先尝试 Nexus 命名规则
    # 要求：至少包含 ID + 一个后续段（版本号或时间戳），避免误匹配 "Mod-123" 这种短名
    nexus_match = _NEXUS_PATTERN.match(stem)
    if nexus_match:
        name = nexus_match.group("name").strip()
        if name:
            return name

    # 回退：通用版本号剔除（兼容社区分享、汉化包等命名）
    # rstrip(" .-") 剥离版本号前的分隔符（空格 / - / .）
    match = _VERSION_PATTERN.search(stem)
    if match:
        return stem[: match.start()].rstrip(" .-")
    return stem


def extract_nexus_id(filename: str) -> str | None:
    """从文件名提取 N 网 Mod ID（用户称"尾号"）。

    仅匹配 Nexus 模式 `名称-ID-版本-…`（如
    "Birthplace of a Kitsune-26416-1-1-1588673209.zip" → "26416"）。
    不匹配（普通压缩包、汉化包、readme 等）返回 None——调用方必须静默跳过。
    """
    stem = Path(filename).stem
    match = _NEXUS_PATTERN.match(stem)
    if match is None:
        return None
    return match.group("id")


def build_nexus_url(path: Path, prefix: str) -> str | None:
    """按内容单元路径生成 N 网来源 URL；无法识别时返回 None。

    - 文件：文件名匹配 Nexus 模式 → ``prefix + ID``。
    - 文件夹：文件夹名自身含 Nexus ID → 用之；否则遍历顶层文件收集全部
      Nexus ID 取**最小**（汉化后发 → ID 更大，最小者即本体，用户确认
      2026-08-04）；无任何匹配返回 None。

    调用方在拿到 None 时必须静默跳过（不填、不报错、不弹窗）。
    """
    try:
        mod_id = _folder_nexus_id(path) if path.is_dir() else extract_nexus_id(path.name)
    except OSError:
        logger.debug("build_nexus_url: 路径不可访问 %s", path)
        return None
    if mod_id is None:
        return None
    return prefix.rstrip("/") + "/" + mod_id


def _folder_nexus_id(folder: Path) -> str | None:
    """文件夹内取本体 ID：自身名优先，否则内部文件最小 ID。"""
    own = extract_nexus_id(folder.name)
    if own is not None:
        return own

    ids: list[int] = []
    try:
        for child in folder.iterdir():
            if child.is_file():
                mid = extract_nexus_id(child.name)
                if mid is not None:
                    ids.append(int(mid))
    except OSError:
        return None
    if not ids:
        return None
    return str(min(ids))


def mod_search_query(name: str, prefix: str) -> str | None:
    """构造浏览器搜索词（操作便捷性9）。

    - 与创建 Mod 组取名字一致：extract_mod_name 自动删掉无用尾号
      （N 网 ID/版本/时间戳、通用版本号），仅保留有效文件名信息。
    - 下划线和横线替换为空格。
    - 前缀（默认 "skyrim "）拼在搜索词前。

    清理后为空返回 None（调用方静默跳过）。
    """
    base = extract_mod_name(name)
    cleaned = re.sub(r"[_\-]+", " ", base).strip()
    if not cleaned:
        return None
    query = f"{prefix.strip()} {cleaned}".strip() if prefix else cleaned
    return query or None
