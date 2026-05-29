#!/usr/bin/env python3
"""Collect a day's or week's Claude Code session activity, grouped by day.

Reads all session transcripts under ~/.claude/projects/*/*.jsonl, filters
messages to a Monday-Sunday week (or a single day) in local time, and emits a
compact per-day digest as JSON for the report skill to summarize.

Deterministic work (week math, JSONL parsing, noise filtering, grouping,
fork de-duplication) lives here so the model only does semantic work
(thread -> daily -> weekly, work/personal classification).

Two notable behaviors:
  * Snippets are captured head + tail per thread, so a session's closing
    *conclusions* survive (they live at the end, not the start).
  * Forked sessions (same conversation continued in several windows -> different
    sessionIds but the same opening prompt) are merged within a day into one
    thread, unless --no-dedup is passed.

Usage:
    collect_week.py [--week-offset N] [--date YYYY-MM-DD] [--single-day]
                    [--projects-dir PATH] [--max-prompts N]
                    [--head-snippets N] [--tail-snippets N] [--snippet-chars N]
                    [--no-dedup]
"""
import argparse
import glob
import json
import os
import re
import sys
from collections import defaultdict, deque
from datetime import datetime, timedelta

# --- message-content filtering -------------------------------------------------

# user text blocks that are harness/tooling noise, not real user intent
_NOISE_PREFIXES = (
    "<system-reminder", "<command-", "<local-command", "<bash-",
    "Caveat:", "[Request interrupted", "<user-memory", "<post-tool",
    "<task-notification",
)
# generic prompts that don't identify a thread (skipped when fingerprinting)
_GENERIC_PROMPTS = {
    "continue from where you left off.", "现在可以了吗？", "现在可以了吗",
    "好的", "好的，就这样", "好的就这样", "中文回答我", "翻译完了吗？",
    "进度如何，怎么看？", "好的，删除吧",
}
# tool_use names that indicate file work (used to collect files_touched)
_FILE_TOOLS = {"Edit", "Write", "NotebookEdit", "MultiEdit"}

# traceable links worth surfacing in the report (MR/PR, Notion, docs, dashboards)
_URL_RE = re.compile(r"https?://[^\s\)\]\}<>\"']+")
_LINK_HINTS = ("merge_request", "/pull/", "/-/", "notion.", "langfuse",
               "docs.", "confluence", "/issues/", "figma.", "feishu", "shimo")


def _extract_links(text):
    out = []
    for m in _URL_RE.findall(text or ""):
        url = m.rstrip(".,;*`_~")
        if "..." in url:  # elided placeholder, not a real link
            continue
        low = url.lower()
        if any(h in low for h in _LINK_HINTS):
            out.append(url)
    return out


def _iter_blocks(content):
    if isinstance(content, str):
        yield ("text", content)
        return
    if not isinstance(content, list):
        return
    for b in content:
        if not isinstance(b, dict):
            continue
        bt = b.get("type")
        if bt == "text":
            yield ("text", b.get("text", ""))
        elif bt == "tool_use":
            yield ("tool_use", b.get("name", ""))


def _clean_user_text(text):
    t = (text or "").strip()
    if not t:
        return None
    for p in _NOISE_PREFIXES:
        if t.startswith(p):
            return None
    return t


# Best-effort secret redaction. Session transcripts routinely contain API keys,
# tokens and passwords pasted by the user; we MUST NOT let them flow into the
# digest JSON (which may be saved, shared, or synced). High-confidence patterns
# only, to avoid mangling normal prose.
_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),               # OpenAI/OpenRouter/SiliconFlow
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),          # GitHub tokens
    re.compile(r"AKLT[A-Za-z0-9+/=_-]{10,}"),           # Volcengine AccessKeyID
    re.compile(r"AKIA[0-9A-Z]{12,}"),                   # AWS access key id
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),        # Slack tokens
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{6,}"),  # JWT
    # key/secret/password/token = <value>  (covers 密码：xxx, SecretAccessKey: xxx)
    re.compile(
        r"(?i)(pass(?:word|wd)?|密\s*码|secret(?:\s*access\s*key)?|access\s*key(?:\s*id)?|"
        r"api[_-]?key|token|bearer)\s*[:=：]\s*\S+"),
]


def _label_redact(m):
    """"<label><sep><value>" -> "<label><sep>[REDACTED]" (keep label, drop value)."""
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


def _file_path_from_tool(content, name):
    if not isinstance(content, list):
        return None
    for b in content:
        if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == name:
            inp = b.get("input") or {}
            fp = inp.get("file_path") or inp.get("notebook_path")
            if fp:
                return fp
    return None


def _fingerprint(user_prompts):
    """A stable key identifying the conversation thread a session belongs to.

    Forked windows share their first *substantive* user prompt; we normalize it
    and use it as the merge key. Falls back to None (no merge) when a session has
    only generic prompts.
    """
    for p in user_prompts:
        low = p.strip().lower()
        if low in _GENERIC_PROMPTS or len(low) < 8:
            continue
        norm = re.sub(r"\s+", " ", low)[:140]
        return norm
    return None


def _head_tail(items, head, tail):
    """First `head` + last `tail` items, de-duplicated, order preserved."""
    if len(items) <= head + tail:
        return list(items)
    seen, out = set(), []
    for x in items[:head] + items[-tail:]:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


# --- week boundary -------------------------------------------------------------

