#!/usr/bin/env python3
"""Deterministically pull ONE person's entries out of a multi-person team report.

The #1 failure when turning a week of *team* daily reports into a personal weekly
is 张冠李戴 — grabbing colleagues' items as yours. This script removes the guesswork:
it splits the report into name-led blocks and keeps ONLY the blocks whose leading
name(s) include the target person, grouped by date. The model then summarizes the
clean subset (no cross-person mixing possible).

Team-report structure assumed (示例用占位假名):
  20260530                      <- date header
  今日完成
  【模块 A】                      <- bracket section header (not a person)
  子方向标题                      <- Chinese sub-category header (not a person)
  Alice Wang 做了某事：...        <- person block starts (English name at line head)
    续写的子条 ...                <- continuation line, belongs to Alice Wang
  Bob Chen Carol Li 联合做了某事 ...   <- collaboration block (2 owners)
  bob.chen: 另一件事 ...          <- handle-style owner

Rules:
  * A block STARTS at a line whose head is a name-run: ≥2 capitalized ASCII tokens
    (e.g. "Alice Wang", "Bob Chen Carol Li") OR a handle like "bob.chen".
  * The block's OWNERS are the names in that head-run; it's the target's iff the
    target's name appears as consecutive tokens in the run (or the handle matches).
  * The block runs until the next block-start or a header line.
  * Header lines (date / 【...】 / pure-Chinese category titles / "今日完成") never own content.
  * High precision by design: when unsure, exclude. 宁漏不错 (better to drop than misattribute).

Usage:
  extract_person.py --name "Your Name" [--name 中文名] [--name handle] \
                    [--file report.txt]      # else reads stdin
Output: the target's blocks, grouped by date, as text (feed to the weekly prompt).
"""
import argparse
import re
import sys

_DATE = re.compile(r"^\s*20\d{6}\s*$")
_BRACKET = re.compile(r"^\s*[【\[]")
_SECTION_WORDS = ("今日完成", "本周完成", "—————")
# leading run of capitalized ASCII name tokens, then the rest (content)
_NAME_RUN = re.compile(r"^\s*([A-Z][A-Za-z.\-]*(?:\s+[A-Z][A-Za-z.\-]*)+)\b")
# handle style at line head: alice.wang  /  bob.chen
_HANDLE = re.compile(r"^\s*([a-z][a-z0-9]+\.[a-z][a-z0-9.]+)\s*[:：]?")


def _is_header(line):
    s = line.strip()
    if not s:
        return False
    if _DATE.match(s) or _BRACKET.match(s):
        return True
    if any(w in s for w in _SECTION_WORDS):
        return True
    # pure-Chinese category title (no ASCII letters, short-ish), e.g. 个性化数据预测
    if not re.search(r"[A-Za-z]", s) and len(s) <= 24:
        return True
    return False


def _block_owners(line):
    """Return the list of owner-name strings if this line starts a person block, else None."""
    m = _NAME_RUN.match(line)
    if m:
        run = m.group(1)
        # split the run into individual names (pairs of Capitalized tokens, greedily)
        toks = run.split()
        return run, toks
    h = _HANDLE.match(line)
    if h:
        return h.group(1), [h.group(1)]
    return None


def _matches_target(run, toks, aliases_low):
    run_low = run.lower()
    # direct substring (handles full-name aliases like "alice wang")
    for a in aliases_low:
        if a in run_low:
            return True
    # consecutive-token match (e.g. target "carol li" within "bob chen carol li")
    tl = [t.lower() for t in toks]
    for a in aliases_low:
        parts = a.split()
        if len(parts) >= 2:
            for i in range(len(tl) - len(parts) + 1):
                if tl[i:i + len(parts)] == parts:
                    return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", action="append", required=True,
                    help="target name/alias (repeatable)")
    ap.add_argument("--file", default=None)
    args = ap.parse_args()
    aliases_low = [a.strip().lower() for a in args.name if a.strip()]

    text = open(args.file, errors="replace").read() if args.file else sys.stdin.read()
    lines = text.splitlines()

    out_by_date = {}          # date -> list of lines
    order = []                # preserve date order
    cur_date = "(未标日期)"
    capturing = False

    for line in lines:
        if not line.strip():
            if capturing:
                out_by_date.setdefault(cur_date, []).append(line.rstrip())
            continue
        if _DATE.match(line.strip()):
            cur_date = line.strip()
            capturing = False
            continue
        if _is_header(line):
            capturing = False
            continue
        owners = _block_owners(line)
        if owners is not None:                    # a new person block starts here
            run, toks = owners
            capturing = _matches_target(run, toks, aliases_low)
            if capturing:
                if cur_date not in out_by_date:
                    order.append(cur_date)
                out_by_date.setdefault(cur_date, []).append(line.rstrip())
            continue
        # continuation / sub-line: belongs to current owner
        if capturing:
            out_by_date.setdefault(cur_date, []).append(line.rstrip())

    if not out_by_date:
        sys.stderr.write("（未抽到目标人物的任何条目，请检查 --name 是否与报告里的写法一致）\n")
        return
    for d in order:
        block = [l for l in out_by_date[d] if l.strip()]
        if not block:
            continue
        print(f"===== {d} =====")
        print("\n".join(block))
        print()


if __name__ == "__main__":
    main()
