#!/usr/bin/env python3
"""Collect a day's or week's coding-agent activity, grouped by day.

Reads local session transcripts from **Claude Code** (`~/.claude/projects/*/*.jsonl`)
and/or **Codex** (`~/.codex/sessions/**/rollout-*.jsonl`), filters to a Monday–Sunday
week (or a single day) in local time, and emits a compact per-day digest as JSON for
the report skill to summarize.

Deterministic work (week math, parsing both formats, noise filtering, grouping, fork
de-duplication, secret redaction, link extraction) lives here so the model only does
semantic work (thread → daily → weekly, work/personal classification).

Usage:
    collect_week.py [--source claude|codex|all] [--week-offset N] [--date YYYY-MM-DD]
                    [--single-day] [--projects-dir PATH] [--codex-dir PATH]
                    [--max-prompts N] [--head-snippets N] [--tail-snippets N]
                    [--snippet-chars N] [--no-dedup]
"""
import argparse
import glob
import json
import os
import re
import sys
from collections import defaultdict, deque
from datetime import datetime, timedelta

# --- noise filtering -----------------------------------------------------------

# user text that is harness/tooling noise, not real user intent (both agents)
_NOISE_PREFIXES = (
    "<system-reminder", "<command-", "<local-command", "<bash-", "Caveat:",
    "[Request interrupted", "<user-memory", "<post-tool", "<task-notification",
    # codex-specific wrappers
    "# AGENTS.md", "<environment_context", "# Context from my IDE", "<permissions",
    "<user_instructions", "## Active file:", "<turn_aborted", "<user_turn",
)
_REQUEST_MARKER = "## My request for Codex:"  # real request follows this in IDE ctx
_GENERIC_PROMPTS = {
    "continue from where you left off.", "现在可以了吗？", "现在可以了吗",
    "好的", "好的，就这样", "好的就这样", "中文回答我", "翻译完了吗？",
    "进度如何，怎么看？", "好的，删除吧",
}
_CLAUDE_FILE_TOOLS = {"Edit", "Write", "NotebookEdit", "MultiEdit"}
_APPLY_PATCH_FILE = re.compile(r"\*\*\* (?:Add|Update|Delete) File: (.+)")


def _clean_user_text(text):
    t = (text or "").strip()
    if not t:
        return None
    if _REQUEST_MARKER in t:                     # codex IDE context wrapper
        t = t.split(_REQUEST_MARKER, 1)[1].strip()
    for p in _NOISE_PREFIXES:
        if t.startswith(p):
            return None
    return t or None


# --- secret redaction (must run before anything leaves this script) ------------

_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"AKLT[A-Za-z0-9+/=_-]{10,}"),
    re.compile(r"AKIA[0-9A-Z]{12,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{6,}"),
    re.compile(r"(?i)(pass(?:word|wd)?|密\s*码|secret(?:\s*access\s*key)?|"
               r"access\s*key(?:\s*id)?|api[_-]?key|token|bearer)\s*[:=：]\s*\S+"),
]


def _label_redact(m):
    full, label = m.group(0), m.group(1)
    rest = full[full.lower().find(label.lower()) + len(label):]
    sep = rest[: len(rest) - len(rest.lstrip(" :=："))]
    return full[: len(full) - len(rest)] + sep + "[REDACTED]"


def _redact(text):
    if not text:
        return text
    out = text
    for pat in _SECRET_PATTERNS:
        out = pat.sub(_label_redact if pat.groups else "[REDACTED]", out)
    return out


# --- link extraction -----------------------------------------------------------

_URL_RE = re.compile(r"https?://[^\s\)\]\}<>\"']+")
_LINK_HINTS = ("merge_request", "/pull/", "/-/", "notion.", "langfuse", "docs.",
               "confluence", "/issues/", "figma.", "feishu", "shimo")


def _extract_links(text):
    out = []
    for m in _URL_RE.findall(text or ""):
        url = m.rstrip(".,;*`_~")
        if "..." in url:
            continue
        if any(h in url.lower() for h in _LINK_HINTS):
            out.append(url)
    return out


# --- normalized message iterators (one record per message/tool event) ----------
# record = dict(ts, sid, cwd, role, texts:list, tools:list, files:list)

