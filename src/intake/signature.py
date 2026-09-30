"""
Failure signatures: turn a platform's raw error into stable, matchable parts — no LLM.

    parse(platform, error_code, message) -> Signature

Two layers:
  - a small parser per platform family pulls out the specific error code, the error/exception
    type and the part of the message that describes the error (wrappers stripped);
  - one shared masker replaces variable values (names, paths, ids, timestamps, numbers, ...)
    with placeholders, giving a template, and keeps the values separately.

Matching identity (see `Signature.identity`): a *specific* code identifies an error on its own
(its wording can change between platform versions), while a *generic wrapper* code (ADF 2200,
UserErrorOdbcOperationFailed, ...) wraps many unrelated causes, so it's the fingerprint —
code + type + first sentence of the template — that identifies those.
"""

import hashlib
import json
import re
from dataclasses import dataclass

# --------------------------------------------------------------------------- masking

# Most specific first: a GUID inside a URL is consumed as part of the URL.
_MASKS: tuple[tuple[str, re.Pattern], ...] = (
    (
        "URL",
        re.compile(
            r"\b(?:https?|abfss?|wasbs?|jdbc:[a-z]+|s3a?|gs|dbfs|sftp|ftp)://[^\s'\"<>,;)]+",
            re.I,
        ),
    ),
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")),
    (
        "ID",
        re.compile(
            r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I
        ),
    ),
    ("ID", re.compile(r"\b\d{4}-\d{6}-[a-z0-9]{8}\b")),  # Databricks cluster id
    # HTTP date: "Mon, 06 Oct 2025 10:14:03 GMT".
    (
        "TS",
        re.compile(
            r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun), \d{1,2} [A-Z][a-z]{2} \d{4} \d{2}:\d{2}:\d{2}(?: GMT)?"
        ),
    ),
    (
        "TS",
        re.compile(
            r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?\b"
        ),
    ),
    (
        "TS",
        re.compile(
            r"\b\d{1,2}/\d{1,2}/\d{2,4}(?:\s+\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM)?)?\b",
            re.I,
        ),
    ),
    ("TS", re.compile(r"\b\d{2}:\d{2}:\d{2}(?:\.\d+)?\b")),
    ("IP", re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b")),
    ("HEX", re.compile(r"\b0x[0-9a-f]+\b|\b[0-9a-f]{16,}\b", re.I)),
    # A quote right after a letter is an apostrophe (Can't, It's), not the start of a name.
    ("NAME", re.compile(r"(?<!\w)'[^'\n]{0,500}'(?!\w)")),
    ("NAME", re.compile(r"\"[^\"\n]{1,200}\"")),
    ("NAME", re.compile(r"`[^`\n]{1,200}`")),
    ("LIST", re.compile(r"\[[^\[\]\n<>]{1,300}\]")),
    # Hyphenated project/dataset names before a colon: hello-data-pipeline:dataset.
    ("NAME", re.compile(r"(?<![\w<-])[a-z][a-z0-9]*(?:-[a-z0-9]+)+(?=:\S)")),
    # A drive letter may be followed straight by a separator: D:/folder/file.
    ("PATH", re.compile(r"(?<![\w<])(?:[A-Za-z]:[/\\]?)?(?:[\w.$@-]+[/\\])+[\w.$@-]+")),
    (
        "PATH",
        re.compile(
            r"\b[\w-]+\.(?:csv|parquet|json|xlsx?|txt|avro|orc|xml|sql|ya?ml|py|zip|gz|tsv|dat)\b",
            re.I,
        ),
    ),
    # Identifier-shaped tokens (table_name, Prop_0, QID67099467) — codes are extracted first.
    ("NAME", re.compile(r"(?<![<\w])(?=\w*[A-Za-z])(?=\w*[_\d])\w{3,}(?![>\w])")),
    # An HTTP status after HttpStatusCode is the error itself (500 vs 404), not a value.
    ("NUM", re.compile(r"(?<![\w<])(?<!HttpStatusCode )-?\d+(?:\.\d+)?(?![\w>])")),
)
# Status and error codes quoted inside a message ('Conflict', 'LeaseAlreadyPresent') tell
# errors apart, so they stay in the template instead of being masked as names.
_QUOTED_CODE = re.compile(r"((?:status code|ErrorCode:)\s*)'(\w+)'")
_REPEATED_PLACEHOLDER = re.compile(r"(<(\w+)>)(?:\s*[,.]\s*<\2>)+")
_TEMPLATE_MAX = 300
_HEAD_MAX = 120


def _mask(text: str) -> tuple[str, dict[str, list[str]]]:
    values: dict[str, list[str]] = {}
    text = _QUOTED_CODE.sub(r"\1\2", text)
    for kind, pattern in _MASKS:

        def keep(match: re.Match, kind: str = kind) -> str:
            values.setdefault(kind, []).append(match.group(0).strip("'\"`"))
            return f"<{kind}>"

        text = pattern.sub(keep, text)
    text = _REPEATED_PLACEHOLDER.sub(r"\1", re.sub(r"\s+", " ", text).strip())
    return text[:_TEMPLATE_MAX], values


