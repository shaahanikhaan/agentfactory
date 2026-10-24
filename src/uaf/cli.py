"""UAF command-line interface. Every command maps to a real application service."""

from __future__ import annotations

import argparse
import dataclasses
import getpass
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from uaf import __version__
from uaf.agents import role_catalog
from uaf.app import Application
from uaf.config import AppPaths, ConfigManager
from uaf.diagnostics import benchmark, capability_report
from uaf.errors import UAFError, ValidationError
from uaf.logging_config import configure_logging
from uaf.mcp_server import serve as serve_mcp
from uaf.models import Priority, RiskTier, TaskContract
from uaf.onboarding import GeminiOnboarding
from uaf.self_update import SelfUpdateManager
from uaf.util import canonical_json, now_dt, redact_data, redact_text


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="uaf",
        description="Ultimate Agent Factory — local-first, durable, no-spend multi-agent runtime",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--home", help="Override UAF_HOME for this invocation")
    parser.add_argument("--verbose", action="store_true", help="Write verbose redacted local logs")
    parser.add_argument(
        "--json", action="store_true", help="Machine-readable JSON (accepted anywhere)"
    )
    commands = parser.add_subparsers(dest="command")

    init = commands.add_parser("init", help="Initialize local state and workspace")
    init.add_argument("--workspace")
    init.add_argument(
        "--online", action="store_true", help="Explicitly permit configured cloud calls"
    )
    commands.add_parser("doctor", help="Check runtime, paths, database, RAM, and optional features")
    setup = commands.add_parser("setup", help="Guided one-Gemini-key onboarding with OS vault storage")
    setup.add_argument("--workspace")
    setup.add_argument("--model", help="Choose a discovered model without a numeric prompt")
    setup.add_argument("--online", action="store_true", help="Permit model discovery and Gemini calls")
    setup.add_argument(
        "--confirm-free",
        action="store_true",
        help="Confirm that current official pricing documents this model/key as free",
    )
    setup.add_argument(
        "--source",
        default="https://ai.google.dev/gemini-api/docs/pricing",
        help="Official current free-tier evidence URL",
    )
    setup.add_argument("--verified-at", help="YYYY-MM-DD; defaults to today after confirmation")
    setup.add_argument(
        "--live-test", action="store_true", help="Also make one explicit real generation request"
    )
    auth = commands.add_parser("auth", help="Inspect or delete OS-vault provider credentials")
    auth_sub = auth.add_subparsers(dest="subcommand", required=True)
    auth_sub.add_parser("status")
    auth_delete = auth_sub.add_parser("delete")
    auth_delete.add_argument("provider", choices=["gemini", "groq", "openrouter"])
    auth_delete.add_argument("--yes", action="store_true")
    browser = commands.add_parser("browser", help="Dedicated visible browser profile")
    browser_sub = browser.add_subparsers(dest="subcommand", required=True)
    browser_login = browser_sub.add_parser(
        "login", help="Let the user log in manually; no credentials are read by the agent"
    )
    browser_login.add_argument("url")
    browser_login.add_argument("--wait-seconds", type=int, default=120)
    browser_inspect = browser_sub.add_parser(
        "inspect", help="Show bounded redacted text and numbered elements for an exact action"
    )
    browser_inspect.add_argument("url")
    browser_inspect.add_argument("--wait-seconds", type=int, default=1)
    desktop = commands.add_parser("desktop", help="Approval-gated Windows mouse/keyboard batches")
    desktop_sub = desktop.add_subparsers(dest="subcommand", required=True)
    desktop_run = desktop_sub.add_parser("run")
    desktop_run.add_argument("request", help="Workspace-relative UTF-8 JSON batch")
    commands.add_parser("status", help="Show tasks, providers, memory, backups, and budgets")
    commands.add_parser("capabilities", help="Truthful machine-readable capability report")

    config = commands.add_parser("config", help="Inspect or change safe configuration")
    config_sub = config.add_subparsers(dest="subcommand", required=True)
    config_sub.add_parser("show")
    config_set = config_sub.add_parser("set")
    config_set.add_argument("key")
    config_set.add_argument("value", help="JSON boolean/number or string")

    task = commands.add_parser("task", help="Durable task operations")
    task_sub = task.add_subparsers(dest="subcommand", required=True)
    add = task_sub.add_parser("add")
    add.add_argument("goal")
    add.add_argument("--kind", choices=["agent", "react", "smoke", "tool"], default="agent")
    add.add_argument("--tool", help="Built-in tool name for --kind tool")
    add.add_argument("--arguments", default="{}", help="JSON object of tool arguments")
    add.add_argument("--allowed-tool", action="append", default=[])
    add.add_argument("--depends-on", action="append", default=[])
    add.add_argument("--constraint", action="append", default=[])
    add.add_argument("--priority", choices=[p.value for p in Priority], default="normal")
    add.add_argument("--risk", choices=[r.value for r in RiskTier], default="R0")
    add.add_argument("--department", default="executive")
    add.add_argument("--deadline", help="Timezone-aware ISO timestamp")
    add.add_argument("--idempotency-key")
    add.add_argument("--schema", default="{}", help="Required worker output JSON schema")
    for name, help_text in (
        ("list", "List tasks"),
        ("run", "Run one task or the runnable queue"),
    ):
        cmd = task_sub.add_parser(name, help=help_text)
        if name == "list":
            cmd.add_argument("--state")
            cmd.add_argument("--limit", type=int, default=100)
        else:
            cmd.add_argument("task_id", nargs="?")
            cmd.add_argument("--all", action="store_true")
            cmd.add_argument("--limit", type=int, default=100)
    for name in ("show", "timeline", "resume", "cancel"):
        cmd = task_sub.add_parser(name)
        cmd.add_argument("task_id")

    provider = commands.add_parser("provider", help="Free-only model registry and diagnostics")
    provider_sub = provider.add_subparsers(dest="subcommand", required=True)
    provider_sub.add_parser("list")
    configure = provider_sub.add_parser("configure")
    configure.add_argument("provider", choices=["gemini", "groq", "openrouter", "ollama"])
    configure.add_argument("model")
    configure.add_argument("--confirm-free", action="store_true")
    configure.add_argument("--confirm-local-resources", action="store_true")
    configure.add_argument("--source", help="Official HTTPS free-tier evidence URL")
    configure.add_argument(
        "--verified-at", help="YYYY-MM-DD; defaults to today after explicit confirmation"
    )
    configure.add_argument("--capabilities", default="text")
    configure.add_argument("--priority", type=int, default=100)
    configure.add_argument("--context-limit", type=int, default=32_000)
    configure.add_argument("--output-limit", type=int, default=4_096)
    configure.add_argument("--endpoint", help="Loopback Ollama origin only")
    for name in ("enable", "disable", "test", "clear-cooldown"):
        cmd = provider_sub.add_parser(name)
        cmd.add_argument("provider", choices=["gemini", "groq", "openrouter", "ollama"])
        if name == "test":
            cmd.add_argument(
                "--live", action="store_true", help="Make one explicit real model request"
            )
        if name == "clear-cooldown":
            cmd.add_argument("--model")

    memory = commands.add_parser("memory", help="Provenance-backed memory and maintenance")
    memory_sub = memory.add_subparsers(dest="subcommand", required=True)
    mem_add = memory_sub.add_parser("add")
    mem_add.add_argument("content")
    mem_add.add_argument("--type", default="fact")
    mem_add.add_argument("--source", default="local-user")
    mem_add.add_argument("--confidence", type=float, default=1.0)
    mem_add.add_argument(
        "--sensitivity", choices=["public", "internal", "private"], default="internal"
    )
    mem_add.add_argument("--expires-at")
    mem_add.add_argument("--approved", action="store_true")
    mem_list = memory_sub.add_parser("list")
    mem_list.add_argument("--type")
    mem_list.add_argument("--approved-only", action="store_true")
    mem_list.add_argument("--limit", type=int, default=100)
    mem_search = memory_sub.add_parser("search")
    mem_search.add_argument("query")
    mem_search.add_argument("--include-pending", action="store_true")
    mem_search.add_argument("--limit", type=int, default=20)
    for name in ("show", "revisions", "approve", "delete"):
        cmd = memory_sub.add_parser(name)
        cmd.add_argument("memory_id")
        if name == "delete":
            cmd.add_argument("--yes", action="store_true")
    mem_correct = memory_sub.add_parser("correct")
    mem_correct.add_argument("memory_id")
    mem_correct.add_argument("content")
    mem_correct.add_argument("--reason", default="correction")
    mem_export = memory_sub.add_parser("export")
    mem_export.add_argument("destination")
    mem_consolidate = memory_sub.add_parser("consolidate")
    mem_consolidate.add_argument("--apply", metavar="JOB_ID")
    mem_consolidate.add_argument("--record-limit", type=int, default=500)

    backup = commands.add_parser("backup", help="Consistent database snapshots")
    backup_sub = backup.add_subparsers(dest="subcommand", required=True)
    backup_create = backup_sub.add_parser("create")
    backup_create.add_argument("--purpose", default="manual")
    backup_sub.add_parser("list")
    for name in ("verify", "restore"):
        cmd = backup_sub.add_parser(name)
        cmd.add_argument("snapshot_id")
        if name == "restore":
            cmd.add_argument("--yes", action="store_true")

    approval = commands.add_parser("approval", help="Human decisions for exact high-risk actions")
    approval_sub = approval.add_subparsers(dest="subcommand", required=True)
    approval_list = approval_sub.add_parser("list")
    approval_list.add_argument("--state")
    for name in ("approve", "reject"):
        cmd = approval_sub.add_parser(name)
        cmd.add_argument("approval_id")
        cmd.add_argument("--actor", default="local-human")
        cmd.add_argument("--reason", default="")

    effect = commands.add_parser("effect", help="Inspect and reconcile uncertain external effects")
    effect_sub = effect.add_subparsers(dest="subcommand", required=True)
    effect_list = effect_sub.add_parser("list")
    effect_list.add_argument("task_id")
    effect_reconcile = effect_sub.add_parser("reconcile")
    effect_reconcile.add_argument("task_id")
    effect_reconcile.add_argument("key", help="Exact key from effect list")
    effect_reconcile.add_argument("--observed", choices=["executed", "not-executed"], required=True)
    effect_reconcile.add_argument(
        "--evidence", required=True, help="Bounded JSON object with human observation evidence"
    )
    effect_reconcile.add_argument(
        "--result", help="Required for executed: JSON object with output and evidence"
    )
    effect_reconcile.add_argument("--actor", default="local-human")
    effect_reconcile.add_argument("--yes", action="store_true")

    plugin = commands.add_parser("plugin", help="Controlled declarative plugin lifecycle")
    plugin_sub = plugin.add_subparsers(dest="subcommand", required=True)
    plugin_sub.add_parser("discover")
    plugin_sub.add_parser("list")
    plugin_register = plugin_sub.add_parser("register")
    plugin_register.add_argument("manifest")
    for name in ("enable", "disable"):
        cmd = plugin_sub.add_parser(name)
        cmd.add_argument("plugin_id")
    plugin_run = plugin_sub.add_parser("run")
    plugin_run.add_argument("plugin_id")
    plugin_run.add_argument(
        "--input", default="{}", help="JSON object matching the plugin input schema"
    )

    skill = commands.add_parser("skill", help="Progressively disclosed skill library")
    skill_sub = skill.add_subparsers(dest="subcommand", required=True)
    skill_sub.add_parser("list")
    skill_show = skill_sub.add_parser("show")
    skill_show.add_argument("skill_id")
    commands.add_parser("tool", help="List registered governed tools").add_subparsers(
        dest="subcommand", required=True
    ).add_parser("list")

    research = commands.add_parser("research", help="Bounded HTTPS source fetch and provenance")
    research_sub = research.add_subparsers(dest="subcommand", required=True)
    research_fetch = research_sub.add_parser("fetch")
    research_fetch.add_argument("url")
    research_fetch.add_argument("--full", action="store_true")
    research_sub.add_parser("list")
    research_show = research_sub.add_parser("show")
    research_show.add_argument("source_id")

    commands.add_parser("mcp", help="Optional MCP integration").add_subparsers(
        dest="subcommand", required=True
    ).add_parser("serve", help="Serve narrow tools over stdio")

    update = commands.add_parser("self-update", help="Human-gated update proposals")
    update_sub = update.add_subparsers(dest="subcommand", required=True)
    update_check = update_sub.add_parser("check")
    update_check.add_argument("--repo", default=".")
    update_plan = update_sub.add_parser("plan")
    update_plan.add_argument("--repo", default=".")
    update_plan.add_argument("--patch", required=True)
    update_plan.add_argument("--run-tests", action="store_true")
    update_plan.add_argument("--allow-untrusted-code", action="store_true")

    commands.add_parser("agents", help="List logical role profiles and charters")
    blueprint = commands.add_parser(
        "blueprint", help="Immutable declarative agent-team specifications"
    )
    blueprint_sub = blueprint.add_subparsers(dest="subcommand", required=True)
    blueprint_sub.add_parser("list")
    blueprint_show = blueprint_sub.add_parser("show")
    blueprint_show.add_argument("blueprint_id")
    blueprint_register = blueprint_sub.add_parser("register")
    blueprint_register.add_argument("path")
    for name in ("enable", "disable"):
        command_parser = blueprint_sub.add_parser(name)
        command_parser.add_argument("blueprint_id")
    factory = commands.add_parser("factory", help="Run durable declarative agent DAGs")
    factory_sub = factory.add_subparsers(dest="subcommand", required=True)
    factory_start = factory_sub.add_parser("start")
    factory_start.add_argument("blueprint_id")
    factory_start.add_argument("goal")
    factory_start.add_argument("--input", default="{}", help="JSON object matching input_schema")
    factory_start.add_argument("--idempotency-key")
    factory_show = factory_sub.add_parser("show")
    factory_show.add_argument("run_id")
    for name in ("resume", "cancel"):
        command_parser = factory_sub.add_parser(name)
        command_parser.add_argument("run_id")
        command_parser.add_argument("--actor", default="local-human")
    factory_list = factory_sub.add_parser("list")
    factory_list.add_argument("--limit", type=int, default=50)
    evaluation = commands.add_parser(
        "eval", help="Reproducible task evaluation and regression gates"
    )
    evaluation_sub = evaluation.add_subparsers(dest="subcommand", required=True)
    evaluation_run = evaluation_sub.add_parser("run")
    evaluation_run.add_argument(
        "--suite", help="Custom bounded JSON suite; defaults to offline core"
    )
    evaluation_run.add_argument("--baseline", help="Prior run of the identical suite")
    evaluation_run.add_argument("--candidate", help="Optional candidate identifier for evidence")
    evaluation_show = evaluation_sub.add_parser("show")
    evaluation_show.add_argument("run_id")
    evaluation_compare = evaluation_sub.add_parser("compare")
    evaluation_compare.add_argument("candidate_run_id")
    evaluation_compare.add_argument("baseline_run_id")
    evaluation_list = evaluation_sub.add_parser("list")
    evaluation_list.add_argument("--limit", type=int, default=50)
    bench = commands.add_parser("benchmark", help="Measure a real durable offline scenario")
    bench.add_argument("--iterations", type=int, default=5)
    return parser