def _ts_ok(raw):
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def iter_claude(path):
    sid_default = os.path.basename(path).replace(".jsonl", "")
    for line in open(path, "r", errors="replace"):
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            continue
        if o.get("type") not in ("user", "assistant"):
            continue
        ts = o.get("timestamp")
        if not ts:
            continue
        msg = o.get("message", {})
        content = msg.get("content") if isinstance(msg, dict) else None
        texts, tools, files = [], [], []
        if isinstance(content, str):
            texts.append(content)
        elif isinstance(content, list):
            for b in content:
                if not isinstance(b, dict):
                    continue
                bt = b.get("type")
                if bt == "text":
                    texts.append(b.get("text", ""))
                elif bt == "tool_use":
                    name = b.get("name", "")
                    if name:
                        tools.append(name)
                    if name in _CLAUDE_FILE_TOOLS:
                        fp = (b.get("input") or {}).get("file_path") \
                            or (b.get("input") or {}).get("notebook_path")
                        if fp:
                            files.append(fp)
        yield {"ts": ts, "sid": o.get("sessionId") or sid_default,
               "cwd": o.get("cwd", ""), "role": o["type"],
               "texts": texts, "tools": tools, "files": files}


def iter_codex(path):
    sid = os.path.basename(path).replace(".jsonl", "")
    cwd = ""
    for line in open(path, "r", errors="replace"):
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            continue
        typ = o.get("type")
        p = o.get("payload") if isinstance(o.get("payload"), dict) else {}
        if typ == "session_meta":
            sid = p.get("id") or sid
            cwd = p.get("cwd", cwd)
            continue
        if typ != "response_item":
            continue
        ts = o.get("timestamp")
        if not ts:
            continue
        pt = p.get("type")
        if pt == "message":
            role = p.get("role")
            if role not in ("user", "assistant"):
                continue
            texts = [b.get("text", "") for b in (p.get("content") or [])
                     if isinstance(b, dict) and b.get("type") in
                     ("input_text", "output_text", "text")]
            yield {"ts": ts, "sid": sid, "cwd": cwd, "role": role,
                   "texts": texts, "tools": [], "files": []}
        elif pt in ("function_call", "custom_tool_call", "web_search_call"):
            name = p.get("name") or p.get("tool_name") or pt
            args = p.get("arguments") or p.get("input") or ""
            if not isinstance(args, str):
                args = json.dumps(args, ensure_ascii=False)
            files = _APPLY_PATCH_FILE.findall(args)
            yield {"ts": ts, "sid": sid, "cwd": cwd, "role": "assistant",
                   "texts": [], "tools": [name], "files": [f.strip() for f in files]}


def _head_tail(items, head, tail):
    if len(items) <= head + tail:
        return list(items)
    seen, out = set(), []
    for x in items[:head] + items[-tail:]:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _fingerprint(user_prompts):
    for pmt in user_prompts:
        low = pmt.strip().lower()
        if low in _GENERIC_PROMPTS or len(low) < 8:
            continue
        return re.sub(r"\s+", " ", low)[:140]
    return None


