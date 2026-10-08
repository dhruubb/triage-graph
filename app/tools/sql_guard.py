"""Guardrails for model-written SQL.

Defence in depth for the history agent's text-to-SQL tool:
1. Parse with sqlglot and accept exactly one read-only SELECT.
2. Allow only the incidents table.
3. Force a row limit.
4. Run it on a read-only SQLite connection with query_only on (see incidents_db).
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp

ALLOWED_TABLES = {"incidents"}
MAX_ROWS = 50
FORBIDDEN_NODES = (
    exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter,
    exp.Command, exp.Merge, exp.TruncateTable, exp.Pragma, exp.Attach, exp.Detach,
)
FORBIDDEN_FUNCTIONS = {"load_extension", "readfile", "writefile", "edit", "fts3_tokenizer"}


class UnsafeSQLError(ValueError):
    pass


def validate_select(sql: str) -> str:
    """Return a safe, limited version of `sql`, or raise UnsafeSQLError."""
    if not sql or not sql.strip():
        raise UnsafeSQLError("empty query")
    try:
        statements = [s for s in sqlglot.parse(sql, read="sqlite") if s is not None]
    except sqlglot.errors.ParseError as exc:
        raise UnsafeSQLError(f"could not parse SQL: {str(exc).splitlines()[0]}") from exc
    if len(statements) != 1:
        raise UnsafeSQLError("exactly one statement is allowed")
    stmt = statements[0]
    if not isinstance(stmt, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
        raise UnsafeSQLError(f"only SELECT queries are allowed, got {stmt.key.upper()}")
    for node in stmt.walk():
        if isinstance(node, FORBIDDEN_NODES):
            raise UnsafeSQLError(f"{node.key.upper()} is not allowed")
        if isinstance(node, (exp.Anonymous, exp.Func)):
            name = (node.name if isinstance(node, exp.Anonymous) else node.sql_name()).lower()
            if name in FORBIDDEN_FUNCTIONS:
                raise UnsafeSQLError(f"function {name} is not allowed")
    cte_names = {cte.alias_or_name.lower() for cte in stmt.find_all(exp.CTE)}
    tables = {t.name.lower() for t in stmt.find_all(exp.Table)} - cte_names
    bad = tables - ALLOWED_TABLES
    if bad:
        raise UnsafeSQLError(f"table not allowed: {', '.join(sorted(bad))}")
    if isinstance(stmt, exp.Select):
        limit = stmt.args.get("limit")
        current = None
        if limit is not None:
            try:
                current = int(limit.expression.name)
            except (AttributeError, ValueError):
                current = None
        if current is None or current > MAX_ROWS:
            stmt = stmt.limit(MAX_ROWS)
        return stmt.sql(dialect="sqlite")
    return f"SELECT * FROM ({stmt.sql(dialect='sqlite')}) LIMIT {MAX_ROWS}"
