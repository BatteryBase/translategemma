#!/usr/bin/env python3
"""
从 ModelScope 下载 TranslateGemma 27B-Q8 GGUF（约 28.7GB）。

模型仓库: bullerwins/translategemma-27b-it-GGUF
目标文件: translategemma-27b-it-Q8_0.gguf
最终路径: ~/.cache/translate/models/translategemma-27b-it-Q8.gguf
          （项目代码认这个名字）

用法:
  conda activate translategemma
  cd ~/nhwork/translategemma
  python scripts/download_27b_q8.py

中断后再跑同一条命令，会尽量续传。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = "bullerwins/translategemma-27b-it-GGUF"
REMOTE_NAME = "translategemma-27b-it-Q8_0.gguf"  # ModelScope 上的文件名
CACHE_DIR = Path.home() / ".cache" / "translate" / "models"
FINAL_PATH = CACHE_DIR / "translategemma-27b-it-Q8.gguf"
MIN_OK_BYTES = 20_000_000_000  # 完整约 28.7GB


def main() -> int:
    try:
        from modelscope import snapshot_download
    except ImportError:
        print("请先安装: pip install modelscope", file=sys.stderr)
        return 1

    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if FINAL_PATH.exists() and FINAL_PATH.stat().st_size > MIN_OK_BYTES:
        print(f"已经下好了: {FINAL_PATH}")
        print(f"大小: {FINAL_PATH.stat().st_size / 1e9:.2f} GB")
        return 0

    print(f"来源: ModelScope / {REPO}")
    print(f"文件: {REMOTE_NAME}")
    print(f"保存目录: {CACHE_DIR}")
    print("大约 28.7GB，请耐心等待；断了再运行本脚本即可续传。")

    # 只下 Q8，不下其它量化
    local_dir = snapshot_download(
        REPO,
        local_dir=str(CACHE_DIR),
        allow_patterns=[REMOTE_NAME],
    )
    downloaded = Path(local_dir) / REMOTE_NAME
    if not downloaded.exists():
        # 有时会放在子目录
        matches = list(Path(local_dir).rglob(REMOTE_NAME))
        if not matches:
            print(f"下载后找不到 {REMOTE_NAME}", file=sys.stderr)
            return 1
        downloaded = matches[0]

    size = downloaded.stat().st_size
    print(f"下载到: {downloaded} ({size / 1e9:.2f} GB)")
    if size < MIN_OK_BYTES:
        print("文件还太小，可能没下完，请再运行一次。", file=sys.stderr)
        return 1

    # 链到项目认的名字
    if downloaded.resolve() != FINAL_PATH.resolve():
        if FINAL_PATH.exists() or FINAL_PATH.is_symlink():
            FINAL_PATH.unlink()
        FINAL_PATH.symlink_to(downloaded.name if downloaded.parent == CACHE_DIR else downloaded)
        print(f"已链接: {FINAL_PATH} -> {downloaded}")

    print(f"最终: {FINAL_PATH} ({FINAL_PATH.stat().st_size / 1e9:.2f} GB)")
    print("下载成功。启动服务:")
    print("  cd ~/nhwork/translategemma/scripts && ./start_api.sh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