def _head(template: str) -> str:
    """First sentence of the template: the stable part. Tails such as "Additional info: ..."
    vary between occurrences of the same error."""
    first = re.split(r"(?<=[.;])\s|\s(?=Additional info)", template, maxsplit=1)[0]
    return first[:_HEAD_MAX].rstrip(" .;:")


# --------------------------------------------------------------------------- parsers


@dataclass(frozen=True)
class _Parsed:
    code: str | None
    error_type: str | None
    core: str


def _is_numeric(code: str | None) -> bool:
    return bool(code) and code.strip().isdigit()


# ADF / Synapse / Fabric pipelines share one error format: stacked wrappers, then
# ErrorCode=<Specific>,'Type=<.NET exception>,Message=<text>,Source=<assembly>,'
_AZURE_WRAPPERS = (
    re.compile(r"Operation on target .+? failed:\s*"),
    re.compile(
        r"Activity failed because an inner activity failed;\s*Inner activity name:\s*[^,]+,\s*Error:\s*"
    ),
    re.compile(r"Failure happened on '?(?:Source|Sink)'? side\.\s*"),
)
_AZURE_MESSAGE = re.compile(
    r"Message=\s*(.+?)(?:,\s*Source=|,\s*'{1,2}Type=|'\s*$|$)", re.S
)


def _parse_azure(message: str, error_code: str | None) -> _Parsed:
    msg = message.replace("&#44;", ",").replace("\\r\\n", " ").replace("\\n", " ")
    msg = re.sub(r"''(?=[^\s',])|(?<=[^\s',])''", "'", msg)  # ADF doubles nested quotes
    for wrapper in _AZURE_WRAPPERS:
        msg = wrapper.sub("", msg)
    code_match = re.search(r"ErrorCode=\s*([A-Za-z][\w.]*)", msg)
    types = re.findall(r"Type=\s*([\w.]+)", msg)
    body = _AZURE_MESSAGE.search(msg)
    code = code_match.group(1) if code_match else None
    if not code and error_code and not _is_numeric(error_code):
        code = error_code  # data flow (DF-*), notebook and service errors
    if not code:
        named = re.search(r"Error name - (\w+)", msg)
        code = named.group(1) if named else None
    core = body.group(1) if body else msg
    if code in _GENERIC_WRAPPER_CODES:
        # "…failed with the following error: 'Incorrect syntax near '>'.'" — the quoted part
        # is the actual error, and it's what tells this wrapper's causes apart.
        core = re.sub(r"(following error:\s*)'(.*)'\s*$", r"\1\2", core, flags=re.S)
    return _Parsed(code, types[-1].split(".")[-1] if types else None, core)


_SPARK_STAGE_WRAPPER = re.compile(
    r"Job aborted due to stage failure:.*?\(TID \d+\)(?: \([^)]*\))?:\s*", re.S
)


def _parse_spark(message: str, error_code: str | None) -> _Parsed:
    msg = _SPARK_STAGE_WRAPPER.sub("", message)
    msg = re.sub(r"\s*SQLSTATE:\s*\w+\.?", "", re.split(r"\n?== SQL ==", msg)[0])
    error_class = re.search(r"\[([A-Z][A-Z0-9_]+(?:\.[A-Z0-9_]+)*)\]", msg)
    exception = re.search(r"\b(?:[a-z]+\.)*([A-Z]\w*(?:Exception|Error))\s*:", msg)
    if error_class:
        code, core = error_class.group(1), msg[error_class.end() :]
    else:
        cluster = re.search(r"Cluster terminated\. Reason:\s*([\w ]+)", msg)
        code = (
            cluster.group(1).strip().replace(" ", "_")
            if cluster
            else (error_code if error_code and not _is_numeric(error_code) else None)
        )
        core = msg[exception.end() :] if exception else msg
    return _Parsed(code, exception.group(1) if exception else None, core.strip(" :\n"))


_DBT_HEADER = re.compile(
    r"(Database|Compilation|Runtime|Parsing|Dependency)\s+Error\s+in\s+"
    r"(?:model|test|macro|seed|snapshot|source)\s+[\w.]+\s*(?:\([^)]+\))?",
    re.I,
)
_WAREHOUSE_CODE = re.compile(r"\b(\d{6}) \(\w{5}\)|\b(ORA-\d{5})\b")


def _parse_dbt(message: str, error_code: str | None) -> _Parsed:
    msg = re.sub(r"^\s*\d{2}:\d{2}:\d{2}\s*", "", message, flags=re.M)
    msg = re.split(r"\n\s*compiled (?:Code|SQL) at ", msg, flags=re.I)[0]
    header = _DBT_HEADER.search(msg)
    if header:
        error_type, core = f"dbt_{header.group(1).lower()}_error", msg[header.end() :]
    else:
        error_type, core = (
            ("dbt_test_failure" if "Failure in test" in msg else None),
            msg,
        )
    warehouse = _WAREHOUSE_CODE.search(core)
    code = (warehouse.group(1) or warehouse.group(2)) if warehouse else error_code
    return _Parsed(code, error_type, core.strip())


