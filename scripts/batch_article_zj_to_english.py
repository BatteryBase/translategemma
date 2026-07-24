#!/usr/bin/env python3
"""
从 ArangoDB 拉取文章 → 本机 TranslateGemma 中译英 → 写回同一篇文档的英文字段。

对应原 JS: batchArticleZJToEnglish.js

如何判断「已翻译」:
  - 整篇完成并写库后，文档会带 hasZhangJun=1
  - 查询条件 FILTER a.hasZhangJun != 1，所以下次自动跳过已完成的文章
  - 另有 hasDeepl=1 的也会跳过（DeepL 已处理过）

断点续跑:
  - 每译完一段，写入本地 checkpoint: scripts/.zj_progress/<文章key>.json
  - Ctrl+C / 崩溃后重新运行同一命令，会跳过已译段落，从中断处继续
  - 整篇写库成功后删除该 checkpoint
  - --dry-run 也会写 checkpoint（方便试跑续传）；成功结束后同样删除

用法示例:
  export ARANGO_USER=root
  export ARANGO_PASSWORD='你的密码'
  python batch_article_zj_to_english.py --limit 1
  python batch_article_zj_to_english.py --article-key 9318039520
  python batch_article_zj_to_english.py --limit 5 --dry-run
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import requests

# ---------- 可改配置（也可用环境变量覆盖） ----------
ARANGO_URL = os.environ.get("ARANGO_URL", "http://218.93.190.182:8529").rstrip("/")
ARANGO_DB = os.environ.get("ARANGO_DB", "nyztest")
ARANGO_USER = os.environ.get("ARANGO_USER", "")
ARANGO_PASSWORD = os.environ.get("ARANGO_PASSWORD", "")
TRANSLATE_URL = os.environ.get("TRANSLATE_URL", "http://127.0.0.1:8022").rstrip("/")
COLLECTION = "my_nyz_article"

# 单条翻译超时（秒）。27B 长段落可能很慢，按需加大
TRANSLATE_TIMEOUT = int(os.environ.get("TRANSLATE_TIMEOUT", "1800"))

SCRIPT_DIR = Path(__file__).resolve().parent
PROGRESS_DIR = SCRIPT_DIR / ".zj_progress"


class ArangoClient:
    def __init__(self, url: str, db: str, user: str, password: str):
        self.base = f"{url}/_db/{db}"
        self.session = requests.Session()
        if user:
            self.session.auth = (user, password)

    def query(self, aql: str, bind_vars: dict | None = None) -> list[Any]:
        payload = {"query": aql, "bindVars": bind_vars or {}}
        r = self.session.post(f"{self.base}/_api/cursor", json=payload, timeout=120)
        if r.status_code >= 400:
            raise RuntimeError(f"ArangoDB query failed {r.status_code}: {r.text}")
        data = r.json()
        rows = list(data.get("result") or [])
        while data.get("hasMore"):
            r = self.session.put(
                f"{self.base}/_api/cursor/{data['id']}", timeout=120
            )
            if r.status_code >= 400:
                raise RuntimeError(f"ArangoDB cursor failed {r.status_code}: {r.text}")
            data = r.json()
            rows.extend(data.get("result") or [])
        return rows


# ---------- checkpoint（段落级断点） ----------
def progress_path(article_key: str) -> Path:
    return PROGRESS_DIR / f"{article_key}.json"


def load_progress(article_key: str) -> dict:
    path = progress_path(article_key)
    if not path.exists():
        return {"article_key": article_key, "content": {}, "meta": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"article_key": article_key, "content": {}, "meta": {}}
    data.setdefault("article_key", article_key)
    data.setdefault("content", {})
    data.setdefault("meta", {})
    # JSON 的 key 都是 str
    data["content"] = {str(k): v for k, v in data["content"].items()}
    data["meta"] = {str(k): v for k, v in data["meta"].items()}
    return data


def save_progress(article_key: str, progress: dict) -> None:
    PROGRESS_DIR.mkdir(parents=True, exist_ok=True)
    path = progress_path(article_key)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    tmp.replace(path)


def clear_progress(article_key: str) -> None:
    path = progress_path(article_key)
    if path.exists():
        path.unlink()
        print(f"  checkpoint cleared: {path.name}")


def collect_text_nodes(content: Any, out: list[dict]) -> None:
    """递归收集 content 树里 type==text 且非空的节点（原地引用，便于回写）。"""
    if not isinstance(content, list):
        return
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "text":
            text = item.get("text") or ""
            if str(text).strip():
                out.append({"node": item, "text": text})
        if "content" in item:
            collect_text_nodes(item.get("content"), out)


def translate_one(text: str, source_lang: str = "zh", target_lang: str = "en") -> str:
    """单条翻译，失败抛异常。"""
    url = f"{TRANSLATE_URL}/api/translate"
    payload = {
        "text": text,
        "source_lang": source_lang,
        "target_lang": target_lang,
    }
    r = requests.post(url, json=payload, timeout=TRANSLATE_TIMEOUT)
    if r.status_code >= 400:
        raise RuntimeError(f"translate HTTP {r.status_code}: {r.text[:500]}")
    data = r.json()
    if data.get("status") != "success" or not data.get("result"):
        raise RuntimeError(
            f"translate failed: {json.dumps(data, ensure_ascii=False)[:500]}"
        )
    return data["result"]


def translate_many_with_checkpoint(
    texts: list[str],
    *,
    label: str,
    article_key: str,
    progress: dict,
    bucket: str,
) -> list[str]:
    """
    逐条翻译；已在 checkpoint[bucket] 里的下标直接复用，新结果立刻落盘。
    bucket: "content" | "meta"
    """
    cache: dict = progress.setdefault(bucket, {})
    results: list[str] = [""] * len(texts)
    total = len(texts)
    done = sum(1 for i in range(total) if str(i) in cache)
    if done:
        print(f"  [{label}] resume: {done}/{total} already done")

    for i, text in enumerate(texts):
        key = str(i)
        if key in cache and cache[key]:
            results[i] = cache[key]
            preview = (cache[key][:40] + "…") if len(cache[key]) > 40 else cache[key]
            print(f"  [{label}] {i + 1}/{total}  SKIP (checkpoint)  {preview!r}")
            continue

        preview = (text[:40] + "…") if len(text) > 40 else text
        print(f"  [{label}] {i + 1}/{total}  len={len(text)}  {preview!r}")
        t0 = time.time()
        translated = translate_one(text)
        print(f"    ok  {int((time.time() - t0) * 1000)} ms  -> {len(translated)} chars")
        results[i] = translated
        cache[key] = translated
        save_progress(article_key, progress)

    return results


def translate_article(source: dict, article_key: str) -> dict:
    """
    翻译一篇文章，返回要 update 到 Arango 的字段。
    content_english: 深拷贝 content 树，并把 text 节点替换成英文。
    """
    progress = load_progress(article_key)
    if progress_path(article_key).exists():
        print(f"  loaded checkpoint: {progress_path(article_key)}")

    content_en = copy.deepcopy(source.get("content"))
    text_nodes: list[dict] = []
    if isinstance(content_en, dict):
        collect_text_nodes(content_en.get("content"), text_nodes)

    if text_nodes:
        print(f"  content text nodes: {len(text_nodes)}")
        translated = translate_many_with_checkpoint(
            [t["text"] for t in text_nodes],
            label="content",
            article_key=article_key,
            progress=progress,
            bucket="content",
        )
        for node_info, en in zip(text_nodes, translated):
            node_info["node"]["text"] = en
        print("  content success")
    else:
        print("  content: no text nodes")

    other = [
        source.get("summary") or "总结",
        source.get("title") or "标题",
        source.get("text") or "文本内容",
        source.get("index") or "空",
    ]
    other_en = translate_many_with_checkpoint(
        other,
        label="meta",
        article_key=article_key,
        progress=progress,
        bucket="meta",
    )
    print("  otherContent success")

    return {
        "hasZhangJun": 1,
        "summary_english": other_en[0],
        "title_english": other_en[1],
        "content_english": content_en,
        "text_english": other_en[2],
        "wordNumber_english": len(other_en[2]),
        "index_english": other_en[3],
        "updateTime": int(time.time() * 1000),
    }


def list_article_keys(db: ArangoClient, limit: int, article_key: str | None) -> list[str]:
    if article_key:
        rows = db.query(
            "FOR a IN @@col FILTER a._key == @key RETURN a._key",
            {"@col": COLLECTION, "key": article_key},
        )
        return [str(x) for x in rows]

    # hasZhangJun=1 → 本脚本已完成；hasDeepl=1 → DeepL 已处理，也跳过
    aql = """
    FOR a IN @@col
      FILTER a.hasZhangJun != 1
         AND a.hasDeepl != 1
         AND a.status == 1
         AND !a.isEmpty
         AND !a.isDraft
         AND IS_OBJECT(a.content)
         AND IS_ARRAY(a.content.content)
      SORT TO_NUMBER(a._key) ASC
      LIMIT @limit
      RETURN a._key
    """
    rows = db.query(aql, {"@col": COLLECTION, "limit": int(limit)})
    return [str(x) for x in rows]


def fetch_article(db: ArangoClient, key: str) -> dict | None:
    rows = db.query(
        "FOR a IN @@col FILTER a._key == @key RETURN a",
        {"@col": COLLECTION, "key": key},
    )
    return rows[0] if rows else None


def update_article(db: ArangoClient, key: str, data: dict) -> dict | None:
    aql = """
    FOR a IN @@col
      FILTER a._key == @key AND a.status == 1
      UPDATE a WITH @data IN @@col
      RETURN NEW
    """
    rows = db.query(aql, {"@col": COLLECTION, "key": key, "data": data})
    return rows[0] if rows else None


def check_translate_alive() -> None:
    try:
        r = requests.get(f"{TRANSLATE_URL}/health", timeout=10)
        print(f"translate health: HTTP {r.status_code}  {r.text[:120]}")
        if r.status_code >= 400:
            raise RuntimeError("health not ok")
    except Exception as e:
        raise SystemExit(
            f"翻译服务不可用 ({TRANSLATE_URL}): {e}\n"
            f"请先: cd ~/nhwork/translategemma/scripts && ./start_api.sh"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="批量文章中译英并写回 ArangoDB")
    parser.add_argument("--limit", type=int, default=10, help="一次处理多少篇（对应原 time）")
    parser.add_argument("--article-key", default=None, help="只处理指定 _key")
    parser.add_argument("--dry-run", action="store_true", help="只翻译不写库（仍会写本地 checkpoint）")
    parser.add_argument(
        "--clear-checkpoint",
        action="store_true",
        help="开始前清除本批文章的本地 checkpoint（强制重译段落）",
    )
    args = parser.parse_args()

    if not ARANGO_USER or not ARANGO_PASSWORD:
        print(
            "请设置 ArangoDB 账号:\n"
            "  export ARANGO_USER=root\n"
            "  export ARANGO_PASSWORD='你的密码'",
            file=sys.stderr,
        )
        return 2

    print(f"ArangoDB: {ARANGO_URL}  db={ARANGO_DB}")
    print(f"Translate: {TRANSLATE_URL}")
    print(f"Checkpoint dir: {PROGRESS_DIR}")
    check_translate_alive()

    db = ArangoClient(ARANGO_URL, ARANGO_DB, ARANGO_USER, ARANGO_PASSWORD)
    keys = list_article_keys(db, args.limit, args.article_key)
    if not keys:
        print("文章不存在 / 没有待处理文章（可能都已 hasZhangJun=1）")
        return 0

    if args.clear_checkpoint:
        for key in keys:
            clear_progress(key)

    print(f"articles ({len(keys)}): {keys}")
    t_start = time.time()
    ok, fail = 0, 0

    for i, key in enumerate(keys, 1):
        article = fetch_article(db, key)
        if not article:
            print(f"[{i}/{len(keys)}] skip missing {key}")
            fail += 1
            continue

        # 已完成的文章（手动指定 --article-key 时也可能已有标记）
        if article.get("hasZhangJun") == 1 and not args.article_key:
            print(f"[{i}/{len(keys)}] skip already hasZhangJun=1  {key}")
            clear_progress(key)
            continue

        print(f"\n======= [{i}/{len(keys)}] {key}  {article.get('title')} =======")
        try:
            patch = translate_article(article, key)
            if args.dry_run:
                print("  dry-run: 不写库")
                print(
                    "  title_english:",
                    (patch.get("title_english") or "")[:120],
                )
            else:
                updated = update_article(db, key, patch)
                if not updated:
                    raise RuntimeError("update 未命中文档（可能 status!=1）")
                print("  update success (hasZhangJun=1)")
            clear_progress(key)
            ok += 1
        except KeyboardInterrupt:
            print("\n  interrupted — checkpoint 已保存，重跑同一命令即可续传")
            return 130
        except Exception as e:
            fail += 1
            print(f"  FAILED: {e}")
            print("  checkpoint 保留，修好后重跑可续传")
            try:
                requests.get(f"{TRANSLATE_URL}/health", timeout=5)
            except Exception:
                print("  翻译服务疑似挂掉，停止后续文章")
                break

    elapsed = int((time.time() - t_start) * 1000)
    print(f"\n------------------- done {elapsed} ms  ok={ok} fail={fail} -------------------")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
