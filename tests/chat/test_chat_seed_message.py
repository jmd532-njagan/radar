from dataclasses import asdict
from datetime import UTC, datetime

from chat.notification import build_seed_message
from db.failure_patterns import PatternHistory
from db.models import FailureEvent, FailurePattern
from intake.signature import parse

_MESSAGE = (
    "ErrorCode=MappingColumnNameNotFoundInSourceFile,'Type=Microsoft.DataTransfer.Common.Shared."
    "HybridDeliveryException,Message=Column 'ID' specified in column mapping cannot be found in "
    "'mcp_test/customers.csv' source file.,Source=Microsoft.DataTransfer.ClientLibrary,'"
)


def _event() -> FailureEvent:
    return FailureEvent(
        pipeline_name="pl_copy_customers",
        last_error=_MESSAGE,
        start_time=datetime(2026, 9, 25, 17, 20, tzinfo=UTC),
        end_time=datetime(2026, 9, 25, 17, 24, tzinfo=UTC),
        signature=asdict(parse("adf", "2200", _MESSAGE)),
    )


def test_first_occurrence_is_readable_and_drops_the_wrapper_noise():
    text = build_seed_message(_event(), None, None)
    assert text.startswith(
        "`pl_copy_customers` failed at 25 Sep 17:24 UTC: Column 'ID' specified in column mapping "
        "cannot be found in 'mcp_test/customers.csv' source file"
    )
    assert "HybridDeliveryException" not in text
    assert "First time this error has been seen" in text


def test_known_pattern_with_cause_and_fix():
    pattern = FailurePattern(
        id=12,
        category="schema_drift",
        cause="Source CSV header no longer has the mapped column.",
        fix_actions=["update_copy_mapping", "rerun_pipeline"],
    )
    text = build_seed_message(_event(), pattern, PatternHistory(3, None, None))
    assert "Matches failure pattern FP-12, seen 3× before (schema drift)" in text
    assert "Known cause: Source CSV header no longer has the mapped column." in text
    assert "Usual fix: update_copy_mapping, rerun_pipeline." in text


def test_known_pattern_without_diagnosis_and_no_signature():
    event = _event()
    event.signature, event.last_error = None, "Something broke"
    text = build_seed_message(
        event, FailurePattern(id=4, fix_actions=[]), PatternHistory(1, None, None)
    )
    assert "failed at 25 Sep 17:24 UTC: Something broke" in text
    assert "seen 1× before, no diagnosis recorded yet." in text
