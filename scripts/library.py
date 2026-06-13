#!/usr/bin/env python3
"""Manage an Expression Spark evidence library using only Python stdlib."""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 1
SKILL_ROOT = Path(__file__).resolve().parents[1]
ASSETS_DIR = SKILL_ROOT / "assets"
SIGNAL_STATUSES = {"tentative", "recurring", "confirmed", "contradicted", "retired"}
SIGNAL_TYPES = {"voice", "value", "stance", "boundary", "tension", "business"}
MODES = {"deep-interviewer", "gentle-journal", "content-coach"}
TOPIC_STATUSES = {"unfilmed", "drafted", "filmed", "retired"}
REQUIRED_DIRS = ("sessions", "topics", "signals", "profile", "generated")
REQUIRED_FILES = ("config.md", "profile/current.md", "state.json")
STATE_CONTENT_KEYS = {"text", "claim", "summary", "fact_core", "tension", "audience", "angles", "content"}
QUOTE_BLOCK_RE = re.compile(
    r"<!-- quote:(?P<id>[^:]+):start -->.*?<!-- quote:(?P=id):end -->\n?",
    re.DOTALL,
)


class LibraryError(RuntimeError):
    """Expected validation or usage error."""


def iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def safe_slug(value: str) -> str:
    value = value.strip().replace(" ", "-")
    value = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", value, flags=re.UNICODE)
    value = re.sub(r"-+", "-", value).strip("-_")
    if not value:
        raise LibraryError("user slug cannot be empty")
    return value


def require_id(value: str, label: str) -> str:
    if not value or "/" in value or "\\" in value or value in {".", ".."}:
        raise LibraryError(f"invalid {label}: {value!r}")
    return value


