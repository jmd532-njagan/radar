"""Signature parsing against real platform error messages (taken from the error corpus)."""

from intake.signature import parse

ADF_MAPPING = (
    "ErrorCode=MappingColumnNameNotFoundInSourceFile,'Type=Microsoft.DataTransfer.Common.Shared."
    "HybridDeliveryException,Message=Column '{col}' specified in column mapping cannot be found in "
    "'mcp_test/customers.csv' source file.,Source=Microsoft.DataTransfer.ClientLibrary,'"
)


def test_adf_specific_code_is_the_identity_and_values_are_masked():
    a = parse("adf", "2200", ADF_MAPPING.format(col="ID"))
    b = parse("adf", "2200", ADF_MAPPING.format(col="ID_subham"))
    assert a.code == "MappingColumnNameNotFoundInSourceFile"
    assert a.error_type == "HybridDeliveryException"
    assert a.outer_code == "2200"
    assert (
        a.template
        == "Column <NAME> specified in column mapping cannot be found in <NAME> source file."
    )
    assert a.values["NAME"] == ["ID", "mcp_test/customers.csv"]
    assert a.identity == b.identity == "adf:MappingColumnNameNotFoundInSourceFile"
    assert a.fingerprint == b.fingerprint


def test_adf_nested_wrappers_and_doubled_quotes():
    sig = parse(
        "adf",
        "2200",
        "Operation on target Load_Sales failed: Operation on target Copy_Customers failed: "
        "Failure happened on 'Source' side. ErrorCode=TypeConversionFailure,Exception occurred when "
        "converting value '' for column name ''EndDate'' from type ''String'' (precision:, scale:) to "
        "type ''DateTime'' (precision:255, scale:255). Additional info: String was not recognized.",
    )
    assert sig.code == "TypeConversionFailure"
    assert not sig.is_generic
    assert "<NAME>" in sig.template and "EndDate" not in sig.template
    assert "Load_Sales" not in sig.template


def test_generic_wrapper_code_is_told_apart_by_fingerprint():
    relation = parse(
        "adf",
        "2200",
        "ErrorCode=UserErrorOdbcOperationFailed,'Type=Microsoft.DataTransfer.Common.Shared."
        'HybridDeliveryException,Message=ERROR [42P01] ERROR: relation "sales.orders" does not exist,'
        "Source=Microsoft.DataTransfer.Runtime.GenericOdbcConnectors,'",
    )
    denied = parse(
        "adf",
        "2200",
        "ErrorCode=UserErrorOdbcOperationFailed,'Type=Microsoft.DataTransfer.Common.Shared."
        "HybridDeliveryException,Message=ERROR [08001] Failed to access remote file: access denied.,"
        "Source=Microsoft.DataTransfer.Runtime.GenericOdbcConnectors,'",
    )
    assert relation.is_generic and denied.is_generic
    assert relation.identity == relation.fingerprint
    assert relation.identity != denied.identity


def test_json_error_body():
    sig = parse(
        "adf",
        "2108",
        '{"error":{"code":"BadParameter","message":"Property has invalid value\\r\\n"}}',
    )
    assert sig.code == "BadParameter"
    assert sig.template.startswith("Property has invalid value")


def test_spark_error_class_survives_rewording_between_versions():
    old = parse(
        "databricks",
        None,
        "AnalysisException: [UNRESOLVED_COLUMN.WITH_SUGGESTION] A column or function parameter with "
        "name `amount` cannot be resolved. Did you mean one of the following? [`id`, `total`]. SQLSTATE: 42703",
    )
    new = parse(
        "databricks",
        None,
        "[UNRESOLVED_COLUMN.WITH_SUGGESTION] A column, variable, or function parameter with name "
        "`graduate_program` cannot be resolved. Did you mean one of the following? [degree, id].",
    )
    assert old.code == new.code == "UNRESOLVED_COLUMN.WITH_SUGGESTION"
    assert old.error_type == "AnalysisException"
    assert old.identity == new.identity
    assert "SQLSTATE" not in old.template


def test_dbt_error_kind_and_warehouse_code():
    sig = parse(
        "dbt",
        None,
        "Database Error in model stg_orders (models/staging/stg_orders.sql)\n"
        "  001003 (42000): SQL compilation error:\n  syntax error line 12 at position 4 unexpected 'from'.\n"
        "  compiled Code at target/run/proj/models/staging/stg_orders.sql",
    )
    assert sig.error_type == "dbt_database_error"
    assert sig.code == "001003"
    assert "stg_orders" not in sig.template


def test_generic_platform_and_empty_input():
    sig = parse("fivetran", None, "ORA-01017: invalid username/password; logon denied")
    assert sig.code == "ORA-01017"
    assert parse("adf", None, None) is None
