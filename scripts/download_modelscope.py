#!/usr/bin/env python3
"""从 ModelScope 下载 TranslateGemma PyTorch 权重（国内网络推荐）。"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

MODELSCOPE_IDS = {
    "4b": "google/translategemma-4b-it",
    "12b": "google/translategemma-12b-it",
    "27b": "google/translategemma-27b-it",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="从 ModelScope 下载 TranslateGemma 模型")
    parser.add_argument("size", choices=MODELSCOPE_IDS.keys(), default="27b", nargs="?")
    parser.add_argument(
        "--output",
        "-o",
        default=str(Path.home() / "nhwork/translategemma/models/translategemma-27b-it"),
        help="下载目标目录（默认: ~/nhwork/translategemma/models/translategemma-<size>-it）",
    )
    args = parser.parse_args()

    model_id = MODELSCOPE_IDS[args.size]
    if args.output.endswith("27b-it") and args.size != "27b":
        output = Path.home() / "nhwork/translategemma/models" / f"translategemma-{args.size}-it"
    else:
        output = Path(args.output)

    try:
        from modelscope import snapshot_download
    except ImportError:
        raise SystemExit("请先安装: pip install modelscope")

    output.parent.mkdir(parents=True, exist_ok=True)
    print(f"ModelScope 模型: {model_id}")
    print(f"保存目录: {output}")
    print("约 51GB（27b），请耐心等待…")

    path = snapshot_download(model_id, local_dir=str(output))
    print(f"\n下载完成: {path}")
    print("\n请在 .env 中设置:")
    print(f"MODEL_LOCAL_PATH={path}")
    print("\n然后启动:")
    print("  cd ~/nhwork/translategemma && sudo uvicorn app_fastapi:app --host 0.0.0.0 --port 80")


if __name__ == "__main__":
    main()