def _json_object(raw: str, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"{label} must be valid JSON: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be a JSON object")
    return value


def _config_value(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _risk_for_tool(tool: str) -> RiskTier:
    if tool in {"workspace.delete", "browser.click", "desktop.execute"}:
        return RiskTier.R3
    if tool == "browser.type":
        return RiskTier.R2
    if tool == "workspace.write":
        return RiskTier.R1
    return RiskTier.R0


def dispatch(args: argparse.Namespace, paths: AppPaths) -> Any:
    command = args.command
    if command == "capabilities":
        return capability_report()
    if command == "agents":
        return role_catalog()
    if command == "init":
        settings = ConfigManager(paths).initialize(args.workspace, online=args.online)
        with Application(paths, verbose=args.verbose) as app:
            return {
                "initialized": True,
                "home": str(paths.home),
                "workspace": settings.workspace,
                "network_allowed": settings.network_allowed,
                "allow_paid": False,
                "database": app.db.integrity_check(),
            }
    if command == "config":
        manager = ConfigManager(paths)
        if args.subcommand == "show":
            return manager.load().to_dict()
        settings = manager.set(args.key, _config_value(args.value))
        return {"updated": args.key, "settings": settings.to_dict()}
    if command == "provider" and args.subcommand in {"configure", "enable", "disable"}:
        manager = ConfigManager(paths)
        settings = manager.load()
        provider = settings.providers[args.provider]
        if args.subcommand in {"enable", "disable"}:
            provider["enabled"] = args.subcommand == "enable"
            manager.save(settings)
            return {
                "provider": args.provider,
                "enabled": provider["enabled"],
                "network_allowed": settings.network_allowed,
                "note": "Eligibility still requires a fresh free/local model and credentials where applicable",
            }
        if args.provider == "ollama":
            if not args.confirm_local_resources:
                raise ValidationError("Ollama configuration requires --confirm-local-resources")
            model_config = {
                "enabled": True,
                "free_tier_status": "local",
                "free_tier_source": "local://inference",
                "verified_at": None,
            }
            if args.endpoint:
                provider["endpoint"] = args.endpoint
        else:
            if not args.confirm_free or not args.source:
                raise ValidationError(
                    "Cloud models require --confirm-free and official --source evidence"
                )
            model_config = {
                "enabled": True,
                "free_tier_status": "free",
                "free_tier_source": args.source,
                "verified_at": args.verified_at or now_dt().date().isoformat(),
            }
        model_config.update(
            {
                "capabilities": [
                    item.strip() for item in args.capabilities.split(",") if item.strip()
                ],
                "priority": args.priority,
                "context_limit": args.context_limit,
                "output_limit": args.output_limit,
            }
        )
        provider["models"][args.model] = model_config
        provider["enabled"] = True
        manager.save(settings)
        with Application(paths, verbose=args.verbose) as app:
            app.providers.clear_cooldown(args.provider, args.model)
            row = next(row for row in app.providers.list_models() if row["model"] == args.model)
            return {"configured": True, "eligibility": row, "credential_values_stored": False}

    with Application(paths, verbose=args.verbose) as app:
        if command == "setup":
            return _setup_command(args, app)
        if command == "auth":
            if args.subcommand == "status":
                return {
                    **app.credentials.status(),
                    "gemini_env_present": bool(os.environ.get("GEMINI_API_KEY")),
                }
            if not args.yes:
                raise ValidationError("Credential deletion requires explicit --yes")
            deleted = app.credentials.delete(args.provider)
            return {
                "provider": args.provider,
                "deleted": deleted,
                "environment_credential_still_present": bool(
                    os.environ.get(f"{args.provider.upper()}_API_KEY")
                ),
            }
        if command == "browser":
            result = app.browser.open_for_user(args.url, wait_seconds=args.wait_seconds)
            app.db.audit(
                "browser.manual_user_session",
                actor="local-user",
                role="runtime",
                object_type="browser_profile",
                object_id="dedicated",
                decision="completed",
                metadata={
                    "url": result["url"],
                    "wait_seconds": args.wait_seconds,
                    "mode": args.subcommand,
                },
            )
            if args.subcommand == "inspect":
                return result
            return {
                "url": result["url"],
                "title": result["title"],
                "snapshot_id": result["snapshot_id"],
                "elements": len(result["elements"]),
                "text_characters": len(result["text"]),
                "credentials_read": False,
                "dedicated_profile": str(paths.browser_profile),
            }
        if command == "desktop":
            payload = _json_object(
                app.workspace.read_text(args.request, max_bytes=64_000)["content"],
                "desktop request",
            )
            task = app.tasks.add(
                TaskContract(
                    goal="Execute one explicitly approved desktop batch",
                    kind="tool",
                    risk_tier=RiskTier.R3,
                    input_data={"tool": "desktop.execute", "arguments": payload},
                    allowed_tools=["desktop.execute"],
                )
            )
            return app.runner.run(task["task_id"])
        if command == "doctor":
            return app.diagnostics.doctor()
        if command == "status":
            return app.diagnostics.status(app.providers.list_models())
        if command == "task":
            return _task_command(args, app)
        if command == "provider":
            if args.subcommand == "list":
                return {
                    "models": app.providers.list_models(),
                    "cooldowns": app.providers.cooldowns(),
                }
            if args.subcommand == "test":
                return app.providers.test(args.provider, live=args.live)
            if args.subcommand == "clear-cooldown":
                app.providers.clear_cooldown(args.provider, args.model)
                return {"cleared": True, "provider": args.provider, "model": args.model}
        if command == "memory":
            return _memory_command(args, app)
        if command == "backup":
            if args.subcommand == "create":
                return app.backups.create(args.purpose)
            if args.subcommand == "list":
                return app.backups.list()
            if args.subcommand == "verify":
                return app.backups.verify(args.snapshot_id)
            return app.backups.restore(args.snapshot_id, confirmed=args.yes)
        if command == "approval":
            if args.subcommand == "list":
                return app.approvals.list(args.state)
            return app.approvals.decide(
                args.approval_id,
                approve=args.subcommand == "approve",
                actor=args.actor,
                reason=args.reason,
            )
        if command == "effect":
            app.tasks.require(args.task_id)
            if args.subcommand == "list":
                return app.ledger.for_task(args.task_id)
            if not args.yes:
                raise ValidationError("Effect reconciliation requires explicit --yes")
            expected_prefix = f"{args.task_id}:"
            if not args.key.startswith(expected_prefix) or len(args.key) > 256:
                raise ValidationError("Effect key does not belong to the specified task")
            evidence = _json_object(args.evidence, "reconciliation evidence")
            if not evidence:
                raise ValidationError("Reconciliation evidence cannot be empty")
            result = _json_object(args.result, "reconciled result") if args.result else None
            if args.observed == "executed":
                if (
                    result is None
                    or not isinstance(result.get("output"), dict)
                    or not isinstance(result.get("evidence"), dict)
                ):
                    raise ValidationError(
                        "Executed reconciliation requires --result with output and evidence objects"
                    )
            elif result is not None:
                raise ValidationError("not-executed reconciliation does not accept --result")
            reconciled = app.ledger.reconcile(
                scope=f"task:{args.task_id}",
                key=args.key,
                observed=args.observed == "executed",
                evidence=evidence,
                result=result,
                actor=args.actor,
            )
            remaining = app.ledger.for_task(args.task_id)
            return {
                "task_id": args.task_id,
                "effect": reconciled,
                "resume_allowed": all(
                    row["state"] not in {"uncertain", "reserved"} for row in remaining
                ),
            }
        if command == "plugin":
            if args.subcommand == "discover":
                return {
                    "registered": app.plugins.discover(),
                    "entry_points": app.plugins.entry_point_metadata(),
                }
            if args.subcommand == "register":
                return {"registered": app.plugins.register(Path(args.manifest)), "enabled": False}
            if args.subcommand == "list":
                return app.plugins.list()
            if args.subcommand == "enable":
                return app.plugins.enable(args.plugin_id, confirmed=True)
            if args.subcommand == "disable":
                return app.plugins.disable(args.plugin_id)
            rendered = app.plugins.render(args.plugin_id, _json_object(args.input, "plugin input"))
            task = app.tasks.add(
                TaskContract(
                    goal=f"Execute declarative plugin {args.plugin_id}",
                    kind="tool",
                    input_data={"tool": rendered["tool"], "arguments": rendered["arguments"]},
                    allowed_tools=[rendered["tool"]],
                    risk_tier=_risk_for_tool(rendered["tool"]),
                    requester="local-user",
                    department="extensions",
                )
            )
            return app.runner.run(task["task_id"])
        if command == "skill":
            return (
                app.skills.list() if args.subcommand == "list" else app.skills.load(args.skill_id)
            )
        if command == "tool":
            return app.tools.list()
        if command == "research":
            if args.subcommand == "list":
                return app.research.list()
            if args.subcommand == "show":
                return app.research.get(args.source_id)
            result = app.research.fetch(args.url)
            data = dataclasses.asdict(result)
            if not args.full:
                data["content"] = data["content"][:4_000]
                data.pop("model_context", None)
                data["content_preview"] = True
            return data
        if command == "mcp":
            if not app.settings.mcp_enabled:
                raise ValidationError(
                    "MCP is disabled; run 'uaf config set mcp_enabled true' after review"
                )
            serve_mcp(app.tasks, app.memory)
            # stdio belongs exclusively to JSON-RPC; never print CLI status into it.
            return None
        if command == "self-update":
            manager = SelfUpdateManager(app.db, app.backups, Path(args.repo), paths.candidates)
            if args.subcommand == "check":
                return manager.check()
            return manager.plan(
                Path(args.patch),
                run_tests=args.run_tests,
                allow_untrusted_code=args.allow_untrusted_code,
            )
        if command == "blueprint":
            if args.subcommand == "list":
                return app.blueprints.list()
            if args.subcommand == "show":
                return app.blueprints.require(args.blueprint_id)
            if args.subcommand == "register":
                return app.blueprints.register(Path(args.path))
            return app.blueprints.set_enabled(
                args.blueprint_id, enabled=args.subcommand == "enable"
            )
        if command == "factory":
            if args.subcommand == "start":
                return app.factory.start(
                    args.blueprint_id,
                    args.goal,
                    inputs=_json_object(args.input, "factory input"),
                    idempotency_key=args.idempotency_key,
                )
            if args.subcommand == "show":
                return app.factory.require(args.run_id)
            if args.subcommand == "list":
                return app.factory.list(limit=args.limit)
            if args.subcommand == "resume":
                return app.factory.resume(args.run_id, actor=args.actor)
            return app.factory.cancel(args.run_id, actor=args.actor)
        if command == "eval":
            if args.subcommand == "run":
                return app.evaluations.run(
                    args.suite,
                    baseline_run_id=args.baseline,
                    candidate_id=args.candidate,
                )
            if args.subcommand == "show":
                return app.evaluations.require(args.run_id)
            if args.subcommand == "compare":
                return app.evaluations.compare(args.candidate_run_id, args.baseline_run_id)
            return app.evaluations.list(limit=args.limit)
        if command == "benchmark":
            return benchmark(app.runner, app.tasks, iterations=args.iterations)
    raise ValidationError(f"Unsupported command: {command}")


def _ask(prompt: str) -> str:
    print(prompt, file=sys.stderr)
    try:
        return input().strip()
    except EOFError as exc:
        raise ValidationError(
            "Interactive setup input is unavailable; use GEMINI_API_KEY, --model, "
            "--online and --confirm-free explicitly"
        ) from exc


def _setup_command(args: argparse.Namespace, app: Application) -> Any:
    app.config.initialize(args.workspace, online=args.online)
    secret = os.environ.get("GEMINI_API_KEY")
    if not secret:
        try:
            secret = getpass.getpass("Gemini API key (hidden; stored only in OS vault): ")
        except EOFError as exc:
            raise ValidationError("Set GEMINI_API_KEY for noninteractive setup") from exc
    network_confirmed = args.online or _ask(
        "Allow one HTTPS request to Google's official models.list endpoint? Type ONLINE: "
    ) == "ONLINE"
    discovered = GeminiOnboarding(app.config, app.credentials).discover(
        secret, network_confirmed=network_confirmed
    )
    model = args.model
    if not model:
        for index, item in enumerate(discovered, start=1):
            print(
                f"{index}. {item['model']} — {item['display_name']} "
                f"(context {item['context_limit']}, output {item['output_limit']})",
                file=sys.stderr,
            )
        selection = _ask(f"Select a model number [1-{len(discovered)}]: ")
        try:
            model = discovered[int(selection) - 1]["model"]
        except (ValueError, IndexError) as exc:
            raise ValidationError("Invalid model selection") from exc
    free_confirmed = args.confirm_free or _ask(
        f"Review current pricing at {args.source}. Model discovery does not prove free "
        "eligibility. Type FREE only if this key/model is currently eligible: "
    ) == "FREE"
    result = GeminiOnboarding(app.config, app.credentials).complete(
        secret,
        discovered,
        model=model,
        free_confirmed=free_confirmed,
        source=args.source,
        verified_at=args.verified_at,
    )
    app.settings = app.config.load()
    app.providers.settings = app.settings
    app.providers.sync_registry()
    eligibility = next(
        row
        for row in app.providers.list_models()
        if row["provider"] == "gemini" and row["model"] == model
    )
    result["setup_complete"] = bool(eligibility["eligible"])
    result["eligibility"] = eligibility
    app.db.audit(
        "setup.gemini_one_key",
        actor="local-user",
        role="runtime",
        object_type="provider",
        object_id="gemini",
        decision="configured" if result["setup_complete"] else "blocked",
        metadata={"model": model, "credential_storage": "os_vault"},
    )
    if args.live_test:
        result["live_test"] = app.providers.test("gemini", live=True)
        result["live_generation_tested"] = result["live_test"]["status"] == "completed"
    return result


def _task_command(args: argparse.Namespace, app: Application) -> Any:
    if args.subcommand == "add":
        arguments = _json_object(args.arguments, "tool arguments")
        schema = _json_object(args.schema, "output schema")
        if args.kind == "tool":
            if not args.tool:
                raise ValidationError("--kind tool requires --tool")
            arguments = {"tool": args.tool, "arguments": arguments}
            allowed = args.allowed_tool or [args.tool]
            risk = _risk_for_tool(args.tool) if args.risk == "R0" else RiskTier(args.risk)
        else:
            allowed = args.allowed_tool
            risk = RiskTier(args.risk)
        task = app.tasks.add(
            TaskContract(
                goal=args.goal,
                kind=args.kind,
                priority=Priority(args.priority),
                risk_tier=risk,
                department=args.department,
                deadline=args.deadline,
                input_data=arguments,
                constraints=args.constraint,
                allowed_tools=allowed,
                expected_output_schema=schema,
                idempotency_key=args.idempotency_key,
                depends_on=args.depends_on,
            )
        )
        return task
    if args.subcommand == "list":
        return app.tasks.list(args.state, limit=args.limit)
    if args.subcommand == "show":
        return app.tasks.require(args.task_id)
    if args.subcommand == "timeline":
        return app.tasks.timeline(args.task_id)
    if args.subcommand == "resume":
        return app.tasks.resume(args.task_id)
    if args.subcommand == "cancel":
        return app.tasks.cancel(args.task_id)
    if args.all:
        return app.runner.run_all(limit=args.limit)
    if not args.task_id:
        raise ValidationError("task run requires a task ID or --all")
    return app.runner.run(args.task_id)


def _memory_command(args: argparse.Namespace, app: Application) -> Any:
    if args.subcommand == "add":
        return app.memory.add(
            args.content,
            memory_type=args.type,
            source=args.source,
            confidence=args.confidence,
            sensitivity=args.sensitivity,
            expires_at=args.expires_at,
            approved=args.approved,
        )
    if args.subcommand == "list":
        return app.memory.list(
            memory_type=args.type, include_pending=not args.approved_only, limit=args.limit
        )
    if args.subcommand == "search":
        return app.memory.search(
            args.query, limit=args.limit, approved_only=not args.include_pending
        )
    if args.subcommand == "show":
        return app.memory.require(args.memory_id)
    if args.subcommand == "revisions":
        return app.memory.revisions(args.memory_id)
    if args.subcommand == "approve":
        return app.memory.approve(args.memory_id)
    if args.subcommand == "correct":
        return app.memory.correct(args.memory_id, args.content, reason=args.reason)
    if args.subcommand == "delete":
        app.memory.delete(args.memory_id, confirmed=args.yes)
        return {"deleted": args.memory_id, "content_scrubbed": True}
    if args.subcommand == "export":
        return app.memory.export(Path(args.destination))
    if args.apply:
        return app.memory.apply(args.apply)
    return app.memory.dry_run(record_limit=args.record_limit)


def _emit(value: Any, *, json_output: bool) -> None:
    value = redact_data(value)
    if dataclasses.is_dataclass(value):
        value = dataclasses.asdict(value)
    if json_output or isinstance(value, dict):
        print(json.dumps(value, indent=2, ensure_ascii=False, default=str))
        return
    if isinstance(value, list):
        if not value:
            print("No records.")
            return
        for item in value:
            if isinstance(item, dict):
                summary = {}
                for key in (
                    "task_id",
                    "run_id",
                    "blueprint_id",
                    "memory_id",
                    "approval_id",
                    "plugin_id",
                    "skill_id",
                    "provider",
                    "model",
                    "state",
                    "status",
                    "kind",
                    "type",
                    "risk_tier",
                    "eligible",
                    "goal",
                    "content",
                    "action_summary",
                    "name",
                    "reason",
                ):
                    if key in item and item[key] is not None:
                        summary[key] = item[key]
                print(canonical_json(summary or item))
            else:
                print(item)
        return
    print(value)


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    json_output = "--json" in raw
    raw = [item for item in raw if item != "--json"]
    parser = build_parser()
    args = parser.parse_args(raw)
    if not args.command:
        parser.print_help()
        return 0
    paths = AppPaths.discover(args.home)
    try:
        configure_logging(paths.logs, verbose=args.verbose)
        result = dispatch(args, paths)
        if result is not None:
            _emit(result, json_output=json_output)
        return 0
    except UAFError as exc:
        error = {
            "error": {
                "code": exc.code,
                "message": redact_text(str(exc)),
                "details": redact_data(exc.details),
            }
        }
        if json_output:
            print(json.dumps(error, indent=2, ensure_ascii=False), file=sys.stderr)
        else:
            print(f"Error [{exc.code}]: {redact_text(str(exc))}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print(
            "Interrupted; committed checkpoints remain available for explicit resume.",
            file=sys.stderr,
        )
        return 130
    except Exception as exc:
        logging.getLogger("uaf.cli").exception("Unhandled command failure")
        if args.verbose:
            raise
        print(
            f"Error [internal_error]: {redact_text(type(exc).__name__)}; see redacted local log",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