def week_bounds(anchor):
    monday = anchor - timedelta(days=anchor.weekday())
    start = monday.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=7) - timedelta(seconds=1)
    return start, end


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--week-offset", type=int, default=0)
    ap.add_argument("--date", default=None)
    ap.add_argument("--single-day", action="store_true",
                    help="collect only the anchor day (for daily reports)")
    ap.add_argument("--projects-dir",
                    default=os.path.expanduser("~/.claude/projects"))
    ap.add_argument("--max-prompts", type=int, default=16)
    ap.add_argument("--head-snippets", type=int, default=4)
    ap.add_argument("--tail-snippets", type=int, default=8)
    ap.add_argument("--snippet-chars", type=int, default=320)
    ap.add_argument("--no-dedup", action="store_true",
                    help="do not merge forked sessions")
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

    # (session_id, day) -> raw bucket; snippets kept as head list + tail deque
    raw = {}
    for path in glob.glob(os.path.join(args.projects_dir, "*", "*.jsonl")):
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(path), local_tz)
        except OSError:
            continue
        if mtime < start:
            continue
        with open(path, "r", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if o.get("type") not in ("user", "assistant"):
                    continue
                ts_raw = o.get("timestamp")
                if not ts_raw:
                    continue
                try:
                    ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                except ValueError:
                    continue
                ts_local = ts.astimezone(local_tz)
                if ts_local < start or ts_local > end:
                    continue

                day = ts_local.strftime("%Y-%m-%d")
                sid = o.get("sessionId") or os.path.basename(path)
                key = (sid, day)
                s = raw.get(key)
                if s is None:
                    s = raw[key] = {
                        "session_id": sid, "day": day, "cwd": o.get("cwd", ""),
                        "first_ts": ts_raw, "last_ts": ts_raw,
                        "user_prompts": [], "_seen_prompts": set(),
                        "head": [], "tail": deque(maxlen=args.tail_snippets),
                        "tool_activity": defaultdict(int), "files_touched": set(),
                        "links": set(),
                    }
                if not s["cwd"] and o.get("cwd"):
                    s["cwd"] = o["cwd"]
                if ts_raw < s["first_ts"]:
                    s["first_ts"] = ts_raw
                if ts_raw > s["last_ts"]:
                    s["last_ts"] = ts_raw

                msg = o.get("message", {})
                content = msg.get("content") if isinstance(msg, dict) else None
                if o["type"] == "user":
                    for bt, val in _iter_blocks(content):
                        if bt != "text":
                            continue
                        c = _clean_user_text(val)
                        if c and c not in s["_seen_prompts"]:
                            s["_seen_prompts"].add(c)
                            s["user_prompts"].append(
                                _redact(c[: args.snippet_chars * 3]))
                        s["links"].update(_extract_links(val))
                else:
                    for bt, val in _iter_blocks(content):
                        if bt == "tool_use" and val:
                            s["tool_activity"][val] += 1
                            if val in _FILE_TOOLS:
                                fp = _file_path_from_tool(content, val)
                                if fp:
                                    s["files_touched"].add(fp)
                        elif bt == "text":
                            t = (val or "").strip()
                            if t:
                                s["links"].update(_extract_links(t))
                                snip = _redact(t[: args.snippet_chars])
                                if len(s["head"]) < args.head_snippets:
                                    s["head"].append(snip)
                                s["tail"].append(snip)

    # collapse each session bucket; head + tail (tail wins for conclusions)
    def finalize(bucket_list):
        sessions = sorted(bucket_list, key=lambda b: b["first_ts"])
        prompts, pseen = [], set()
        snips, sseen = [], set()
        tools = defaultdict(int)
        files = set()
        links = set()
        sids = []
        for b in sessions:
            sids.append(b["session_id"])
            links |= b["links"]
            for p in b["user_prompts"]:
                if p not in pseen:
                    pseen.add(p)
                    prompts.append(p)
            combined = b["head"] + [x for x in b["tail"] if x not in b["head"]]
            for s in combined:
                if s not in sseen:
                    sseen.add(s)
                    snips.append(s)
            for k, v in b["tool_activity"].items():
                tools[k] += v
            files |= b["files_touched"]
        return {
            "session_count": len(sessions),
            "session_ids": sids,
            "cwd": sessions[0]["cwd"],
            "first_ts": sessions[0]["first_ts"],
            "last_ts": max(b["last_ts"] for b in sessions),
            "user_prompts": _head_tail(prompts, args.max_prompts // 2,
                                       args.max_prompts - args.max_prompts // 2),
            "assistant_snippets": _head_tail(snips, args.head_snippets,
                                             args.tail_snippets),
            "tool_activity": dict(sorted(tools.items(), key=lambda kv: -kv[1])),
            "files_touched": sorted(files)[:25],
            "links": sorted(links)[:15],
        }

    # group by day, then optionally merge forked sessions by fingerprint
    by_day = defaultdict(list)
    for b in raw.values():
        by_day[b["day"]].append(b)

    days = {}
    for day in sorted(by_day):
        buckets = by_day[day]
        if args.no_dedup:
            groups = [[b] for b in buckets]
        else:
            fp_groups = defaultdict(list)
            standalone = []
            for b in buckets:
                fp = _fingerprint(b["user_prompts"])
                if fp:
                    fp_groups[fp].append(b)
                else:
                    standalone.append(b)
            groups = list(fp_groups.values()) + [[b] for b in standalone]
        threads = [finalize(g) for g in groups]
        threads.sort(key=lambda t: t["first_ts"])
        days[day] = threads

    out = {
        "mode": "day" if args.single_day else "week",
        "week_start": start.strftime("%Y-%m-%d"),
        "week_end": end.strftime("%Y-%m-%d"),
        "timezone": str(local_tz),
        "generated_at": datetime.now(local_tz).isoformat(),
        "day_count": len(days),
        "thread_count": sum(len(v) for v in days.values()),
        "deduped": not args.no_dedup,
        "days": days,
    }
    json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