_GENERIC_CODES = (
    re.compile(r"\b(ORA-\d{5})\b"),
    re.compile(r"\b(\d{6}) \(\w{5}\)"),
    re.compile(r"err code:\s*(\d+)", re.I),
    re.compile(r"SQLSTATE[=: ]\s*(\w{5})", re.I),
    re.compile(
        r"\b(4\d\d|5\d\d)\s+(?:Too Many|Unauthorized|Forbidden|Not Found|Internal|Bad)",
        re.I,
    ),
)


def _parse_generic(message: str, error_code: str | None) -> _Parsed:
    """Fivetran, Matillion and platforms without a dedicated parser: pass-through source and
    driver messages, where a warehouse/driver code is the best identifier available."""
    code = error_code
    for pattern in _GENERIC_CODES:
        if code:
            break
        found = pattern.search(message)
        code = found.group(1) if found else None
    exception = re.search(r"\b(?:[a-z]+\.)*([A-Z]\w*(?:Exception|Error))\b", message)
    return _Parsed(code, exception.group(1) if exception else None, message)


_PARSERS = {
    "adf": _parse_azure,
    "synapse": _parse_azure,
    "fabric": _parse_azure,
    "databricks": _parse_spark,
    "dbt": _parse_dbt,
}

# Codes that wrap many unrelated causes: identity comes from the fingerprint, not the code.
_GENERIC_WRAPPER_CODES = frozenset(
    {
        "UserErrorOdbcOperationFailed",
        "SqlOperationFailed",
        "AdlsGen2OperationFailed",
        "UserErrorFailedFileOperation",
        "UserErrorHttpStatusCodeIndicatingFailure",
        "RestCallFailedWithClientError",
        "RestCallFailedWithServerError",
        "UserErrorFailedToConnectOdbcSource",
        "JobFailed",
    }
)


def _unwrap_json(message: str) -> tuple[str | None, str]:
    """Some platforms return the error as a JSON body ({"error": {"code", "message"}})."""
    stripped = message.strip()
    if not stripped.startswith("{"):
        return None, message
    try:
        body = json.loads(stripped)
    except ValueError:
        return None, message
    inner = body.get("error", body) if isinstance(body, dict) else {}
    if not isinstance(inner, dict):
        return None, message
    code = inner.get("code") or inner.get("errorCode") or inner.get("StatusCode")
    text = inner.get("message") or inner.get("Message") or message
    return (str(code) if code else None), str(text)


# --------------------------------------------------------------------------- public API


@dataclass(frozen=True)
class Signature:
    platform: str
    code: str | None
    error_type: str | None
    outer_code: str | None
    template: str
    values: dict[str, list[str]]
    fingerprint: str

    @property
    def is_generic(self) -> bool:
        return (
            not self.code
            or _is_numeric(self.code)
            or self.code in _GENERIC_WRAPPER_CODES
        )

    @property
    def identity(self) -> str:
        """What a failure pattern is matched on: the specific code, or the fingerprint when
        the code alone can't tell causes apart."""
        return self.fingerprint if self.is_generic else f"{self.platform}:{self.code}"


def summarize(template: str, values: dict[str, list[str]]) -> str:
    """The template's first sentence with its real values put back: a readable one-line error
    without the wrapper noise ("Column 'ID' specified in column mapping cannot be found...")."""
    queues = {kind: list(found) for kind, found in values.items()}

    def fill(match: re.Match) -> str:
        queue = queues.get(match.group(1))
        if not queue:
            return match.group(0)
        value = queue.pop(0)
        return f"'{value}'" if match.group(1) == "NAME" else value

    return re.sub(r"<(\w+)>", fill, _head(template))


def parse(
    platform: str, error_code: str | None, message: str | None
) -> Signature | None:
    """None when there's nothing to parse (no message and no code)."""
    if not message and not error_code:
        return None
    platform = platform.lower()
    json_code, text = _unwrap_json(message or "")
    parsed = _PARSERS.get(platform, _parse_generic)(text, json_code or error_code)
    template, values = _mask(parsed.core or text)
    # An inner "ErrorCode: X" past the first sentence (ADLS) still tells causes apart.
    inner_codes = ",".join(re.findall(r"ErrorCode: (\w+)", template))
    digest = (
        f"{platform}|{parsed.code}|{parsed.error_type}|{_head(template)}|{inner_codes}"
    )
    return Signature(
        platform=platform,
        code=parsed.code,
        error_type=parsed.error_type,
        outer_code=error_code if _is_numeric(error_code) else None,
        template=template,
        values=values,
        fingerprint=hashlib.sha256(digest.encode()).hexdigest()[:16],
    )