def parse_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def dump_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise LibraryError(f"missing file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise LibraryError(f"invalid JSON in {path}: {exc}") from exc


def detect_obsidian_vault() -> Path | None:
    if not shutil.which("obsidian"):
        return None
    try:
        result = subprocess.run(
            ["obsidian", "eval", "code=app.vault.adapter.basePath"],
            check=True,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    output = result.stdout.strip()
    if "=>" in output:
        output = output.split("=>", 1)[1].strip()
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError:
        parsed = output.strip('"')
    path = Path(str(parsed)).expanduser()
    return path.resolve() if path.exists() else None


class LibraryStore:
    def __init__(self, root: Path, backend: str = "filesystem", vault_root: Path | None = None):
        self.root = root.expanduser().resolve()
        self.backend = backend
        self.vault_root = vault_root.resolve() if vault_root else None

    def absolute(self, relative: str | Path) -> Path:
        candidate = (self.root / relative).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise LibraryError(f"path escapes library root: {relative}") from exc
        return candidate

    def relative_to_vault(self, path: Path) -> str | None:
        if not self.vault_root:
            return None
        try:
            return path.resolve().relative_to(self.vault_root).as_posix()
        except ValueError:
            return None

    def write_text(self, relative: str | Path, content: str) -> None:
        path = self.absolute(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        if self.backend == "obsidian" and path.suffix == ".md":
            vault_relative = self.relative_to_vault(path)
            if vault_relative and shutil.which("obsidian"):
                try:
                    subprocess.run(
                        [
                            "obsidian",
                            "create",
                            f"path={vault_relative}",
                            f"content={content}",
                            "silent",
                            "overwrite",
                        ],
                        check=True,
                        capture_output=True,
                        text=True,
                        timeout=20,
                    )
                    return
                except (OSError, subprocess.SubprocessError) as exc:
                    print(f"warning: obsidian write failed, using filesystem fallback: {exc}", file=sys.stderr)
        path.write_text(content, encoding="utf-8")

    def remove(self, relative: str | Path) -> None:
        path = self.absolute(relative)
        if not path.exists():
            return
        if self.backend == "obsidian" and path.suffix == ".md":
            vault_relative = self.relative_to_vault(path)
            if vault_relative and shutil.which("obsidian"):
                try:
                    subprocess.run(
                        ["obsidian", "delete", f"path={vault_relative}"],
                        check=True,
                        capture_output=True,
                        text=True,
                        timeout=20,
                    )
                    return
                except (OSError, subprocess.SubprocessError) as exc:
                    print(f"warning: obsidian delete failed, using filesystem fallback: {exc}", file=sys.stderr)
        path.unlink(missing_ok=True)

    def read_text(self, relative: str | Path) -> str:
        return self.absolute(relative).read_text(encoding="utf-8")

    def write_state(self, state: dict[str, Any]) -> None:
        self.write_text("state.json", dump_json(state))


def choose_init_store(args: argparse.Namespace) -> LibraryStore:
    requested_backend = args.backend
    vault_root = detect_obsidian_vault() if requested_backend in {"auto", "obsidian"} else None
    if args.root:
        root = Path(args.root).expanduser().resolve()
        backend = "filesystem"
        if requested_backend == "obsidian":
            if not vault_root:
                raise LibraryError("Obsidian backend requested, but no active Obsidian vault was detected")
            try:
                root.relative_to(vault_root)
            except ValueError as exc:
                raise LibraryError("--root must be inside the active Obsidian vault for obsidian backend") from exc
            backend = "obsidian"
        return LibraryStore(root, backend, vault_root)
    if vault_root:
        return LibraryStore(vault_root / "表达资产" / safe_slug(args.user_slug), "obsidian", vault_root)
    if requested_backend == "obsidian":
        raise LibraryError("Obsidian backend requested, but no active Obsidian vault was detected")
    return LibraryStore(Path.home() / "expression-library" / safe_slug(args.user_slug), "filesystem")


def load_store(library: str) -> tuple[LibraryStore, dict[str, Any]]:
    root = Path(library).expanduser().resolve()
    state = load_json(root / "state.json")
    backend = state.get("settings", {}).get("backend", "filesystem")
    vault_root = detect_obsidian_vault() if backend == "obsidian" else None
    return LibraryStore(root, backend, vault_root), state


def render_template(name: str, values: dict[str, Any]) -> str:
    path = ASSETS_DIR / name
    text = path.read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", str(value))
    unresolved = re.findall(r"\{\{[^}]+\}\}", text)
    if unresolved:
        raise LibraryError(f"unresolved template values in {name}: {', '.join(unresolved)}")
    return text


def new_state(slug: str, name: str, default_mode: str, backend: str) -> dict[str, Any]:
    state = {
        "schema_version": SCHEMA_VERSION,
        "created_at": iso_now(),
        "updated_at": iso_now(),
        "user": {"slug": slug, "name": name},
        "settings": {"default_mode": default_mode, "backend": backend},
        "records": {"sessions": {}, "quotes": {}, "topics": {}, "signals": {}},
        "persona": {
            "last_generated_at": None,
            "last_generated_quote_count": 0,
            "path": None,
            "business_changed": False,
        },
        "stats": {},
    }
    state["stats"] = compute_stats(state)
    return state


def config_markdown(args: argparse.Namespace, store: LibraryStore) -> str:
    domains = parse_csv(args.domains)
    domain_lines = "\n".join(f"- {item}" for item in domains) or "- 待补充"
    return f"""---
user_slug: "{safe_slug(args.user_slug)}"
name: "{args.name}"
default_mode: "{args.default_mode}"
backend: "{store.backend}"
tags:
  - expression/config
---

# Expression Spark 配置

## 当前业务

{args.business or "待补充"}

## 常聊领域

{domain_lines}

## 隐私与保存规则

- 只保存用户审阅并确认后的精选原话和派生资产。
- 不保存完整聊天记录。
- 用户可以要求排除、预览遗忘影响范围，并在再次确认后删除。
- 原话是源数据；画像、选题与 Persona 都可以重建。
"""


def initial_profile_markdown(name: str) -> str:
    return f"""---
generated: true
tags:
  - expression/profile
---

# {name} · 当前画像

这是从已确认原话重建的派生视图。当前还没有足够证据形成稳定判断。
"""


def update_config_default_mode(store: LibraryStore, mode: str) -> None:
    text = store.read_text("config.md")
    updated, replacements = re.subn(
        r'^default_mode:\s*".*?"\s*$',
        f'default_mode: "{mode}"',
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if replacements != 1:
        raise LibraryError("config.md is missing default_mode frontmatter")
    store.write_text("config.md", updated)


def cmd_init(args: argparse.Namespace) -> int:
    if args.default_mode not in MODES:
        raise LibraryError(f"invalid mode: {args.default_mode}")
    store = choose_init_store(args)
    if (store.root / "state.json").exists():
        raise LibraryError(f"library already exists: {store.root}")
    for directory in REQUIRED_DIRS:
        (store.root / directory).mkdir(parents=True, exist_ok=True)
    slug = safe_slug(args.user_slug)
    state = new_state(slug, args.name, args.default_mode, store.backend)
    store.write_text("config.md", config_markdown(args, store))
    store.write_text("profile/current.md", initial_profile_markdown(args.name))
    store.write_state(state)
    print(
        dump_json(
            {
                "ok": True,
                "library": str(store.root),
                "backend": store.backend,
                "privacy": "Only confirmed excerpts are stored; full chat transcripts are not stored.",
            }
        ),
        end="",
    )
    return 0


def normalized_session(payload: dict[str, Any]) -> dict[str, Any]:
    session = copy.deepcopy(payload.get("session") or {})
    session_date = str(session.get("date") or date.today().isoformat())
    session_id = session.get("id") or f"{session_date}-{uuid.uuid4().hex[:8]}"
    session["id"] = require_id(str(session_id), "session id")
    session["date"] = session_date
    session["mode"] = session.get("mode") or "deep-interviewer"
    if session["mode"] not in MODES:
        raise LibraryError(f"invalid session mode: {session['mode']}")
    session["summary"] = str(session.get("summary") or "本次保存了经用户确认的精选表达。").strip()
    if len(session["summary"]) > 600:
        raise LibraryError("session summary exceeds 600 characters; save selected quotes, not a full transcript")
    session["themes"] = [str(item).strip() for item in session.get("themes", []) if str(item).strip()]
    return session


def normalized_quotes(payload: dict[str, Any], session: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, original in enumerate(payload.get("quotes") or [], start=1):
        item = copy.deepcopy(original)
        quote_id = item.get("id") or f"q-{session['id']}-{index:02d}"
        item["id"] = require_id(str(quote_id), "quote id")
        item["text"] = str(item.get("text") or "").strip()
        if not item["text"]:
            raise LibraryError(f"quote {item['id']} has empty text")
        if item.get("do_not_quote"):
            raise LibraryError(f"quote {item['id']} is marked do_not_quote and cannot be registered")
        item["theme"] = str(item.get("theme") or (session["themes"][0] if session["themes"] else "")).strip()
        item["source_turn"] = str(item.get("source_turn") or "").strip()
        item["story_or_decision"] = bool(item.get("story_or_decision", False))
        result.append(item)
    if not result:
        raise LibraryError("register requires at least one confirmed quote")
    ids = [item["id"] for item in result]
    if len(ids) != len(set(ids)):
        raise LibraryError("duplicate quote ids in payload")
    return result


def normalized_topics(payload: dict[str, Any], session: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for index, original in enumerate(payload.get("topics") or [], start=1):
        item = copy.deepcopy(original)
        item["id"] = require_id(str(item.get("id") or f"topic-{session['id']}-{index:02d}"), "topic id")
        item["title"] = str(item.get("title") or item["id"]).strip()
        item["fact_core"] = str(item.get("fact_core") or "").strip()
        item["tension"] = str(item.get("tension") or "").strip()
        item["audience"] = str(item.get("audience") or "").strip()
        item["angles"] = [str(value).strip() for value in item.get("angles", []) if str(value).strip()]
        item["theme"] = str(item.get("theme") or (session["themes"][0] if session["themes"] else "")).strip()
        item["status"] = str(item.get("status") or "unfilmed")
        if item["status"] not in TOPIC_STATUSES:
            raise LibraryError(f"invalid topic status for {item['id']}: {item['status']}")
        item["quote_ids"] = [str(value) for value in item.get("quote_ids", [])]
        if not item["quote_ids"]:
            raise LibraryError(f"topic {item['id']} must reference at least one quote")
        result.append(item)
    return result


def normalized_signals(payload: dict[str, Any], session: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for index, original in enumerate(payload.get("signals") or [], start=1):
        item = copy.deepcopy(original)
        item["id"] = require_id(str(item.get("id") or f"signal-{session['id']}-{index:02d}"), "signal id")
        item["type"] = str(item.get("type") or "stance")
        if item["type"] not in SIGNAL_TYPES:
            raise LibraryError(f"invalid signal type for {item['id']}: {item['type']}")
        item["claim"] = str(item.get("claim") or "").strip()
        if not item["claim"]:
            raise LibraryError(f"signal {item['id']} requires a claim")
        item["status"] = str(item.get("status") or "tentative")
        if item["status"] not in SIGNAL_STATUSES:
            raise LibraryError(f"invalid signal status for {item['id']}: {item['status']}")
        item["confidence"] = float(item.get("confidence", 0.35))
        if not 0 <= item["confidence"] <= 1:
            raise LibraryError(f"signal {item['id']} confidence must be between 0 and 1")
        item["theme"] = str(item.get("theme") or (session["themes"][0] if session["themes"] else "")).strip()
        item["evidence_quote_ids"] = [str(value) for value in item.get("evidence_quote_ids", [])]
        if not item["evidence_quote_ids"]:
            raise LibraryError(f"signal {item['id']} must reference at least one quote")
        contradicts = item.get("contradicts", [])
        if isinstance(contradicts, str):
            contradicts = [contradicts]
        item["contradicts"] = [str(value) for value in contradicts]
        item["user_confirmed"] = bool(item.get("user_confirmed", False))
        if item["status"] in {"confirmed", "retired"} and not item["user_confirmed"]:
            raise LibraryError(f"signal {item['id']} status {item['status']} requires user_confirmed: true")
        if item["status"] == "contradicted" and not item["contradicts"]:
            raise LibraryError(f"contradicted signal {item['id']} must name the signal it contradicts")
        result.append(item)
    return result


def quote_block(quote: dict[str, Any], index: int) -> str:
    quoted = "\n".join(f"> {line}" if line else ">" for line in quote["text"].splitlines())
    metadata = [f"- quote_id: `{quote['id']}`"]
    if quote["theme"]:
        metadata.append(f"- theme: {quote['theme']}")
    if quote["source_turn"]:
        metadata.append(f"- source_turn: {quote['source_turn']}")
    if quote["story_or_decision"]:
        metadata.append("- story_or_decision: true")
    return (
        f"### 原话 {index} · {quote['id']}\n\n"
        f"<!-- quote:{quote['id']}:start -->\n"
        f"{quoted}\n\n"
        + "\n".join(metadata)
        + f"\n<!-- quote:{quote['id']}:end -->"
    )


def evidence_lines(quote_ids: Iterable[str], state: dict[str, Any]) -> str:
    lines = []
    quotes = state["records"]["quotes"]
    for quote_id in quote_ids:
        record = quotes.get(quote_id)
        if not record:
            raise LibraryError(f"unknown quote evidence: {quote_id}")
        lines.append(f"- quote_id: `{quote_id}` · [[{record['path']}|来源会话]]")
    return "\n".join(lines) or "- 无"


def status_reason(signal: dict[str, Any], evidence_session_count: int) -> str:
    custom = str(signal.get("status_reason") or "").strip()
    if custom:
        return custom
    status = signal["status"]
    reasons = {
        "tentative": "当前证据不足，只作为可被推翻的暂定观察。",
        "recurring": f"该模式已在 {evidence_session_count} 次不同会话中重复出现。",
        "confirmed": "用户已明确认领此价值观或立场。",
        "contradicted": "新证据与已有画像冲突，保留两边证据，不覆盖旧判断。",
        "retired": "用户已明确确认此判断不再适用。",
    }
    return reasons[status]


def extract_section(text: str, heading: str) -> str:
    pattern = re.compile(rf"^## {re.escape(heading)}\s*$\n+(.*?)(?=^## |\Z)", re.MULTILINE | re.DOTALL)
    match = pattern.search(text)
    return match.group(1).strip() if match else ""


def format_list(items: Iterable[str], fallback: str = "- 无") -> str:
    values = [str(item).strip() for item in items if str(item).strip()]
    return "\n".join(f"- {item}" for item in values) if values else fallback


def update_stats(state: dict[str, Any]) -> None:
    state["stats"] = compute_stats(state)
    state["updated_at"] = iso_now()


def compute_stats(state: dict[str, Any]) -> dict[str, Any]:
    records = state.get("records", {})
    sessions = records.get("sessions", {})
    quotes = records.get("quotes", {})
    topics = records.get("topics", {})
    signals = records.get("signals", {})
    themes = {
        theme
        for topic in topics.values()
        for theme in [str(topic.get("theme") or "").strip()]
        if theme
    }
    for session in sessions.values():
        themes.update(str(item).strip() for item in session.get("themes", []) if str(item).strip())
    story_count = sum(1 for quote in quotes.values() if quote.get("story_or_decision"))
    recurring_voice = sum(
        1
        for signal in signals.values()
        if signal.get("type") == "voice"
        and signal.get("status") in {"recurring", "confirmed"}
        and len(set(signal.get("evidence_session_ids", []))) >= 3
    )
    confirmed_values_stances = sum(
        1
        for signal in signals.values()
        if signal.get("type") in {"value", "stance"}
        and signal.get("status") == "confirmed"
        and signal.get("user_confirmed")
    )
    confirmed_contradictions = sum(
        1
        for signal in signals.values()
        if signal.get("status") == "contradicted" and signal.get("user_confirmed")
    )
    preview_checks = {
        "sessions": len(sessions) >= 2,
        "quotes": len(quotes) >= 12,
        "topics": len(topics) >= 3,
    }
    persona_checks = {
        "sessions": len(sessions) >= 6,
        "quotes": len(quotes) >= 30,
        "themes": len(themes) >= 3,
        "stories_or_decisions": story_count >= 5,
        "recurring_voice_patterns": recurring_voice >= 3,
        "confirmed_values_or_stances": confirmed_values_stances >= 3,
    }
    persona = state.get("persona", {})
    last_count = int(persona.get("last_generated_quote_count") or 0)
    quotes_since_persona = max(0, len(quotes) - last_count) if persona.get("last_generated_at") else 0
    update_due = bool(
        persona.get("last_generated_at")
        and (
            quotes_since_persona >= 15
            or confirmed_contradictions > 0
            or persona.get("business_changed", False)
        )
    )
    return {
        "sessions": len(sessions),
        "quotes": len(quotes),
        "topics": len(topics),
        "signals": len(signals),
        "themes": sorted(themes),
        "stories_or_decisions": story_count,
        "recurring_voice_patterns": recurring_voice,
        "confirmed_values_or_stances": confirmed_values_stances,
        "confirmed_contradictions": confirmed_contradictions,
        "voice_preview": {"ready": all(preview_checks.values()), "checks": preview_checks},
        "stable_persona": {"ready": all(persona_checks.values()), "checks": persona_checks},
        "persona_update": {"due": update_due, "quotes_since_persona": quotes_since_persona},
    }


def rebuild_profile(store: LibraryStore, state: dict[str, Any]) -> None:
    groups: dict[str, list[str]] = {status: [] for status in SIGNAL_STATUSES}
    for signal_id, record in sorted(state["records"]["signals"].items()):
        try:
            signal_text = store.read_text(record["path"])
        except FileNotFoundError:
            continue
        claim = extract_section(signal_text, "画像判断") or signal_id
        evidence_count = len(record.get("evidence_session_ids", []))
        groups[record["status"]].append(
            f"- **{claim}** · [[{record['path']}|证据]] · {evidence_count} 次会话"
        )
    labels = {
        "confirmed": "用户已确认",
        "recurring": "跨会话重复出现",
        "tentative": "暂定观察",
        "contradicted": "矛盾与张力",
        "retired": "已不再适用",
    }
    sections = []
    for status in ("confirmed", "recurring", "tentative", "contradicted", "retired"):
        sections.append(f"## {labels[status]}\n\n" + ("\n".join(groups[status]) if groups[status] else "- 无"))
    stats = compute_stats(state)
    text = f"""---
generated: true
updated: "{iso_now()}"
tags:
  - expression/profile
---

# {state['user']['name']} · 当前画像

这是从已确认原话重建的派生视图。原话拥有最高优先级，矛盾不会被自动覆盖。

## 证据概览

- 已确认会话：{stats['sessions']}
- 精选原话：{stats['quotes']}
- 选题卡：{stats['topics']}
- 覆盖主题：{len(stats['themes'])}

{chr(10).join(sections)}
"""
    store.write_text("profile/current.md", text)


def apply_persona_generation(state: dict[str, Any], generation: dict[str, Any]) -> None:
    if not generation.get("user_confirmed"):
        raise LibraryError("persona_generation requires user_confirmed: true")
    path = str(generation.get("path") or "").strip()
    if not path:
        raise LibraryError("persona_generation requires path")
    state["persona"]["last_generated_at"] = generation.get("generated_at") or iso_now()
    state["persona"]["last_generated_quote_count"] = len(state["records"]["quotes"])
    state["persona"]["path"] = path
    state["persona"]["business_changed"] = False


def register_session(store: LibraryStore, state: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    session = normalized_session(payload)
    if session["id"] in state["records"]["sessions"]:
        raise LibraryError(f"session already exists: {session['id']}")
    quotes = normalized_quotes(payload, session)
    topics = normalized_topics(payload, session)
    signals = normalized_signals(payload, session)
    records = state["records"]
    existing_quote_ids = set(records["quotes"])
    incoming_quote_ids = {quote["id"] for quote in quotes}
    overlap = existing_quote_ids & incoming_quote_ids
    if overlap:
        raise LibraryError(f"quote ids already exist: {', '.join(sorted(overlap))}")
    all_quote_ids = existing_quote_ids | incoming_quote_ids
    existing_session_for_quote = {
        quote_id: record["session_id"] for quote_id, record in records["quotes"].items()
    }
    incoming_session_for_quote = {quote["id"]: session["id"] for quote in quotes}
    for topic in topics:
        unknown = set(topic["quote_ids"]) - all_quote_ids
        if unknown:
            raise LibraryError(f"topic {topic['id']} references unknown quotes: {', '.join(sorted(unknown))}")
        if topic["id"] in records["topics"]:
            raise LibraryError(f"topic already exists: {topic['id']}")
    for signal in signals:
        unknown = set(signal["evidence_quote_ids"]) - all_quote_ids
        if unknown:
            raise LibraryError(f"signal {signal['id']} references unknown quotes: {', '.join(sorted(unknown))}")
        existing = records["signals"].get(signal["id"], {})
        if existing and existing.get("type") != signal["type"]:
            raise LibraryError(
                f"signal {signal['id']} cannot change type from {existing.get('type')} to {signal['type']}"
            )
        if existing and existing.get("status") == "confirmed":
            old_claim = extract_section(store.read_text(existing["path"]), "画像判断")
            if old_claim and old_claim != signal["claim"] and not signal["user_confirmed"]:
                raise LibraryError(
                    f"confirmed signal {signal['id']} cannot change claim without user_confirmed: true"
                )
        signal["contradicts"] = list(
            dict.fromkeys(existing.get("contradicts", []) + signal["contradicts"])
        )
        merged_quote_ids = list(dict.fromkeys(existing.get("evidence_quote_ids", []) + signal["evidence_quote_ids"]))
        evidence_session_ids = {
            existing_session_for_quote.get(quote_id) or incoming_session_for_quote.get(quote_id)
            for quote_id in merged_quote_ids
        }
        evidence_session_ids.discard(None)
        incoming_status = signal["status"]
        if existing.get("status") == "confirmed" and incoming_status not in {"confirmed", "retired"}:
            incoming_status = "confirmed"
        if existing.get("status") == "recurring" and incoming_status == "tentative":
            incoming_status = "recurring"
        if incoming_status == "recurring" and len(evidence_session_ids) < 3:
            raise LibraryError(
                f"signal {signal['id']} cannot be recurring with evidence from only "
                f"{len(evidence_session_ids)} session(s)"
            )
    incoming_signal_ids = {signal["id"] for signal in signals}
    known_signal_ids = set(records["signals"]) | incoming_signal_ids
    for signal in signals:
        unknown = set(signal["contradicts"]) - known_signal_ids
        if unknown:
            raise LibraryError(f"signal {signal['id']} contradicts unknown signals: {', '.join(sorted(unknown))}")

    session_path = f"sessions/{session['date'][:4]}/{session['date'][5:7]}/{session['id']}.md"
    for quote in quotes:
        records["quotes"][quote["id"]] = {
            "id": quote["id"],
            "path": session_path,
            "session_id": session["id"],
            "theme": quote["theme"],
            "source_turn": quote["source_turn"],
            "story_or_decision": quote["story_or_decision"],
            "created_at": iso_now(),
        }

    for topic in topics:
        topic_path = f"topics/{topic['id']}.md"
        topic_text = render_template(
            "topic-template.md",
            {
                "topic_id": topic["id"],
                "date": session["date"],
                "theme": topic["theme"],
                "status": topic["status"],
                "session_id": session["id"],
                "title": topic["title"],
                "fact_core": topic["fact_core"] or "待补充",
                "tension": topic["tension"] or "待补充",
                "audience": topic["audience"] or "待补充",
                "angles": format_list(topic["angles"]),
                "evidence": evidence_lines(topic["quote_ids"], state),
            },
        )
        store.write_text(topic_path, topic_text)
        records["topics"][topic["id"]] = {
            "id": topic["id"],
            "path": topic_path,
            "status": topic["status"],
            "session_id": session["id"],
            "theme": topic["theme"],
            "quote_ids": topic["quote_ids"],
            "created_at": iso_now(),
        }

    for signal in signals:
        existing = records["signals"].get(signal["id"], {})
        merged_quote_ids = list(dict.fromkeys(existing.get("evidence_quote_ids", []) + signal["evidence_quote_ids"]))
        evidence_session_ids = sorted(
            {
                records["quotes"][quote_id]["session_id"]
                for quote_id in merged_quote_ids
                if quote_id in records["quotes"]
            }
        )
        incoming_status = signal["status"]
        existing_status = existing.get("status")
        if existing_status == "confirmed" and incoming_status not in {"confirmed", "retired"}:
            incoming_status = "confirmed"
        if existing_status == "recurring" and incoming_status == "tentative":
            incoming_status = "recurring"
        if incoming_status == "recurring" and len(evidence_session_ids) < 3:
            raise LibraryError(
                f"signal {signal['id']} cannot be recurring with evidence from only "
                f"{len(evidence_session_ids)} session(s)"
            )
        signal["status"] = incoming_status
        signal_path = f"signals/{signal['id']}.md"
        signal_text = render_template(
            "signal-template.md",
            {
                "signal_id": signal["id"],
                "signal_type": signal["type"],
                "status": signal["status"],
                "confidence": signal["confidence"],
                "theme": signal["theme"],
                "source_date": session["date"],
                "updated": iso_now(),
                "claim": signal["claim"],
                "status_reason": status_reason(signal, len(evidence_session_ids)),
                "evidence": evidence_lines(merged_quote_ids, state),
                "source_sessions": format_list(evidence_session_ids),
                "contradiction": format_list(signal["contradicts"]),
            },
        )
        store.write_text(signal_path, signal_text)
        records["signals"][signal["id"]] = {
            "id": signal["id"],
            "path": signal_path,
            "type": signal["type"],
            "status": signal["status"],
            "theme": signal["theme"],
            "evidence_quote_ids": merged_quote_ids,
            "evidence_session_ids": evidence_session_ids,
            "user_confirmed": bool(existing.get("user_confirmed") or signal["user_confirmed"]),
            "contradicts": signal["contradicts"],
            "updated_at": iso_now(),
        }

    session_text = render_template(
        "session-template.md",
        {
            "session_id": session["id"],
            "date": session["date"],
            "mode": session["mode"],
            "themes_json": json.dumps(session["themes"], ensure_ascii=False),
            "summary": session["summary"],
            "quote_blocks": "\n\n".join(quote_block(quote, index) for index, quote in enumerate(quotes, start=1)),
            "topic_links": format_list(f"[[topics/{topic['id']}|{topic['title']}]]" for topic in topics),
            "signal_links": format_list(f"[[signals/{signal['id']}|{signal['id']}]]" for signal in signals),
            "next_threads": format_list(payload.get("next_threads") or []),
        },
    )
    store.write_text(session_path, session_text)
    records["sessions"][session["id"]] = {
        "id": session["id"],
        "path": session_path,
        "date": session["date"],
        "mode": session["mode"],
        "themes": session["themes"],
        "quote_ids": [quote["id"] for quote in quotes],
        "topic_ids": [topic["id"] for topic in topics],
        "signal_ids": [signal["id"] for signal in signals],
        "created_at": iso_now(),
    }
    return {
        "session_id": session["id"],
        "session_path": session_path,
        "quotes_registered": len(quotes),
        "topics_registered": len(topics),
        "signals_registered": len(signals),
    }


def cmd_register(args: argparse.Namespace) -> int:
    store, state = load_store(args.library)
    payload = load_json(Path(args.payload).expanduser().resolve())
    if payload.get("confirmed") is not True:
        raise LibraryError("register refused: payload must contain confirmed: true after user review")
    mode_to_update: str | None = None
    if payload.get("update_default_mode"):
        mode_to_update = str(payload.get("default_mode") or payload.get("session", {}).get("mode") or "")
        if mode_to_update not in MODES:
            raise LibraryError("update_default_mode requires a valid default_mode")
    generation = payload.get("persona_generation")
    if generation:
        if not generation.get("user_confirmed"):
            raise LibraryError("persona_generation requires user_confirmed: true")
        generation_path = str(generation.get("path") or "").strip()
        if not generation_path:
            raise LibraryError("persona_generation requires path")
        if not generation_path.startswith("generated/"):
            raise LibraryError("persona_generation path must be inside generated/")
        if not store.absolute(generation_path).is_file():
            raise LibraryError("persona_generation path must exist before it is registered")
    result: dict[str, Any] = {}
    if payload.get("session"):
        result.update(register_session(store, state, payload))
    elif not generation:
        raise LibraryError("register requires a session or persona_generation")
    if mode_to_update:
        state["settings"]["default_mode"] = mode_to_update
        update_config_default_mode(store, mode_to_update)
        result["default_mode_updated"] = mode_to_update
    if payload.get("business_changed"):
        state["persona"]["business_changed"] = True
    if generation:
        apply_persona_generation(state, generation)
        result["persona_generation_registered"] = True
    update_stats(state)
    rebuild_profile(store, state)
    store.write_state(state)
    result["status"] = state["stats"]
    print(dump_json({"ok": True, **result}), end="")
    return 0


def status_markdown(store: LibraryStore, state: dict[str, Any]) -> str:
    stats = compute_stats(state)
    preview = "ready" if stats["voice_preview"]["ready"] else "not ready"
    persona = "ready" if stats["stable_persona"]["ready"] else "not ready"
    update = "due" if stats["persona_update"]["due"] else "not due"
    return f"""# Expression Spark status

- Library: {store.root}
- Backend: {store.backend}
- Sessions: {stats['sessions']}
- Quotes: {stats['quotes']}
- Topics: {stats['topics']}
- Signals: {stats['signals']}
- Themes: {len(stats['themes'])}
- Stories or decisions: {stats['stories_or_decisions']}
- Recurring voice patterns: {stats['recurring_voice_patterns']}
- Confirmed values or stances: {stats['confirmed_values_or_stances']}
- Voice preview: {preview}
- Stable persona: {persona}
- Persona update: {update}
"""


def cmd_status(args: argparse.Namespace) -> int:
    store, state = load_store(args.library)
    stats = compute_stats(state)
    if args.json:
        print(dump_json({"library": str(store.root), "backend": store.backend, "stats": stats}), end="")
    else:
        print(status_markdown(store, state), end="")
    return 0


def score_text(text: str, query: str, themes: list[str]) -> int:
    lowered = text.casefold()
    score = 1 if not query and not themes else 0
    if query:
        query_lower = query.casefold().strip()
        if query_lower and query_lower in lowered:
            score += 6
        for term in query_lower.split():
            score += lowered.count(term)
    for theme in themes:
        if theme.casefold() in lowered:
            score += 4
    return score


def relevant_records(
    store: LibraryStore,
    records: dict[str, dict[str, Any]],
    query: str,
    themes: list[str],
    limit: int,
    allowed_statuses: set[str] | None = None,
) -> list[tuple[int, str, str]]:
    ranked = []
    for record_id, record in records.items():
        if allowed_statuses and record.get("status") not in allowed_statuses:
            continue
        try:
            text = store.read_text(record["path"])
        except FileNotFoundError:
            continue
        score = score_text(text, query, themes)
        if score > 0:
            ranked.append((score, record_id, text.strip()))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return ranked[:limit]


def cmd_context(args: argparse.Namespace) -> int:
    store, state = load_store(args.library)
    themes = args.theme or []
    profile = store.read_text("profile/current.md").strip()
    signals = relevant_records(
        store,
        state["records"]["signals"],
        args.query or "",
        themes,
        args.limit,
        {"confirmed", "recurring", "contradicted"},
    )
    topics = relevant_records(
        store,
        state["records"]["topics"],
        args.query or "",
        themes,
        args.limit,
        {"unfilmed", "drafted"},
    )
    sessions = relevant_records(
        store,
        state["records"]["sessions"],
        args.query or "",
        themes,
        args.limit,
    )
    chunks = [
        "# Expression Spark context",
        f"- Generated: {iso_now()}",
        f"- Library: {store.root}",
        f"- Query: {args.query or 'none'}",
        "",
        "## Current profile",
        "",
        profile,
        "",
        "## Relevant signals",
        "",
        "\n\n---\n\n".join(text for _, _, text in signals) or "- None",
        "",
        "## Relevant topic cards",
        "",
        "\n\n---\n\n".join(text for _, _, text in topics) or "- None",
        "",
        "## Source sessions with exact quotes",
        "",
        "\n\n---\n\n".join(text for _, _, text in sessions) or "- None",
        "",
        "> Treat exact quotes as source evidence. Do not invent experiences, numbers, clients, or positions.",
    ]
    output = "\n".join(chunks) + "\n"
    if args.output:
        Path(args.output).expanduser().resolve().write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    return 0


def walk_keys(value: Any, path: str = "") -> Iterable[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, item in value.items():
            current = f"{path}.{key}" if path else key
            yield current, item
            yield from walk_keys(item, current)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from walk_keys(item, f"{path}[{index}]")


def validation_report(store: LibraryStore, state: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    if state.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    for directory in REQUIRED_DIRS:
        if not store.absolute(directory).is_dir():
            errors.append(f"missing directory: {directory}")
    for filename in REQUIRED_FILES:
        if not store.absolute(filename).is_file():
            errors.append(f"missing file: {filename}")
    for key_path, _ in walk_keys(state):
        final_key = re.split(r"[.\[]", key_path)[-1].rstrip("]")
        if final_key in STATE_CONTENT_KEYS:
            errors.append(f"state.json contains prohibited corpus field: {key_path}")
    records = state.get("records", {})
    quotes = records.get("quotes", {})
    sessions = records.get("sessions", {})
    topics = records.get("topics", {})
    signals = records.get("signals", {})
    for group_name, group in (("sessions", sessions), ("quotes", quotes), ("topics", topics), ("signals", signals)):
        for record_id, record in group.items():
            relative = record.get("path")
            if not relative:
                errors.append(f"{group_name}.{record_id} has no path")
                continue
            try:
                path = store.absolute(relative)
            except LibraryError as exc:
                errors.append(str(exc))
                continue
            if not path.exists():
                errors.append(f"indexed path does not exist: {relative}")
    for quote_id, quote in quotes.items():
        if quote.get("session_id") not in sessions:
            errors.append(f"quote {quote_id} references missing session {quote.get('session_id')}")
    for topic_id, topic in topics.items():
        unknown = set(topic.get("quote_ids", [])) - set(quotes)
        if unknown:
            errors.append(f"topic {topic_id} references missing quotes: {', '.join(sorted(unknown))}")
    for signal_id, signal in signals.items():
        if signal.get("status") not in SIGNAL_STATUSES:
            errors.append(f"signal {signal_id} has invalid status {signal.get('status')}")
        unknown = set(signal.get("evidence_quote_ids", [])) - set(quotes)
        if unknown:
            errors.append(f"signal {signal_id} references missing quotes: {', '.join(sorted(unknown))}")
        if signal.get("status") == "recurring" and len(set(signal.get("evidence_session_ids", []))) < 3:
            errors.append(f"recurring signal {signal_id} has evidence from fewer than 3 sessions")
        if signal.get("status") in {"confirmed", "retired"} and not signal.get("user_confirmed"):
            errors.append(f"signal {signal_id} status {signal.get('status')} lacks user confirmation")
        unknown_contradictions = set(signal.get("contradicts", [])) - set(signals)
        if unknown_contradictions:
            errors.append(
                f"signal {signal_id} contradicts missing signals: {', '.join(sorted(unknown_contradictions))}"
            )
    computed = compute_stats(state)
    if state.get("stats") != computed:
        warnings.append("stored stats differ from computed stats; run register or forget to refresh")
    persona_path = state.get("persona", {}).get("path")
    if persona_path and not store.absolute(persona_path).exists():
        errors.append(f"indexed persona path does not exist: {persona_path}")
    return {"ok": not errors, "errors": errors, "warnings": warnings, "computed_stats": computed}


def cmd_validate(args: argparse.Namespace) -> int:
    store, state = load_store(args.library)
    report = validation_report(store, state)
    if args.json:
        print(dump_json(report), end="")
    else:
        print("PASS" if report["ok"] else "FAIL")
        for error in report["errors"]:
            print(f"ERROR: {error}")
        for warning in report["warnings"]:
            print(f"WARNING: {warning}")
    return 0 if report["ok"] else 1


def remove_quote_blocks(text: str, quote_ids: set[str]) -> str:
    def replace(match: re.Match[str]) -> str:
        return "" if match.group("id") in quote_ids else match.group(0)

    return QUOTE_BLOCK_RE.sub(replace, text)


def remove_lines_containing(text: str, identifiers: set[str]) -> str:
    if not identifiers:
        return text
    lines = []
    for line in text.splitlines():
        if any(identifier in line for identifier in identifiers):
            continue
        lines.append(line)
    return "\n".join(lines).rstrip() + "\n"


def replace_frontmatter_status(text: str, status: str) -> str:
    return re.sub(r'^status:\s*".*?"\s*$', f'status: "{status}"', text, count=1, flags=re.MULTILINE)


def find_forget_impact(state: dict[str, Any], store: LibraryStore, args: argparse.Namespace) -> dict[str, Any]:
    records = state["records"]
    sessions_to_delete = set(args.session_id or [])
    quotes_to_delete = set(args.quote_id or [])
    topics_to_delete = set(args.topic_id or [])
    signals_to_delete = set(args.signal_id or [])
    contains = (args.contains or "").casefold().strip()
    if contains:
        for session_id, record in records["sessions"].items():
            text = store.read_text(record["path"])
            matching_quote_ids = set()
            for match in QUOTE_BLOCK_RE.finditer(text):
                if contains in match.group(0).casefold():
                    matching_quote_ids.add(match.group("id"))
            quotes_to_delete.update(matching_quote_ids)
            remaining = remove_quote_blocks(text, matching_quote_ids)
            if contains in remaining.casefold():
                sessions_to_delete.add(session_id)
        for topic_id, record in records["topics"].items():
            if contains in store.read_text(record["path"]).casefold():
                topics_to_delete.add(topic_id)
        for signal_id, record in records["signals"].items():
            if contains in store.read_text(record["path"]).casefold():
                signals_to_delete.add(signal_id)
    unknown = {
        "sessions": sessions_to_delete - set(records["sessions"]),
        "quotes": quotes_to_delete - set(records["quotes"]),
        "topics": topics_to_delete - set(records["topics"]),
        "signals": signals_to_delete - set(records["signals"]),
    }
    unknown = {key: sorted(value) for key, value in unknown.items() if value}
    if unknown:
        raise LibraryError(f"unknown forget targets: {json.dumps(unknown, ensure_ascii=False)}")
    for session_id in list(sessions_to_delete):
        session = records["sessions"][session_id]
        quotes_to_delete.update(session.get("quote_ids", []))
        topics_to_delete.update(session.get("topic_ids", []))
    for session_id, session in records["sessions"].items():
        if set(session.get("quote_ids", [])) and set(session.get("quote_ids", [])) <= quotes_to_delete:
            sessions_to_delete.add(session_id)
    topics_to_update: dict[str, list[str]] = {}
    for topic_id, topic in records["topics"].items():
        if topic_id in topics_to_delete:
            continue
        remaining = [value for value in topic.get("quote_ids", []) if value not in quotes_to_delete]
        if remaining != topic.get("quote_ids", []):
            if remaining:
                topics_to_update[topic_id] = remaining
            else:
                topics_to_delete.add(topic_id)
    signals_to_update: dict[str, list[str]] = {}
    for signal_id, signal in records["signals"].items():
        if signal_id in signals_to_delete:
            continue
        remaining = [value for value in signal.get("evidence_quote_ids", []) if value not in quotes_to_delete]
        if remaining != signal.get("evidence_quote_ids", []):
            if remaining:
                signals_to_update[signal_id] = remaining
            else:
                signals_to_delete.add(signal_id)
    return {
        "sessions_to_delete": sorted(sessions_to_delete),
        "quotes_to_delete": sorted(quotes_to_delete),
        "topics_to_delete": sorted(topics_to_delete),
        "signals_to_delete": sorted(signals_to_delete),
        "topics_to_update": topics_to_update,
        "signals_to_update": signals_to_update,
    }


def apply_forget(store: LibraryStore, state: dict[str, Any], impact: dict[str, Any]) -> None:
    records = state["records"]
    sessions_to_delete = set(impact["sessions_to_delete"])
    quotes_to_delete = set(impact["quotes_to_delete"])
    topics_to_delete = set(impact["topics_to_delete"])
    signals_to_delete = set(impact["signals_to_delete"])

    for session_id, session in list(records["sessions"].items()):
        if session_id in sessions_to_delete:
            store.remove(session["path"])
            records["sessions"].pop(session_id, None)
            continue
        removed_here = set(session.get("quote_ids", [])) & quotes_to_delete
        if removed_here or topics_to_delete or signals_to_delete:
            text = store.read_text(session["path"])
            text = remove_quote_blocks(text, removed_here)
            text = remove_lines_containing(text, topics_to_delete | signals_to_delete)
            store.write_text(session["path"], text)
            session["quote_ids"] = [value for value in session.get("quote_ids", []) if value not in quotes_to_delete]
            session["topic_ids"] = [value for value in session.get("topic_ids", []) if value not in topics_to_delete]
            session["signal_ids"] = [value for value in session.get("signal_ids", []) if value not in signals_to_delete]

    for topic_id, topic in list(records["topics"].items()):
        if topic_id in topics_to_delete:
            store.remove(topic["path"])
            records["topics"].pop(topic_id, None)
            continue
        if topic_id in impact["topics_to_update"]:
            removed = set(topic.get("quote_ids", [])) - set(impact["topics_to_update"][topic_id])
            text = remove_lines_containing(store.read_text(topic["path"]), removed)
            store.write_text(topic["path"], text)
            topic["quote_ids"] = impact["topics_to_update"][topic_id]

    for signal_id, signal in list(records["signals"].items()):
        if signal_id in signals_to_delete:
            store.remove(signal["path"])
            records["signals"].pop(signal_id, None)
            continue
        if signal_id in impact["signals_to_update"]:
            remaining = impact["signals_to_update"][signal_id]
            removed = set(signal.get("evidence_quote_ids", [])) - set(remaining)
            text = remove_lines_containing(store.read_text(signal["path"]), removed)
            evidence_sessions = sorted(
                {
                    records["quotes"][quote_id]["session_id"]
                    for quote_id in remaining
                    if quote_id in records["quotes"] and quote_id not in quotes_to_delete
                }
            )
            if signal.get("status") == "recurring" and len(evidence_sessions) < 3:
                signal["status"] = "tentative"
                text = replace_frontmatter_status(text, "tentative")
            store.write_text(signal["path"], text)
            signal["evidence_quote_ids"] = remaining
            signal["evidence_session_ids"] = evidence_sessions

    for quote_id in quotes_to_delete:
        records["quotes"].pop(quote_id, None)
    for signal_id, signal in list(records["signals"].items()):
        removed_contradictions = set(signal.get("contradicts", [])) & signals_to_delete
        if not removed_contradictions:
            continue
        signal["contradicts"] = [
            value for value in signal.get("contradicts", []) if value not in signals_to_delete
        ]
        text = remove_lines_containing(store.read_text(signal["path"]), removed_contradictions)
        if signal.get("status") == "contradicted" and not signal["contradicts"]:
            signal["status"] = "tentative"
            text = replace_frontmatter_status(text, "tentative")
        store.write_text(signal["path"], text)
    update_stats(state)
    rebuild_profile(store, state)
    store.write_state(state)


def cmd_forget(args: argparse.Namespace) -> int:
    store, state = load_store(args.library)
    impact = find_forget_impact(state, store, args)
    result = {"ok": True, "mode": "dry-run" if args.dry_run else "apply", "impact": impact}
    if args.apply:
        apply_forget(store, state, impact)
        report = validation_report(store, state)
        result["validation"] = report
        if not report["ok"]:
            print(dump_json(result), end="")
            return 1
    print(dump_json(result), end="")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="initialize a user evidence library")
    init_parser.add_argument("--user-slug", required=True)
    init_parser.add_argument("--name", required=True)
    init_parser.add_argument("--business", default="")
    init_parser.add_argument("--domains", default="")
    init_parser.add_argument("--default-mode", default="deep-interviewer", choices=sorted(MODES))
    init_parser.add_argument("--root", help="explicit library root; useful for tests or non-default locations")
    init_parser.add_argument("--backend", choices=("auto", "filesystem", "obsidian"), default="auto")
    init_parser.set_defaults(func=cmd_init)

    register_parser = subparsers.add_parser("register", help="register user-confirmed assets")
    register_parser.add_argument("--library", required=True)
    register_parser.add_argument("--payload", required=True)
    register_parser.set_defaults(func=cmd_register)

    status_parser = subparsers.add_parser("status", help="show corpus and persona readiness")
    status_parser.add_argument("--library", required=True)
    status_parser.add_argument("--json", action="store_true")
    status_parser.set_defaults(func=cmd_status)

    context_parser = subparsers.add_parser("context", help="build an evidence-grounded context pack")
    context_parser.add_argument("--library", required=True)
    context_parser.add_argument("--query", default="")
    context_parser.add_argument("--theme", action="append")
    context_parser.add_argument("--limit", type=int, default=8)
    context_parser.add_argument("--output")
    context_parser.set_defaults(func=cmd_context)

    validate_parser = subparsers.add_parser("validate", help="validate evidence references and state")
    validate_parser.add_argument("--library", required=True)
    validate_parser.add_argument("--json", action="store_true")
    validate_parser.set_defaults(func=cmd_validate)

    forget_parser = subparsers.add_parser("forget", help="preview or apply a confirmed forget request")
    forget_parser.add_argument("--library", required=True)
    forget_parser.add_argument("--quote-id", action="append")
    forget_parser.add_argument("--session-id", action="append")
    forget_parser.add_argument("--topic-id", action="append")
    forget_parser.add_argument("--signal-id", action="append")
    forget_parser.add_argument("--contains")
    action = forget_parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--dry-run", action="store_true")
    action.add_argument("--apply", action="store_true")
    forget_parser.set_defaults(func=cmd_forget)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "forget" and not any(
        [args.quote_id, args.session_id, args.topic_id, args.signal_id, args.contains]
    ):
        parser.error("forget requires at least one target selector")
    try:
        return int(args.func(args))
    except LibraryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