def week_bounds(anchor):
    monday = anchor - timedelta(days=anchor.weekday())
    start = monday.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=7) - timedelta(seconds=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["claude", "codex", "all"], default="all")
    ap.add_argument("--week-offset", type=int, default=0)
    ap.add_argument("--date", default=None)
    ap.add_argument("--single-day", action="store_true")
    ap.add_argument("--projects-dir", default=os.path.expanduser("~/.claude/projects"))
    ap.add_argument("--codex-dir", default=os.path.expanduser("~/.codex/sessions"))
    ap.add_argument("--max-prompts", type=int, default=16)
    ap.add_argument("--head-snippets", type=int, default=4)
    ap.add_argument("--tail-snippets", type=int, default=8)
    ap.add_argument("--snippet-chars", type=int, default=320)
    ap.add_argument("--no-dedup", action="store_true")
    args = ap.parse_args()

    local_tz = datetime.now().astimezone().tzinfo
    if args.date:
        anchor = datetime.strptime(args.date, "%Y-%m-%d").replace(tzinfo=local_tz)
    else:
        anchor = datetime.now(local_tz)
    anchor = anchor + timedelta(weeks=args.week_offset)
    if args.single_day:
        start = anchor.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1) - timedelta(seconds=1)
    else:
        start, end = week_bounds(anchor)

    # build the list of (path, iterator, source) to scan
    scans = []
    if args.source in ("claude", "all"):
        for path in glob.glob(os.path.join(args.projects_dir, "*", "*.jsonl")):
            scans.append((path, iter_claude, "claude"))
    if args.source in ("codex", "all"):
        for path in glob.glob(os.path.join(args.codex_dir, "**", "rollout-*.jsonl"),
                              recursive=True):
            scans.append((path, iter_codex, "codex"))

    raw = {}
    for path, it, source in scans:
        try:
            if datetime.fromtimestamp(os.path.getmtime(path), local_tz) < start:
                continue
        except OSError:
            continue
        for rec in it(path):
            ts = _ts_ok(rec["ts"])
            if ts is None:
                continue
            ts_local = ts.astimezone(local_tz)
            if ts_local < start or ts_local > end:
                continue
            day = ts_local.strftime("%Y-%m-%d")
            key = (source, rec["sid"], day)
            s = raw.get(key)
            if s is None:
                s = raw[key] = {
                    "source": source, "session_id": rec["sid"], "day": day,
                    "cwd": rec.get("cwd", ""), "first_ts": rec["ts"], "last_ts": rec["ts"],
                    "user_prompts": [], "_seen": set(),
                    "head": [], "tail": deque(maxlen=args.tail_snippets),
                    "tool_activity": defaultdict(int), "files_touched": set(), "links": set(),
                }
            if not s["cwd"] and rec.get("cwd"):
                s["cwd"] = rec["cwd"]
            if rec["ts"] < s["first_ts"]:
                s["first_ts"] = rec["ts"]
            if rec["ts"] > s["last_ts"]:
                s["last_ts"] = rec["ts"]
            for name in rec["tools"]:
                s["tool_activity"][name] += 1
            for fp in rec["files"]:
                s["files_touched"].add(fp)
            for txt in rec["texts"]:
                s["links"].update(_extract_links(txt))
                if rec["role"] == "user":
                    c = _clean_user_text(txt)
                    if c and c not in s["_seen"]:
                        s["_seen"].add(c)
                        s["user_prompts"].append(_redact(c[: args.snippet_chars * 3]))
                else:
                    t = (txt or "").strip()
                    if t:
                        snip = _redact(t[: args.snippet_chars])
                        if len(s["head"]) < args.head_snippets:
                            s["head"].append(snip)
                        s["tail"].append(snip)

    def finalize(bucket_list):
        bs = sorted(bucket_list, key=lambda b: b["first_ts"])
        prompts, pseen, snips, sseen = [], set(), [], set()
        tools, files, links, sids = defaultdict(int), set(), set(), []
        for b in bs:
            sids.append(b["session_id"])
            links |= b["links"]
            for pmt in b["user_prompts"]:
                if pmt not in pseen:
                    pseen.add(pmt)
                    prompts.append(pmt)
            for sn in b["head"] + [x for x in b["tail"] if x not in b["head"]]:
                if sn not in sseen:
                    sseen.add(sn)
                    snips.append(sn)
            for k, v in b["tool_activity"].items():
                tools[k] += v
            files |= b["files_touched"]
        return {
            "source": bs[0]["source"], "session_count": len(bs), "session_ids": sids,
            "cwd": bs[0]["cwd"], "first_ts": bs[0]["first_ts"],
            "last_ts": max(b["last_ts"] for b in bs),
            "user_prompts": _head_tail(prompts, args.max_prompts // 2,
                                       args.max_prompts - args.max_prompts // 2),
            "assistant_snippets": _head_tail(snips, args.head_snippets, args.tail_snippets),
            "tool_activity": dict(sorted(tools.items(), key=lambda kv: -kv[1])),
            "files_touched": sorted(files)[:25], "links": sorted(links)[:15],
        }

    by_day = defaultdict(list)
    for b in raw.values():
        by_day[b["day"]].append(b)

    days = {}
    for day in sorted(by_day):
        buckets = by_day[day]
        if args.no_dedup:
            groups = [[b] for b in buckets]
        else:
            fp_groups, standalone = defaultdict(list), []
            for b in buckets:
                fp = _fingerprint(b["user_prompts"])
                if fp:                       # fork-merge within the same source only
                    fp_groups[(b["source"], fp)].append(b)
                else:
                    standalone.append(b)
            groups = list(fp_groups.values()) + [[b] for b in standalone]
        threads = [finalize(g) for g in groups]
        threads.sort(key=lambda t: t["first_ts"])
        days[day] = threads

    out = {
        "mode": "day" if args.single_day else "week",
        "sources": ("claude", "codex") if args.source == "all" else (args.source,),
        "week_start": start.strftime("%Y-%m-%d"), "week_end": end.strftime("%Y-%m-%d"),
        "timezone": str(local_tz), "generated_at": datetime.now(local_tz).isoformat(),
        "day_count": len(days), "thread_count": sum(len(v) for v in days.values()),
        "deduped": not args.no_dedup, "days": days,
    }
    json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
