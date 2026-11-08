"""Base declarativa de las herramientas: definición, plan y ejecución en pocas líneas."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from honey_check.application.support.ports import Preparation, SupportEnvironment, ToolContext
from honey_check.domain.support import (
    ActionLink,
    Check,
    CheckStatus,
    Choice,
    Column,
    ColumnKind,
    Fact,
    Param,
    ParamKind,
    PlanStep,
    Risk,
    Table,
    Tone,
    ToolDefinition,
    ToolResult,
)

Params = Mapping[str, Any]
PlanFunction = Callable[[Params, SupportEnvironment], list[PlanStep]]
ExecuteFunction = Callable[[Params, ToolContext], ToolResult]
# Revisión previa: resumen, verificaciones y si esta ejecución concreta necesita administrador.
ReviewFunction = Callable[[Params, SupportEnvironment], tuple[str | None, list[Check], bool]]


@dataclass
class SupportTool:
    """Una herramienta: su definición, cómo presenta el plan y cómo se ejecuta."""

    definition: ToolDefinition
    steps: PlanFunction
    run: ExecuteFunction
    warnings: Callable[[Params, SupportEnvironment], list[str]] = field(default=lambda _p, _e: [])
    backup: str | None = None
    review: ReviewFunction | None = None
    # Huella barata del estado que la consulta lee; `differs` compara con tolerancia.
    state: Callable[[Params, SupportEnvironment], str] | None = None
    differs: Callable[[str, str], bool] = field(default=lambda old, new: old != new)

    def plan(self, params: Params, env: SupportEnvironment) -> Preparation:
        summary, checks, needs_admin = (
            self.review(params, env) if self.review else (None, [], False)
        )
        return Preparation(
            steps=self.steps(params, env),
            warnings=self.warnings(params, env),
            backup=self.backup,
            summary=summary,
            checks=checks,
            needs_admin=needs_admin,
        )

    def execute(self, params: Params, ctx: ToolContext) -> ToolResult:
        return self.run(params, ctx)

    def fingerprint(self, params: Params, env: SupportEnvironment) -> str | None:
        return self.state(params, env) if self.state else None

    def changed_since(self, old: str, params: Params, env: SupportEnvironment) -> bool | None:
        now = self.fingerprint(params, env)
        return None if now is None else self.differs(old, now)


def tool(
    id: str,
    category: str,
    title: str,
    description: str,
    risk: Risk,
    *,
    params: list[Param] | None = None,
    admin: bool = False,
    hidden: bool = False,
    network: bool = False,
    action: str | None = None,
    instant: bool = False,
) -> ToolDefinition:
    return ToolDefinition(
        id=id,
        category=category,
        title=title,
        description=description,
        risk=risk,
        requires_admin=admin,
        params=params or [],
        hidden=hidden,
        contacts_network=network,
        action_label=action,
        instant=instant,
    )


def text(
    name: str,
    label: str,
    *,
    required: bool = False,
    pattern: str | None = None,
    help: str | None = None,
    default: str | None = None,
    browse: str | None = None,
    browse_filter: str | None = None,
) -> Param:
    return Param(
        name=name,
        label=label,
        required=required,
        pattern=pattern,
        help=help,
        default=default,
        browse=browse,
        browse_filter=browse_filter,
    )


def secret(name: str, label: str, *, required: bool = False, help: str | None = None) -> Param:
    return Param(name=name, label=label, kind=ParamKind.SECRET, required=required, help=help)


def flag(name: str, label: str, *, default: bool = False, help: str | None = None) -> Param:
    return Param(name=name, label=label, kind=ParamKind.BOOL, default=default, help=help)


def number(name: str, label: str, *, default: int, help: str | None = None) -> Param:
    return Param(name=name, label=label, kind=ParamKind.NUMBER, default=default, help=help)


def choice(
    name: str,
    label: str,
    options: list[tuple[str, str]],
    *,
    default: str | None = None,
    help: str | None = None,
) -> Param:
    return Param(
        name=name,
        label=label,
        kind=ParamKind.CHOICE,
        choices=[Choice(value=v, label=t) for v, t in options],
        default=default if default is not None else options[0][0],
        help=help,
    )


def source_multi(
    name: str,
    label: str,
    source: str,
    *,
    pattern: str | None = None,
    help: str | None = None,
) -> Param:
    """Varias opciones elegidas de una lista que se lee del equipo (discos, impresoras…)."""
    return Param(
        name=name,
        label=label,
        kind=ParamKind.MULTI,
        source=source,
        pattern=pattern,
        help=help,
        max_length=1024,
    )


def source_choice(
    name: str,
    label: str,
    source: str,
    *,
    pattern: str | None = None,
    help: str | None = None,
    required: bool = True,
) -> Param:
    """Una opción elegida de una lista que se lee del equipo (una impresora, por ejemplo)."""
    return Param(
        name=name,
        label=label,
        kind=ParamKind.CHOICE,
        source=source,
        required=required,
        pattern=pattern,
        help=help,
    )


def multi(name: str, label: str, *, required: bool = True) -> Param:
    return Param(name=name, label=label, kind=ParamKind.MULTI, required=required, max_length=1024)


def step(title: str, command: str | None = None, detail: str | None = None) -> PlanStep:
    return PlanStep(title=title, command=command, detail=detail)


def fact(label: str, value: object, tone: Tone = Tone.NEUTRAL) -> Fact:
    return Fact(label=label, value=None if value is None else str(value), tone=tone)


def check(
    label: str,
    ok: bool | None,
    detail: str | None = None,
    fix: ActionLink | None = None,
    *,
    warn: bool = False,
) -> Check:
    if ok is None:
        status = CheckStatus.SKIPPED
    elif ok:
        status = CheckStatus.OK
    else:
        status = CheckStatus.WARN if warn else CheckStatus.FAIL
    return Check(label=label, status=status, detail=detail, fix=fix)


def link(tool_id: str, label: str, tone: Tone = Tone.NEUTRAL, **params: str) -> ActionLink:
    return ActionLink(tool=tool_id, label=label, params=params, tone=tone)


def node_actions(*links: ActionLink) -> list[dict[str, Any]]:
    """Acciones de un elemento de gráfico (`{campo}` se llena con los datos del elemento)."""
    return [item.model_dump(mode="json", by_alias=True) for item in links]


def col(key: str, label: str, kind: ColumnKind = ColumnKind.TEXT, priority: int = 1) -> Column:
    return Column(key=key, label=label, kind=kind, priority=priority)


MAX_ROWS = 2000


def table(
    id: str,
    title: str,
    columns: list[Column],
    rows: list[dict[str, Any]],
    row_key: str,
    *,
    actions: list[ActionLink] | None = None,
    bulk: ActionLink | None = None,
    selection_param: str | None = None,
) -> Table:
    return Table(
        id=id,
        title=title,
        columns=columns,
        rows=rows[:MAX_ROWS],
        row_key=row_key,
        row_actions=actions or [],
        bulk_action=bulk,
        selection_param=selection_param,
        truncated=len(rows) > MAX_ROWS,
    )
