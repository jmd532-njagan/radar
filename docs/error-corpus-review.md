# Real-world pipeline error corpus — signature review

345 real error messages from 7 platforms (official docs, Microsoft Q&A, Databricks KB, Stack Overflow,
Fivetran/Matillion docs and forums), collected 2026-09-26, and what RADAR's prototype signature
extractor pulls out of each. Use it to review two things: whether the **corpus** is representative,
and whether the **extraction** is right. Source URL per message is in `errors.jsonl` (session scratchpad
`corpus/`). Messages are verbatim except where the collector noted soft line-wraps were joined.

## How to read an entry

- **message**: the error as the platform reports it (trimmed to 600 characters here).
- **code**: the specific error code/class found (ADF inner `ErrorCode=`, Spark `[ERROR_CLASS]`, …). `—` = none found.
- **type**: exception / error kind (`HybridDeliveryException`, `AnalysisException`, `dbt_database_error`).
- **template**: the message with variable values masked: `<NAME>` quoted or identifier-like names, `<PATH>`, `<URL>`,
  `<ID>` GUIDs, `<TS>` timestamps, `<NUM>`, `<LIST>` bracketed lists, `<EMAIL>`, `<IP>`, `<HEX>`.
- **values**: what got masked (kept separately, useful for diagnosing that occurrence).
- **fp**: fingerprint (platform + code + type + first sentence of the template). `×N` = N corpus messages share it.

## Results

| Platform | Messages | Specific code found | Notes |
|---|---|---|---|
| adf | 130 | 107 (82%) | inner `ErrorCode=` token; numeric 2200/2108/… kept only as outer code |
| synapse | 29 | 16 (55%) | same format as ADF; Spark-pool (Livy) failures carry no code |
| fabric | 16 | 13 (81%) | copy errors like ADF; notebook errors use `Error name - X` |
| databricks | 61 | 52 (85%) | Spark `[ERROR_CLASS.SUB]`; version wording differs, so match on the class |
| dbt | 53 | 0 (0%) | no codes: kind (`Database Error in model`) + warehouse message; match by type + template |
| fivetran | 32 | 2 (6%) | pass-through source/driver messages; match by template/keywords |
| matillion | 24 | 0 (0%) | pass-through warehouse/driver/Python errors; match by template/keywords |

Overall: 345 messages → 297 distinct fingerprints, 113 distinct (platform, code). Masking leaves digits in
2 templates; 1 fingerprint collision (a Synapse message with and without its numeric code).

**Key finding for matching.** Codes come in two kinds:

- **Specific codes** (e.g. ADF `TypeConversionFailure`, `DelimitedTextMoreColumnsThanDefined`; Spark
  `UNRESOLVED_COLUMN.WITH_SUGGESTION`): the code alone identifies the error. The same code can be worded
  differently across versions (Spark says "column or function parameter" in one release and "column,
  variable, or function parameter" in another), so match on the code, not the full template.
- **Generic wrapper codes** (ADF `2200`, `UserErrorOdbcOperationFailed`, `SqlOperationFailed`,
  `AdlsGen2OperationFailed`, `UserErrorFailedFileOperation`, HTTP status failures): the code wraps many
  unrelated causes ("relation does not exist", "syntax error", "access denied" all arrive as
  `UserErrorOdbcOperationFailed`), so the fingerprint (code + template) is what tells them apart.
- **No code at all** (dbt, Fivetran, Matillion, Synapse Spark pools): type + template + keywords.

## Use for the reranker

Messages that share a fingerprint, or share a specific code, are **positive pairs** (the same failure worded
with different values); messages from different codes are negatives. That gives a labelled set to measure the
search → rerank step: query with one message, check the others in its group rank at the top. Fingerprint
groups with ×2 or more are marked below.

## adf (130)

### — (23)

**1.** given code `—`

```text
Failure happened on 'Source' side. 'Type=Microsoft.Data.SqlClient.SqlException,Message=111202;Query QID67099467 has been cancelled.\r\nCannot continue the execution because the session is in the kill state.\r\nA severe error occurred on the current command. The results, if any, should be discarded.,Source=Framework Microsoft SqlClient Data Provider,'
```

- **type** `SqlException` · **fp** `f9840b134725392b`
- **template** `<NUM>;Query <NAME> has been cancelled. Cannot continue the execution because the session is in the kill state. A severe error occurred on the current command. The results, if any, should be discarded.`
- **values** NAME: QID67099467; NUM: 111202
- **keywords** query, cancelled, cannot, continue, execution, because, session, kill

**2.** given code `—`

```text
Failure happened on 'Source' side. 'Type=System.Collections.Generic.KeyNotFoundException,Message=The given key was not present in the dictionary.,Source=mscorlib
```

- **type** `KeyNotFoundException` · **fp** `ee835a203aea85cc`
- **template** `The given key was not present in the dictionary.`
- **values** —
- **keywords** given, key, present, dictionary

**3.** given code `2108`

```text
{"error":{"code":"BadParameter","message":"Property has invalid value\r\n"}}
```

- **type** `—` · **fp** `b9ceabdd08febaf5`
- **template** `{<NAME>:{<NAME>:<NAME>:<NAME>}}`
- **values** NAME: error, code, BadParameter, message …
- **keywords** —

**4.** given code `2108`

```text
Invoking Web Activity failed with HttpStatusCode - '401 : Unauthorized', message - ''
```

- **type** `—` · **fp** `33ea1738bf0642cb`
- **template** `Invoking Web Activity failed with HttpStatusCode - <NAME>, message - <NAME>`
- **values** NAME: 401 : Unauthorized, 
- **keywords** invoking, web, activity, httpstatuscode

**5.** given code `2402`

```text
Execution failed against SQL Server. SQL error number: 13609. Error Message: JSON text is not properly formatted. Unexpected character 'S' is found at position 0.
```

- **type** `—` · **fp** `cd6727b60c1aa95e`
- **template** `Execution failed against SQL Server. SQL error number: <NUM>. Error Message: JSON text is not properly formatted. Unexpected character <NAME> is found at position <NUM>.`
- **values** NAME: S; NUM: 13609, 0
- **keywords** execution, against, sql, server, number, json, text, properly

**6.** given code `2402`

```text
Execution fail against SQL Server. SQL error number: 40197. Error Message: The service has encountered an error processing your request. Please try again. Error code 9001. A severe error occurred on the current command. The results, if any, should be discarded.
```

- **type** `—` · **fp** `efde6915e6945835`
- **template** `Execution fail against SQL Server. SQL error number: <NUM>. Error Message: The service has encountered an error processing your request. Please try again. Error code <NUM>. A severe error occurred on the current command. The results, if any, should be discarded.`
- **values** NUM: 40197, 9001
- **keywords** execution, against, sql, server, number, service, encountered, processing

**7.** given code `—`

```text
Activity MyCustomActivity failed: Can not access user batch account, please check batch account setiings.
```

- **type** `—` · **fp** `d5e3358c6de18a70`
- **template** `Activity MyCustomActivity failed: Can not access user batch account, please check batch account setiings.`
- **values** —
- **keywords** activity, mycustomactivity, can, access, user, batch, account, setiings

**8.** given code `—`

```text
A database operation failed with the following error: 'Parse error at line: 2, column: 1: Incorrect syntax near 'SELECT'.',Source=,''Type=System.Data.SqlClient.SqlException,Message=Parse error at line: 2, column: 1: Incorrect syntax near 'SELECT'.,Source=.Net SqlClient Data Provider,SqlErrorNumber=103010,Class=16,ErrorCode=-2146232060,State=1
```

- **type** `SqlException` · **fp** `6cc67fdedb3eabdd`
- **template** `Parse error at line: <NUM>, column: <NUM>: Incorrect syntax near <NAME>.`
- **values** NAME: SELECT; NUM: 2, 1
- **keywords** parse, line, column, incorrect, syntax, near

**9.** given code `—`

```text
A database operation failed with the following error: 'Incorrect syntax near '@concat'.',Source=,''Type=System.Data.SqlClient.SqlException,Message=Incorrect syntax near '@concat'.,Source=.Net SqlClient Data Provider,SqlErrorNumber=102,Class=15,ErrorCode=-2146232060,State=1,Errors= [{Class=15,Number=102,State=1,Message=Incorrect syntax near '@concat'.,},],'
```

- **type** `SqlException` · **fp** `a54e8218bd82634b`
- **template** `Incorrect syntax near <NAME>.`
- **values** NAME: @concat
- **keywords** incorrect, syntax, near

**10.** given code `—`

```text
Job failed due to reason: at Sink 'sinksource'(Line 17/Col 12): Column operands are not allowed in literal expressions
```

- **type** `—` · **fp** `503a89971f575aff`
- **template** `Job failed due to reason: at Sink <NAME>(Line <PATH> <NUM>): Column operands are not allowed in literal expressions`
- **values** NAME: sinksource; PATH: 17/Col; NUM: 12
- **keywords** job, due, reason, sink, line, column, operands, allowed

**11.** given code `—`

```text
Job failed due to reason: at Sink 'sink1': SQL compilation error: error line 1 at position 22 invalid identifier '"Employee_ID"'
```

- **type** `—` · **fp** `27afe675a56ff12b`
- **template** `Job failed due to reason: at Sink <NAME>: SQL compilation error: error line <NUM> at position <NUM> invalid identifier <NAME>`
- **values** NAME: sink1, Employee_ID; NUM: 1, 22
- **keywords** job, due, reason, sink, sql, compilation, line, position

**12.** given code `—`

```text
Job failed due to reason: at Source 'Ingestion'(Line 7/Col 0): Key partitioning does not allow computed columns
```

- **type** `—` · **fp** `73a2104c3863371e`
- **template** `Job failed due to reason: at Source <NAME>(Line <PATH> <NUM>): Key partitioning does not allow computed columns`
- **values** NAME: Ingestion; PATH: 7/Col; NUM: 0
- **keywords** job, due, reason, line, key, partitioning, does, allow

**13.** given code `—`

```text
Job failed due to reason: at Source 'srcIICSrest': Illegal character in query at index 42: /saas//api/v2/activity/activityLog?offset={offset}
```

- **type** `—` · **fp** `9463b34eb3e4c306`
- **template** `Job failed due to reason: at Source <NAME>: Illegal character in query at index <NUM>: /saas//<PATH>?offset={offset}`
- **values** NAME: srcIICSrest; PATH: api/v2/activity/activityLog; NUM: 42
- **keywords** job, due, reason, illegal, character, query, index, saas

**14.** given code `—`

```text
Failed to get the secret from key vault, secretName: *********, secretVersion: , vaultBaseUrl:*****************. The error message is: An error occurred while sending the request. The underlying connection was closed: Could not establish trust relationship for the SSL/TLS secure channel. The remote certificate is invalid according to the validation procedure.
```

- **type** `—` · **fp** `992e9dd6381c8d08`
- **template** `Failed to get the secret from key vault, secretName: *********, secretVersion: , vaultBaseUrl:*****************. The error message is: An error occurred while sending the request. The underlying connection was closed: Could not establish trust relationship for the <PATH> secure channel. The remote c`
- **values** PATH: SSL/TLS
- **keywords** get, secret, key, vault, secretname, secretversion, vaultbaseurl, occurred

**15.** given code `—`

```text
Run result unavailable: job failed with error message Library installation failed for library due to user error for jar: "dbfs:/mnt/mopireport/TeamsAnalyticsCore-v9.jar" . Error messages: Library installation attempted on the driver node of cluster 0805-090147-ulpmkivi and failed. Please refer to the following error message to fix the library or contact Databricks support. Error Code: DRIVER_LIBRARY_INSTALLATION_FAILURE. Error Message: java.lang.Throwable: shaded.databricks.org.apache.hadoop.fs.azure.AzureException: com.microsoft.azure.storage.StorageException: This request is not authorized t …
```

- **type** `—` · **fp** `171eeb376616a9ec`
- **template** `Run result unavailable: job failed with error message Library installation failed for library due to user error for jar: <NAME> . Error messages: Library installation attempted on the driver node of cluster <NUM>-<NUM>-ulpmkivi and failed. Please refer to the following error message to fix the libra`
- **values** NAME: dbfs:/mnt/mopireport/TeamsAnalyticsCore-v9.jar, DRIVER_LIBRARY_INSTALLATION_FAILURE; NUM: 0805, 090147
- **keywords** run, result, unavailable, job, library, installation, due, user

**16.** given code `—`

```text
Run result unavailable: job failed with error message  Library installation failed for library due to user error for whl: "dbfs:/FileStore/jars/ephem-4.1.3-cp38-cp38-manylinux_2_17_x86_64.manylinux2014_x86_64.whl" . Error messages: Library installation attempted on the driver node of cluster 1226-023738-9cm6lm7d and failed. Please refer to the following error message to fix the library or contact Databricks support.
```

- **type** `—` · **fp** `edbc16d6514b0d03`
- **template** `Run result unavailable: job failed with error message Library installation failed for library due to user error for whl: <NAME> . Error messages: Library installation attempted on the driver node of cluster <NUM>-<NUM>-<NAME> and failed. Please refer to the following error message to fix the library`
- **values** NAME: dbfs:/FileStore/jars/ephem-4.1.3-cp38-cp38-manylinux_2_17_x86_64.manylinux2014_x86_64.whl, 9cm6lm7d; NUM: 1226, 023738
- **keywords** run, result, unavailable, job, library, installation, due, user

**17.** given code `—`

```text
Operation on target ForEach1 failed: Activity failed because an inner activity failed; Inner activity name: CopyFromSourcetoADLS, Error: The Self-hosted Integration Runtime 'integrationRuntime-edw' is offline, last connect time is '06/07/2024 05:12:00.455 UTC', Self-hosted Integration Runtime id is '5cbb97a6-c6bd-4073-bb78-b4a3e505acb1'.
```

- **type** `—` · **fp** `31004ec4c51c522d` ×3
- **template** `The Self-hosted Integration Runtime <NAME> is offline, last connect time is <NAME>, Self-hosted Integration Runtime id is <NAME>.`
- **values** ID: 5cbb97a6-c6bd-4073-bb78-b4a3e505acb1; TS: 06/07/2024 05:12:00; NAME: integrationRuntime-edw, <TS>.455 UTC, <ID>
- **keywords** self, hosted, integration, runtime, offline, last, connect, time

**18.** given code `—`

```text
The Self-hosted Integration Runtime 'IR-VM' is offline, last connect time is '05/18/2022 23:59:59.182', Self-hosted Integration Runtime id is....
```

- **type** `—` · **fp** `31004ec4c51c522d` ×3
- **template** `The Self-hosted Integration Runtime <NAME> is offline, last connect time is <NAME>, Self-hosted Integration Runtime id is....`
- **values** TS: 05/18/2022 23:59:59; NAME: IR-VM, <TS>.182
- **keywords** self, hosted, integration, runtime, offline, last, connect, time

**19.** given code `—`

```text
The Self-hosted Integration Runtime 'IRSAP' is offline, last connect time is '11/21/2022 02:27:02.340 UTC', Self-hosted Integration Runtime id is 'xxxxxxxxxxxxxxx'.
```

- **type** `—` · **fp** `31004ec4c51c522d` ×3
- **template** `The Self-hosted Integration Runtime <NAME> is offline, last connect time is <NAME>, Self-hosted Integration Runtime id is <NAME>.`
- **values** TS: 11/21/2022 02:27:02; NAME: IRSAP, <TS>.340 UTC, xxxxxxxxxxxxxxx
- **keywords** self, hosted, integration, runtime, offline, last, connect, time

**20.** given code `2906`

```text
ConnectByProxy: Process data from proxy to pipeline buffer fail since error: Timeout when reading from staging. TaskStatus: Failed, ErrorCode: 2906, ErrorMessage: Package execution failed. For more details, select the output of your activity run on the same row.
```

- **type** `—` · **fp** `884e5f3fc595f501`
- **template** `ConnectByProxy: Process data from proxy to pipeline buffer fail since error: Timeout when reading from staging. TaskStatus: Failed, ErrorCode: <NUM>, ErrorMessage: Package execution failed. For more details, select the output of your activity run on the same row.`
- **values** NUM: 2906
- **keywords** connectbyproxy, process, proxy, pipeline, buffer, since, timeout, when

**21.** given code `3208`

```text
An error occurred while sending the request.
```

- **type** `—` · **fp** `076c8da69f997c5d`
- **template** `An error occurred while sending the request.`
- **values** —
- **keywords** occurred, while, sending, request

**22.** given code `3204`

```text
Caused by: com.databricks.NotebookExecutionException: FAILED
```

- **type** `—` · **fp** `8fb9ecce16eb6062`
- **template** `Caused by: com.databricks.NotebookExecutionException: FAILED`
- **values** —
- **keywords** caused, com, databricks, notebookexecutionexception

**23.** given code `2200`

```text
'Type=System.Net.Http.HttpRequestException,Message=An error occurred while sending the request.,Source=mscorlib,''Type=System.Net.WebException,Message=The underlying connection was closed: An unexpected error occurred on a send.,Source=System,''Type=System.IO.IOException,Message=Authentication failed because the remote party has closed the transport stream.,Source=System,'
```

- **type** `IOException` · **fp** `1ebd18810d121be3`
- **template** `An error occurred while sending the request.`
- **values** —
- **keywords** occurred, while, sending, request

### TypeConversionFailure (9)

**1.** given code `TypeConversionFailure`

```text
ErrorCode=TypeConversionFailure,Exception occurred when converting value '' for column name 'xyz' from type 'String' (precision:, scale:) to type 'Decimal' (precision:18, scale:0). Additional info: The input wasn't in a correct format.
```

- **type** `—` · **fp** `fe302989d83234a1` ×9
- **template** `ErrorCode=TypeConversionFailure,Exception occurred when converting value <NAME> for column name <NAME> from type <NAME> (precision:, scale:) to type <NAME> (precision:<NUM>, scale:<NUM>). Additional info: The input wasn't in a correct format.`
- **values** NAME: , xyz, String, Decimal; NUM: 18, 0
- **keywords** type, conversion, failure, errorcode, typeconversionfailure, occurred, when, converting

**2.** given code `TypeConversionFailure`

```text
ErrorCode=TypeConversionFailure,Exception occurred when converting value '+44 07878 44444' for column name 'telephone2' from type 'String' (precision:255, scale:255) to type 'Double' (precision:15, scale:255). Additional info: Input string was not in a correct format.
```

- **type** `—` · **fp** `fe302989d83234a1` ×9
- **template** `ErrorCode=TypeConversionFailure,Exception occurred when converting value <NAME> for column name <NAME> from type <NAME> (precision:<NUM>, scale:<NUM>) to type <NAME> (precision:<NUM>, scale:<NUM>). Additional info: Input string was not in a correct format.`
- **values** NAME: +44 07878 44444, telephone2, String, Double; NUM: 255, 255, 15, 255
- **keywords** type, conversion, failure, errorcode, typeconversionfailure, occurred, when, converting

**3.** given code `TypeConversionFailure`

```text
ErrorCode=TypeConversionFailure,Exception occurred when converting value '' for column name 'EndDate' from type 'String' (precision:, scale:) to type 'DateTime' (precision:255, scale:255). Additional info: String was not recognized as a valid DateTime.
```

- **type** `—` · **fp** `fe302989d83234a1` ×9
- **template** `ErrorCode=TypeConversionFailure,Exception occurred when converting value <NAME> for column name <NAME> from type <NAME> (precision:, scale:) to type <NAME> (precision:<NUM>, scale:<NUM>). Additional info: String was not recognized as a valid DateTime.`
- **values** NAME: , EndDate, String, DateTime; NUM: 255, 255
- **keywords** type, conversion, failure, errorcode, typeconversionfailure, occurred, when, converting

**4.** given code `TypeConversionFailure`

```text
ErrorCode=TypeConversionFailure,Exception occurred when converting value '' for column name 'ContractID' from type 'String' (precision:, scale:) to type 'Guid' (precision:255, scale:255). Additional info: Unrecognized Guid format.
```

- **type** `—` · **fp** `fe302989d83234a1` ×9
- **template** `ErrorCode=TypeConversionFailure,Exception occurred when converting value <NAME> for column name <NAME> from type <NAME> (precision:, scale:) to type <NAME> (precision:<NUM>, scale:<NUM>). Additional info: Unrecognized Guid format.`
- **values** NAME: , ContractID, String, Guid; NUM: 255, 255
- **keywords** type, conversion, failure, errorcode, typeconversionfailure, occurred, when, converting

**5.** given code `TypeConversionFailure`

```text
ErrorCode=TypeConversionFailure,Exception occurred when converting value '23:55' for column name 'systime' from type 'String' (precision:, scale:) to type 'TimeSpan' (precision:255, scale:7). Additional info: Input string was not in a correct format.
```

- **type** `—` · **fp** `fe302989d83234a1` ×9
- **template** `ErrorCode=TypeConversionFailure,Exception occurred when converting value <NAME> for column name <NAME> from type <NAME> (precision:, scale:) to type <NAME> (precision:<NUM>, scale:<NUM>). Additional info: Input string was not in a correct format.`
- **values** NAME: 23:55, systime, String, TimeSpan; NUM: 255, 7
- **keywords** type, conversion, failure, errorcode, typeconversionfailure, occurred, when, converting

**6.** given code `TypeConversionFailure`

```text
ErrorCode=TypeConversionFailure,Exception occurred when converting value '' for column name 'clearingHouseContactTelephoneNumber' from type 'String' (precision:, scale:) to type 'Decimal' (precision:10, scale:0). Additional info: The input wasn't in a correct format.
```

- **type** `—` · **fp** `fe302989d83234a1` ×9
- **template** `ErrorCode=TypeConversionFailure,Exception occurred when converting value <NAME> for column name <NAME> from type <NAME> (precision:, scale:) to type <NAME> (precision:<NUM>, scale:<NUM>). Additional info: The input wasn't in a correct format.`
- **values** NAME: , clearingHouseContactTelephoneNumber, String, Decimal; NUM: 10, 0
- **keywords** type, conversion, failure, errorcode, typeconversionfailure, occurred, when, converting

**7.** given code `TypeConversionFailure`

```text
Operation on target Copy data into Target failed: ErrorCode=TypeConversionFailure,Exception occurred when converting value '2150002867256' for column name 'sourceKey' from type 'String' (precision:255, scale:255) to type 'Int32' (precision:, scale:). Additional info: Value was either too large or too small for an Int32.
```

- **type** `—` · **fp** `fe302989d83234a1` ×9
- **template** `ErrorCode=TypeConversionFailure,Exception occurred when converting value <NAME> for column name <NAME> from type <NAME> (precision:<NUM>, scale:<NUM>) to type <NAME> (precision:, scale:). Additional info: Value was either too large or too small for an <NAME>.`
- **values** NAME: 2150002867256, sourceKey, String, Int32 …; NUM: 255, 255
- **keywords** type, conversion, failure, errorcode, typeconversionfailure, occurred, when, converting

**8.** given code `TypeConversionFailure`

```text
ErrorCode=TypeConversionFailure,Exception occurred when converting value '28/10/2024' for column name 'DATE' from type 'String' (precision:, scale:) to type 'DateTime' (precision:255, scale:255). Additional info: String was not recognized as a valid DateTime.
```

- **type** `—` · **fp** `fe302989d83234a1` ×9
- **template** `ErrorCode=TypeConversionFailure,Exception occurred when converting value <NAME> for column name <NAME> from type <NAME> (precision:, scale:) to type <NAME> (precision:<NUM>, scale:<NUM>). Additional info: String was not recognized as a valid DateTime.`
- **values** TS: 28/10/2024; NAME: <TS>, DATE, String, DateTime; NUM: 255, 255
- **keywords** type, conversion, failure, errorcode, typeconversionfailure, occurred, when, converting

**9.** given code `TypeConversionFailure`

```text
ErrorCode=TypeConversionFailure,Exception occurred when converting value '04-Apr-22 00:00:00' for column name 'DateTime' from type 'String' (precision:, scale:) to type 'DateTime' (precision:23, scale:3). Additional info: String was not recognized as a valid DateTime.
```

- **type** `—` · **fp** `fe302989d83234a1` ×9
- **template** `ErrorCode=TypeConversionFailure,Exception occurred when converting value <NAME> for column name <NAME> from type <NAME> (precision:, scale:) to type <NAME> (precision:<NUM>, scale:<NUM>). Additional info: String was not recognized as a valid DateTime.`
- **values** TS: 00:00:00; NAME: 04-Apr-22 <TS>, DateTime, String, DateTime; NUM: 23, 3
- **keywords** type, conversion, failure, errorcode, typeconversionfailure, occurred, when, converting

### UserErrorInvalidDataValue (8)

**1.** given code `UserErrorInvalidDataValue`

```text
ErrorCode=UserErrorInvalidDataValue,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=Column 'ABOR_CDOM_Seed_Datetime' contains an invalid value '2017-01-02T16:33:43.223Z'. Cannot convert '2017-01-02T16:33:43.223Z' to type 'DateTime' with format 'yyyy-MM-dd HH:mm:ss.fffffff'.,Source=Microsoft.DataTransfer.Common,''Type=System.FormatException,Message=String was not recognized as a valid DateTime.,Source=mscorlib,'
```

- **type** `FormatException` · **fp** `bdbdf44dd6a76b85` ×7
- **template** `Column <NAME> contains an invalid value <NAME>. Cannot convert <NAME> to type <NAME> with format <NAME>.`
- **values** TS: 2017-01-02T16:33:43.223Z, 2017-01-02T16:33:43.223Z; NAME: ABOR_CDOM_Seed_Datetime, <TS>, <TS>, DateTime …
- **keywords** user, error, invalid, data, value, column, contains, cannot

**2.** given code `UserErrorInvalidDataValue`

```text
Failure happened on 'Sink' side. ErrorCode=UserErrorInvalidDataValue,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=Column 'ETA' contains an invalid value '05-05-2020 8:00 pm'. Cannot convert '05-05-2020 8:00 pm' to type 'DateTime' with format 'dd-MM-yyyy hh:mm tt'.,Source=Microsoft.DataTransfer.Common,''Type=System.FormatException,Message=String was not recognized as a valid DateTime.,Source=mscorlib,'
```

- **type** `FormatException` · **fp** `bdbdf44dd6a76b85` ×7
- **template** `Column <NAME> contains an invalid value <NAME>. Cannot convert <NAME> to type <NAME> with format <NAME>.`
- **values** NAME: ETA, 05-05-2020 8:00 pm, 05-05-2020 8:00 pm, DateTime …
- **keywords** user, error, invalid, data, value, column, contains, cannot

**3.** given code `UserErrorInvalidDataValue`

```text
Copy activity encountered a user error at Sink:tcp:database.windows.net,1433 side: ErrorCode=UserErrorInvalidDataValue,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=Column 'createdDate' contains an invalid value '2016-07-13 15:24:58.000'. Cannot convert '2016-07-13 15:24:58.000' to type 'DateTime' with format 'yyyy-MM-dd HH:mm:ss.fffffff'.,Source=Microsoft.DataTransfer.Common,''Type=System.FormatException,Message=String was not recognized as a valid DateTime.,Source=mscorlib,'.
```

- **type** `FormatException` · **fp** `bdbdf44dd6a76b85` ×7
- **template** `Column <NAME> contains an invalid value <NAME>. Cannot convert <NAME> to type <NAME> with format <NAME>.`
- **values** TS: 2016-07-13 15:24:58.000, 2016-07-13 15:24:58.000; NAME: createdDate, <TS>, <TS>, DateTime …
- **keywords** user, error, invalid, data, value, column, contains, cannot

**4.** given code `UserErrorInvalidDataValue`

```text
ErrorCode=UserErrorInvalidDataValue,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=Column 'Longitude' contains an invalid value ''. Cannot convert '' to type 'Double'.,Source=Microsoft.DataTransfer.Common,''Type=System.FormatException,Message=Input string was not in a correct format.,Source=mscorlib,'
```

- **type** `FormatException` · **fp** `1308da581a9da011`
- **template** `Column <NAME> contains an invalid value <NAME><NAME>Double'.`
- **values** NAME: Longitude, . Cannot convert ,  to type 
- **keywords** user, error, invalid, data, value, column, contains, double

**5.** given code `UserErrorInvalidDataValue`

```text
Copy activity encountered a user error at Sink side: ErrorCode=UserErrorInvalidDataValue,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=Column 'data_event_time' contains an invalid value '2016-11-13T00:44:50.573Z'. Cannot convert '2016-11-13T00:44:50.573Z' to type 'DateTimeOffset' with format 'yyyy-MM-dd HH:mm:ss.fffffff zzz'.,Source=Microsoft.DataTransfer.Common,''Type=System.FormatException,Message=String was not recognized as a valid DateTime.,Source=mscorlib,'.
```

- **type** `FormatException` · **fp** `bdbdf44dd6a76b85` ×7
- **template** `Column <NAME> contains an invalid value <NAME>. Cannot convert <NAME> to type <NAME> with format <NAME>.`
- **values** TS: 2016-11-13T00:44:50.573Z, 2016-11-13T00:44:50.573Z; NAME: data_event_time, <TS>, <TS>, DateTimeOffset …
- **keywords** user, error, invalid, data, value, column, contains, cannot

**6.** given code `UserErrorInvalidDataValue`

```text
Copy activity encountered a user error: ErrorCode=UserErrorInvalidDataValue,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=Column 'CarbohydratesFactor' contains an invalid value ' '. Cannot convert ' ' to type 'Decimal'.,Source=Microsoft.DataTransfer.Common,''Type=System.FormatException,Message=Input string was not in a correct format.,Source=mscorlib,'.
```

- **type** `FormatException` · **fp** `bdbdf44dd6a76b85` ×7
- **template** `Column <NAME> contains an invalid value <NAME>. Cannot convert <NAME> to type <NAME>.`
- **values** NAME: CarbohydratesFactor,  ,  , Decimal
- **keywords** user, error, invalid, data, value, column, contains, cannot

**7.** given code `UserErrorInvalidDataValue`

```text
ErrorCode=UserErrorInvalidDataValue,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=Column 'REFERENCE_DATETIME' contains an invalid value '-832759015-05-24 00:00:00.000'. Cannot convert '-832759015-05-24 00:00:00.000' to type 'DateTime'.,Source=Microsoft.DataTransfer.DataContracts,''Type=System.FormatException,Message=String was not recognized as a valid DateTime.,Source=mscorlib,'
```

- **type** `FormatException` · **fp** `bdbdf44dd6a76b85` ×7
- **template** `Column <NAME> contains an invalid value <NAME>. Cannot convert <NAME> to type <NAME>.`
- **values** TS: 00:00:00.000, 00:00:00.000; NAME: REFERENCE_DATETIME, -832759015-05-24 <TS>, -832759015-05-24 <TS>, DateTime
- **keywords** user, error, invalid, data, value, column, contains, cannot

**8.** given code `UserErrorInvalidDataValue`

```text
Copy activity encountered a user error at Sink side: ErrorCode=UserErrorInvalidDataValue,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=Column 'Timestamp' contains an invalid value '11667'. Cannot convert '11667' to type 'DateTimeOffset'.,Source=Microsoft.DataTransfer.Common,''Type=System.FormatException,Message=String was not recognized as a valid DateTime.,Source=mscorlib,'.
```

- **type** `FormatException` · **fp** `bdbdf44dd6a76b85` ×7
- **template** `Column <NAME> contains an invalid value <NAME>. Cannot convert <NAME> to type <NAME>.`
- **values** NAME: Timestamp, 11667, 11667, DateTimeOffset
- **keywords** user, error, invalid, data, value, column, contains, cannot

### UserErrorOdbcOperationFailed (8)

**1.** given code `UserErrorOdbcOperationFailed`

```text
Failure happened on 'Sink' side. ErrorCode=UserErrorOdbcOperationFailed,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=ERROR [42P01] ERROR: relation "semantic_dev.dim_storage_location" does not exist;\nError while preparing parameters,Source=Microsoft.DataTransfer.ClientLibrary.Odbc.OdbcConnector,''Type=Microsoft.DataTransfer.ClientLibrary.Odbc.Exceptions.OdbcException,Message=ERROR [42P01] ERROR: relation "semantic_dev.dim_storage_location" does not exist;\nError while preparing parameters,Source=PSQLODBC35W.DLL
```

- **type** `OdbcException` · **fp** `121b48985db5d34f`
- **template** `ERROR <LIST> ERROR: relation <NAME> does not exist; Error while preparing parameters`
- **values** NAME: semantic_dev.dim_storage_location; LIST: [42P01]
- **keywords** user, error, odbc, operation, failed, relation, does, exist

**2.** given code `UserErrorOdbcOperationFailed`

```text
ErrorCode=UserErrorOdbcOperationFailed,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=ERROR [22000] Found character '`' instead of field delimiter ','\n  File 'staging/398e91a4-8147-4668-96ee-6645c73ae895/SnowflakeImportCopyCommand/data_398e91a4-8147-4668-96ee-6645c73ae895_e9a92264-b3ee-4cbe-a358-1ffeac10c3b3.txt'
```

- **type** `HybridDeliveryException` · **fp** `2c40627a0332e530`
- **template** `ERROR <LIST> Found character <NAME> instead of field delimiter <NAME> File 'staging/<ID>/<PATH>`
- **values** ID: 398e91a4-8147-4668-96ee-6645c73ae895; NAME: , ,; LIST: [22000]; PATH: SnowflakeImportCopyCommand/data_398e91a4-8147-4668-96ee-6645c73ae895_e9a92264-b3ee-4cbe-a358-1ffeac10c3b3.txt
- **keywords** user, error, odbc, operation, failed, found, character, instead

**3.** given code `UserErrorOdbcOperationFailed`

```text
ErrorCode=UserErrorOdbcOperationFailed,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=ERROR [22000] Cannot perform CREATE STAGE. This session does not have a current database. Call 'USE DATABASE', or use a qualified name.,Source=Microsoft.DataTransfer.Runtime.GenericOdbcConnectors,''Type=System.Data.Odbc.OdbcException,Message=ERROR [22000] Cannot perform CREATE STAGE. This session does not have a current database. Call 'USE DATABASE', or use a qualified name.,Source=SnowflakeODBC_sb64.dll,'
```

- **type** `OdbcException` · **fp** `9a0aae8c47ede12a`
- **template** `ERROR <LIST> Cannot perform CREATE STAGE. This session does not have a current database. Call <NAME>, or use a qualified name.`
- **values** NAME: USE DATABASE; LIST: [22000]
- **keywords** user, error, odbc, operation, failed, cannot, perform, create

**4.** given code `UserErrorOdbcOperationFailed`

```text
ErrorCode=UserErrorOdbcOperationFailed,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=ERROR [HY000] [Microsoft][Snowflake] (4) REST request for URL *** failed: HTTP error (http error) - code=503. ,Source=Microsoft.DataTransfer.Runtime.GenericOdbcConnectors,''Type=System.Data.Odbc.OdbcException,Message=ERROR [HY000] [Microsoft][Snowflake] (4) REST request for URL *** failed: HTTP error (http error) - code=503. ,Source=SnowflakeODBC_sb64.dll,'
```

- **type** `OdbcException` · **fp** `0856d539236d07de`
- **template** `ERROR <LIST> <LIST><LIST> (<NUM>) REST request for URL *** failed: HTTP error (http error) - code=<NUM>.`
- **values** LIST: [HY000], [Microsoft], [Snowflake]; NUM: 4, 503
- **keywords** user, error, odbc, operation, failed, rest, request, url

**5.** given code `UserErrorOdbcOperationFailed`

```text
ErrorCode=UserErrorOdbcOperationFailed,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=ERROR [22007] Timestamp ‘14/01/2000’ is not recognized
```

- **type** `HybridDeliveryException` · **fp** `05749d729fbf6193`
- **template** `ERROR <LIST> Timestamp ‘<TS>’ is not recognized`
- **values** TS: 14/01/2000; LIST: [22007]
- **keywords** user, error, odbc, operation, failed, timestamp, recognized

**6.** given code `UserErrorOdbcOperationFailed`

```text
ErrorCode=UserErrorOdbcOperationFailed,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=ERROR [42501] Failed to access remote file: access denied.
```

- **type** `HybridDeliveryException` · **fp** `71ec324dd910dca3`
- **template** `ERROR <LIST> Failed to access remote file: access denied.`
- **values** LIST: [42501]
- **keywords** user, error, odbc, operation, failed, access, remote, file

**7.** given code `UserErrorOdbcOperationFailed`

```text
Failure happened on 'Source' side. ErrorCode=UserErrorOdbcOperationFailed,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=ERROR [HY000] [IBM][System i Access ODBC Driver][DB2 for i5/OS] - Error message text unavailable. Message can not be translated successfully.,Source=Microsoft.DataTransfer.Runtime.GenericOdbcConnectors,''Type=System.Data.Odbc.OdbcException,Message=ERROR [HY000] [IBM][System i Access ODBC Driver][DB2 for i5/OS] - Error message text unavailable. Message can not be translated successfully.,Source=CWBODBC.DLL,'
```

- **type** `OdbcException` · **fp** `47dc51295207595b`
- **template** `ERROR <LIST> <LIST><LIST><LIST> - Error message text unavailable. Message can not be translated successfully.`
- **values** LIST: [HY000], [IBM], [System i Access ODBC Driver], [DB2 for i5/OS]
- **keywords** user, error, odbc, operation, failed, text, unavailable, can

**8.** given code `UserErrorOdbcOperationFailed`

```text
Failure happened on 'Source' side. ErrorCode=UserErrorOdbcOperationFailed,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=ERROR [42000] [Microsoft][MariaDB] You have an error in your SQL syntax; check the manual that corresponds to your MariaDB server version for the right syntax to use near '"LastValue":540418183}\n and id<={"Max":546239715}' at line 2
```

- **type** `HybridDeliveryException` · **fp** `0f8a0a76edee3477`
- **template** `ERROR <LIST> <LIST><LIST> You have an error in your SQL syntax; check the manual that corresponds to your MariaDB server version for the right syntax to use near <NAME> at line <NUM>`
- **values** NAME: LastValue":540418183}  and id<={"Max":546239715}; LIST: [42000], [Microsoft], [MariaDB]; NUM: 2
- **keywords** user, error, odbc, operation, failed, you, your, sql

### UserErrorFailedFileOperation (7)

**1.** given code `UserErrorFailedFileOperation`

```text
ErrorCode=UserErrorFailedFileOperation,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=Upload file failed at path sapoutput.,Source=mscorlib,''Type=System.Net.WebException,Message=The remote server returned an error: (403) Forbidden.,Source=System,
```

- **type** `WebException` · **fp** `1e54d7913e232b71`
- **template** `Upload file failed at path sapoutput.`
- **values** —
- **keywords** user, error, failed, file, operation, upload, path, sapoutput

**2.** given code `UserErrorFailedFileOperation`

```text
Failure happened on 'Source' side. ErrorCode=UserErrorFailedFileOperation,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=The file operation is failed, upload file failed at path: '/Parent/UAT'.,Source=mscorlib,''Type=System.Data.SqlClient.SqlException,Message=Conversion failed when converting date and/or time from character string.,Source=.Net SqlClient Data Provider,SqlErrorNumber=241,Class=16,ErrorCode=-2146232060,State=1,Errors=[{Class=16,Number=241,State=1,Message=Conversion failed when converting date and/or time from character string.,},],'
```

- **type** `SqlException` · **fp** `b48bcbc3f5972fe3`
- **template** `The file operation is failed, upload file failed at path: <NAME>.`
- **values** NAME: /Parent/UAT
- **keywords** user, error, failed, file, operation, upload, path

**3.** given code `UserErrorFailedFileOperation`

```text
Failure happened on 'Sink' side. ErrorCode=UserErrorFailedFileOperation,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=Upload file failed at path rawzone\cibil_enq_file_20200831.parquet.,Source=Microsoft.DataTransfer.Common,''Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=Failed to read a 'Hdfs' file. File path: 'Data_Archival/Bureau_Data_Mart/Bureau_Retail20/cibil_enq_file_20200831/cibil_enq_file_20200831.parquet'. Response details: '{}'.,Source=Microsoft.DataTransfer.ClientLibrary,''Type=System.Net.WebException,Message=The remote server  …
```

- **type** `WebException` · **fp** `7a0575a736d16c51` ×2
- **template** `Upload file failed at path <PATH>`
- **values** PATH: rawzone\cibil_enq_file_20200831.parquet.
- **keywords** user, error, failed, file, operation, upload, path

**4.** given code `UserErrorFailedFileOperation`

```text
Failure happened on 'Source' side. ErrorCode=UserErrorFailedFileOperation,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=The file operation is failed, upload file failed at path: 'perfectviewexport/Output/PerfectView_export_Inter-Rent20240617.zip/exports/alle contactpersonen.csv'.,Source=Microsoft.DataTransfer.Common,''Type=System.IO.InvalidDataException,Message=Found invalid data while decoding.,Source=System,'
```

- **type** `InvalidDataException` · **fp** `79cc125c00aa5aea`
- **template** `The file operation is failed, upload file failed at path: <NAME>.`
- **values** NAME: perfectviewexport/Output/PerfectView_export_Inter-Rent20240617.zip/exports/alle contactpersonen.csv
- **keywords** user, error, failed, file, operation, upload, path

**5.** given code `UserErrorFailedFileOperation`

```text
Activity Copy_DetailPricingLevelHierarchy failed: Failure happened on 'Sink' side. ErrorCode=UserErrorFailedFileOperation,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=Upload file failed at path Intake/MySource\PricingLevelHierarchy.,Source=Microsoft.DataTransfer.Common,''Type=System.InvalidOperationException,Message=Internal connection fatal error. Error state: 18,Source=System.Data,'
```

- **type** `InvalidOperationException` · **fp** `906462d9203a1784`
- **template** `Upload file failed at path <PATH>`
- **values** PATH: Intake/MySource\PricingLevelHierarchy.
- **keywords** user, error, failed, file, operation, upload, path

**6.** given code `UserErrorFailedFileOperation`

```text
Failure happened on 'Sink' side. ErrorCode=UserErrorFailedFileOperation,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=Upload file failed at path extract/coEDW\XXXX_Data_etc.zip.,Source=Microsoft.DataTransfer.ClientLibrary,''Type=Microsoft.WindowsAzure.Storage.StorageException,Message=The remote server returned an error: (404) Not Found.,Source=Microsoft.WindowsAzure.Storage,StorageExtendedMessage=The specified resource does not exist. RequestId:bfe4e2f6-501e-002e-6a21-eaf10e000000 Time:2021-01-14T02:59:24.3300081Z,,''Type=System.Net.WebException,Message=The remote  …
```

- **type** `WebException` · **fp** `7a0575a736d16c51` ×2
- **template** `Upload file failed at path <PATH>`
- **values** PATH: extract/coEDW\XXXX_Data_etc.zip.
- **keywords** user, error, failed, file, operation, upload, path

**7.** given code `UserErrorFailedFileOperation`

```text
Operation on target XXXX failed: Failure happened on 'Source' side. ErrorCode=UserErrorFailedFileOperation,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=Upload file failed at path XXXXXXX,Source=Microsoft.DataTransfer.Common,''Type=System.NotSupportedException,Message=The authentication endpoint Kerberos was not found on the configured Secure Token Service!,Source=Microsoft.Xrm.Sdk,'
```

- **type** `NotSupportedException` · **fp** `2d4e99f7f545b9a1`
- **template** `Upload file failed at path XXXXXXX`
- **values** —
- **keywords** user, error, failed, file, operation, upload, path, xxxxxxx

### DelimitedTextMoreColumnsThanDefined (6)

**1.** given code `DelimitedTextMoreColumnsThanDefined`

```text
ErrorCode=DelimitedTextMoreColumnsThanDefined, 'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException, Message=Error found when processing 'Csv/Tsv Format Text' source 'file1.csv' with row number 5: found more columns than expected column count 17.,Source=Microsoft.DataTransfer.Common,'
```

- **type** `HybridDeliveryException` · **fp** `301f349cd0127282` ×6
- **template** `Error found when processing <NAME> source <NAME> with row number <NUM>: found more columns than expected column count <NUM>.`
- **values** NAME: Csv/Tsv Format Text, file1.csv; NUM: 5, 17
- **keywords** delimited, text, more, columns, than, defined, found, when

**2.** given code `DelimitedTextMoreColumnsThanDefined`

```text
ErrorCode=DelimitedTextMoreColumnsThanDefined,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=Error found when processing 'Csv/Tsv Format Text' source 'chauf_afw.txt' with row number 2: found more columns than expected column count 5.,Source=Microsoft.DataTransfer.Common,'
```

- **type** `HybridDeliveryException` · **fp** `301f349cd0127282` ×6
- **template** `Error found when processing <NAME> source <NAME> with row number <NUM>: found more columns than expected column count <NUM>.`
- **values** NAME: Csv/Tsv Format Text, chauf_afw.txt; NUM: 2, 5
- **keywords** delimited, text, more, columns, than, defined, found, when

**3.** given code `DelimitedTextMoreColumnsThanDefined`

```text
ErrorCode=DelimitedTextMoreColumnsThanDefined,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=Error found when processing 'Csv/Tsv Format Text' source 'CRM_XXX_###.CSV' with row number 1140713: found more columns than expected column count 369.,Source=Microsoft.DataTransfer.Common,'
```

- **type** `HybridDeliveryException` · **fp** `301f349cd0127282` ×6
- **template** `Error found when processing <NAME> source <NAME> with row number <NUM>: found more columns than expected column count <NUM>.`
- **values** NAME: Csv/Tsv Format Text, CRM_XXX_###.CSV; NUM: 1140713, 369
- **keywords** delimited, text, more, columns, than, defined, found, when

**4.** given code `DelimitedTextMoreColumnsThanDefined`

```text
ErrorCode=DelimitedTextMoreColumnsThanDefined,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=Error found when processing 'Csv/Tsv Format Text' source '2020-09-16-stations.csv' with row number 2: found more columns than expected column count 11.,Source=Microsoft.DataTransfer.Common,'
```

- **type** `HybridDeliveryException` · **fp** `301f349cd0127282` ×6
- **template** `Error found when processing <NAME> source <NAME> with row number <NUM>: found more columns than expected column count <NUM>.`
- **values** TS: 2020-09-16; NAME: Csv/Tsv Format Text, <TS>-stations.csv; NUM: 2, 11
- **keywords** delimited, text, more, columns, than, defined, found, when

**5.** given code `DelimitedTextMoreColumnsThanDefined`

```text
ErrorCode=DelimitedTextMoreColumnsThanDefined,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=Error found when processing 'Csv/Tsv Format Text' source 'abc.csv' with row number 2571: found more columns than expected column count 136.,Source=Microsoft.DataTransfer.Common,'.
```

- **type** `HybridDeliveryException` · **fp** `301f349cd0127282` ×6
- **template** `Error found when processing <NAME> source <NAME> with row number <NUM>: found more columns than expected column count <NUM>.`
- **values** NAME: Csv/Tsv Format Text, abc.csv; NUM: 2571, 136
- **keywords** delimited, text, more, columns, than, defined, found, when

**6.** given code `DelimitedTextMoreColumnsThanDefined`

```text
Operation on target Copy_hs1 failed: ErrorCode=DelimitedTextMoreColumnsThanDefined,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=Error found when processing 'Csv/Tsv Format Text' source 'SALESLINE_00001.csv' with row number 4: found more columns than expected column count 6.,Source=Microsoft.DataTransfer.Common,'
```

- **type** `HybridDeliveryException` · **fp** `301f349cd0127282` ×6
- **template** `Error found when processing <NAME> source <NAME> with row number <NUM>: found more columns than expected column count <NUM>.`
- **values** NAME: Csv/Tsv Format Text, SALESLINE_00001.csv; NUM: 4, 6
- **keywords** delimited, text, more, columns, than, defined, found, when

### SqlOperationFailed (6)

**1.** given code `SqlOperationFailed`

```text
Failure happened on 'Sink' side. ErrorCode=SqlOperationFailed,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=A database operation failed. Please search error to get more details.,Source=Microsoft.DataTransfer.ClientLibrary,''Type=System.InvalidOperationException,Message=The given value of type String from the data source cannot be converted to type nvarchar of the specified target column.,Source=System.Data,''Type=System.InvalidOperationException,Message=String or binary data would be truncated.,Source=System.Data,'
```

- **type** `InvalidOperationException` · **fp** `1f556a1d95e08e86`
- **template** `A database operation failed. Please search error to get more details.`
- **values** —
- **keywords** sql, operation, failed, database, search, get

**2.** given code `SqlOperationFailed`

```text
ErrorCode=SqlOperationFailed,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=A database operation failed with the following error: 'Incorrect syntax near '>'.',Source=,''Type=System.Data.SqlClient.SqlException,Message=Incorrect syntax near '>'.,Source=.Net SqlClient Data Provider,SqlErrorNumber=102,Class=15,ErrorCode=-2146232060,State=1,Errors=[{Class=15,Number=102,State=1,Message=Incorrect syntax near '>'.,},],'
```

- **type** `SqlException` · **fp** `e1c2aa289e18a842`
- **template** `A database operation failed with the following error: <NAME>><NAME>`
- **values** NAME: Incorrect syntax near , .
- **keywords** sql, operation, failed, database, following

**3.** given code `SqlOperationFailed`

```text
Failure happened on 'Source' side. ErrorCode=SqlOperationFailed,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=A database operation failed with the following error: 'Incorrect syntax near ')'.',Source=,''Type=System.Data.SqlClient.SqlException,Message=Incorrect syntax near ')'.,Source=.Net SqlClient Data Provider,SqlErrorNumber=102,Class=15,ErrorCode=-2146232060,State=1,Errors=[{Class=15,Number=102,State=1,Message=Incorrect syntax near ')'.,},],'
```

- **type** `SqlException` · **fp** `57edc580950423ad`
- **template** `A database operation failed with the following error: <NAME>)<NAME>`
- **values** NAME: Incorrect syntax near , .
- **keywords** sql, operation, failed, database, following

**4.** given code `SqlOperationFailed`

```text
ErrorCode=SqlOperationFailed, Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException, Message=A database operation failed. Please search error to get more details., Source=Microsoft.DataTransfer.Connectors.MSSQL, Type=Microsoft.Data.SqlClient.SqlException, Message=The statement failed. Column 'Location' has a data type that cannot participate in a columnstore index., Source=Framework Microsoft SqlClient Data Provider
```

- **type** `SqlException` · **fp** `2e365e313f413cd3`
- **template** `A database operation failed. Please search error to get more details.`
- **values** —
- **keywords** sql, operation, failed, database, search, get

**5.** given code `SqlOperationFailed`

```text
Failure happened on 'Source' side. ErrorCode=SqlOperationFailed,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=A database operation failed with the following error: 'Must declare the scalar variable "@variables".',Source=,''Type=System.Data.SqlClient.SqlException,Message=Must declare the scalar variable "@variables".,Source=.Net SqlClient Data Provider,SqlErrorNumber=137,Class=15,ErrorCode=-2146232060,State=2,Errors=[{Class=15,Number=137,State=2,Message=Must declare the scalar variable "@variables".,},],'
```

- **type** `SqlException` · **fp** `8574ea260ad94c48`
- **template** `A database operation failed with the following error: <NAME>`
- **values** NAME: Must declare the scalar variable "@variables".
- **keywords** sql, operation, failed, database, following

**6.** given code `SqlOperationFailed`

```text
Failure happened on 'Source' side. ErrorCode=SqlOperationFailed,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=A database operation failed with the following error: 'Internal system error occurred.
Statement ID: {C2C38377-5A14-4BB7-9298-28C3C351A40E} | Query hash: 0x2C885D2041993FFA | Distributed request ID: {6556701C-BA76-4D0F-8976-52695BBFE6A7}. Total size of data scanned is 134 megabytes, total size of data moved is 102 megabytes, total size of data written is 0 megabytes.',Source=,''Type=System.Data.SqlClient.SqlException,Message=Internal system error occurred. …
```

- **type** `SqlException` · **fp** `def3f134a114cc3d`
- **template** `A database operation failed with the following error: 'Internal system error occurred. Statement ID: {<ID>} \| Query hash: <HEX> \| Distributed request ID: {<ID>}. Total size of data scanned is <NUM> megabytes, total size of data moved is <NUM> megabytes, total size of data written is <NUM> megabytes.`
- **values** ID: C2C38377-5A14-4BB7-9298-28C3C351A40E, 6556701C-BA76-4D0F-8976-52695BBFE6A7; HEX: 0x2C885D2041993FFA; NUM: 134, 102, 0
- **keywords** sql, operation, failed, database, following, internal, system, occurred

### UserErrorFileNotFound (6)

**1.** given code `UserErrorFileNotFound`

```text
Failure happened on the 'Sink' side. ErrorCode=UserErrorFileNotFound, 'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException, Message=ADLS Gen2 operation failed for: Operation returned an invalid status code 'NotFound'. Account: 'XXXX'. FileSystem: 'XXXX'. Path: 'PATH_TO_PARQUET_FILE/oracle_query_TABLE_ID_91922989_122230649_00003.parquet'. ErrorCode: 'PathNotFound'. Message: 'The specified path does not exist.'. RequestId: 'XXXXX'. TimeStamp: 'Sat, 03 Aug 2024 03:10:20 GMT.', Source=Microsoft.DataTransfer.ClientLibrary,'Type=Microsoft.Azure.Storage.Data.Models.ErrorSchemaException, …
```

- **type** `ErrorSchemaException` · **fp** `29a29c815348d262`
- **template** `ADLS <NAME> operation failed for: Operation returned an invalid status code <NAME>. Account: <NAME>. FileSystem: <NAME>. Path: <NAME>. ErrorCode: <NAME>. Message: <NAME>. RequestId: <NAME>. TimeStamp: <NAME>`
- **values** TS: 03:10:20; NAME: NotFound, XXXX, XXXX, PATH_TO_PARQUET_FILE/oracle_query_TABLE_ID_91922989_122230649_00003.parquet …
- **keywords** user, error, file, not, found, adls, returned, invalid

**2.** given code `UserErrorFileNotFound`

```text
Failed execution Copy activity encountered a user error: ErrorCode=UserErrorFileNotFound,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=Cannot find the 'HDFS' file. ,Source=Microsoft.DataTransfer.ClientLibrary,''Type=System.Net.WebException,Message=The remote server returned an error: (404) Not Found.,Source=System,'.
```

- **type** `WebException` · **fp** `917af9a45d1a1be6`
- **template** `Cannot find the <NAME> file.`
- **values** NAME: HDFS
- **keywords** user, error, file, not, found, cannot, find

**3.** given code `UserErrorFileNotFound`

```text
ErrorCode=UserErrorFileNotFound,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=Cannot find the file specified. Folder path: 'Testing', File filter: '*.txt'.,Source=Microsoft.DataTransfer.ClientLibrary,''Type=System.Net.WebException,Message=Unable to connect to the remote server,Source=System,'.
```

- **type** `WebException` · **fp** `0e2d6b992aa75bee` ×2
- **template** `Cannot find the file specified. Folder path: <NAME>, File filter: <NAME>.`
- **values** NAME: Testing, *.txt
- **keywords** user, error, file, not, found, cannot, find, specified

**4.** given code `UserErrorFileNotFound`

```text
Copy activity encountered a user error at Source side: ErrorCode=UserErrorFileNotFound,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=Cannot find the file specified. Folder path: 'Test/', File filter: 'Testfile.text'.,Source=Microsoft.DataTransfer.ClientLibrary,''Type=System.Net.WebException,Message=The remote server returned an error: (500) Syntax error, command unrecognized.,Source=System,'.
```

- **type** `WebException` · **fp** `0e2d6b992aa75bee` ×2
- **template** `Cannot find the file specified. Folder path: <NAME>, File filter: <NAME>.`
- **values** NAME: Test/, Testfile.text
- **keywords** user, error, file, not, found, cannot, find, specified

**5.** given code `UserErrorFileNotFound`

```text
ErrorCode=UserErrorFileNotFound,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=The remote server returned an error: (550) File unavailable (e.g., file not found, no access).,Source=Microsoft.DataTransfer.ClientLibrary,''Type=System.Net.WebException,Message=The remote server returned an error: (550) File unavailable (e.g., file not found, no access).,Source=System,'
```

- **type** `WebException` · **fp** `981d86b61ed60d64`
- **template** `The remote server returned an error: (<NUM>) File unavailable (e.g., file not found, no access).`
- **values** NUM: 550
- **keywords** user, error, file, not, found, remote, server, returned

**6.** given code `UserErrorFileNotFound`

```text
ErrorCode=UserErrorFileNotFound,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=Cannot find the file specified. Folder path: '<<long file path>>''.,Source=Microsoft.DataTransfer.ClientLibrary,''Type=System.IO.FileNotFoundException,Message=Could not find file '<<long file path>>'
```

- **type** `FileNotFoundException` · **fp** `1c85eee578e9c40c`
- **template** `Cannot find the file specified. Folder path: <NAME>.`
- **values** NAME: <<long file path>>
- **keywords** user, error, file, not, found, cannot, find, specified

### AdlsGen2OperationFailed (5)

**1.** given code `AdlsGen2OperationFailed`

```text
ErrorCode=AdlsGen2OperationFailed,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=ADLS Gen2 operation failed for: 'filesystem' does not match expected pattern '^$a-z0-9[-a-z0-9]{1,61}[a-z0-9]$'.. Account: 'saworldemission'. FileSystem: 'True'. Path: 'True'..,Source=Microsoft.DataTransfer.ClientLibrary,''Type=Microsoft.Rest.ValidationException,Message='filesystem' does not match expected pattern '^$a-z0-9[-a-z0-9]{1,61}[a-z0-9]$'.,Source=Microsoft.DataTransfer.ClientLibrary,'
```

- **type** `ValidationException` · **fp** `7adec50f202bd44d`
- **template** `ADLS <NAME> operation failed for: <NAME> does not match expected pattern <NAME>.. Account: <NAME>. FileSystem: <NAME>. Path: <NAME>..`
- **values** NAME: filesystem, ^$a-z0-9[-a-z0-9]{1,61}[a-z0-9]$, saworldemission, True …
- **keywords** adls, gen2, operation, failed, does, match, expected, pattern

**2.** given code `AdlsGen2OperationFailed`

```text
Failure happened on 'Sink' side. ErrorCode=AdlsGen2OperationFailed,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=ADLS Gen2 operation failed for: Operation returned an invalid status code 'Conflict'. Account: '{Storage Account Name}'. FileSystem: '{Container Name}'. Path: 'foodics_v2/Burgerizzr/transactional/_567a2g7a/2018-02-09/raw/inventory-transactions.json'. ErrorCode: 'LeaseAlreadyPresent'. Message: 'There is already a lease present.'. RequestId: 'd27f1a3d-d01f-0003-28fb-400303000000'..,Source=Microsoft.DataTransfer.ClientLibrary,'
```

- **type** `HybridDeliveryException` · **fp** `b0e4f741261e7860` ×2
- **template** `ADLS <NAME> operation failed for: Operation returned an invalid status code <NAME>. Account: <NAME>. FileSystem: <NAME>. Path: <NAME>. ErrorCode: <NAME>. Message: <NAME>. RequestId: <NAME>..`
- **values** ID: d27f1a3d-d01f-0003-28fb-400303000000; TS: 2018-02-09; NAME: Conflict, {Storage Account Name}, {Container Name}, foodics_v2/Burgerizzr/transactional/_567a2g7a/<TS>/raw/inventory-transactions.json …
- **keywords** adls, gen2, operation, failed, returned, invalid, status, code

**3.** given code `AdlsGen2OperationFailed`

```text
Failure happened on 'Sink' side. ErrorCode=AdlsGen2OperationFailed,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=ADLS Gen2 operation failed for: Operation returned an invalid status code 'Conflict'. Account: 'mydatalake'. FileSystem: 'raw'. Path: 'Source/ABC/File_2021_03_24.csv'. ErrorCode: 'PathImmutableDueToLegalHold'. Message: 'This operation is not permitted as the path is immutable due to one or more legal holds.'. RequestId: '37f75e88-501a-0026-2fa1-20d52e000000'. TimeStamp: 'Wed, 24 Mar 2021 11:30:54 GMT'..,Source=Microsoft.DataTransfer.ClientLibrary,'
```

- **type** `HybridDeliveryException` · **fp** `b0e4f741261e7860` ×2
- **template** `ADLS <NAME> operation failed for: Operation returned an invalid status code <NAME>. Account: <NAME>. FileSystem: <NAME>. Path: <NAME>. ErrorCode: <NAME>. Message: <NAME>. RequestId: <NAME>. TimeStamp: <NAME>..`
- **values** ID: 37f75e88-501a-0026-2fa1-20d52e000000; TS: 11:30:54; NAME: Conflict, mydatalake, raw, Source/ABC/File_2021_03_24.csv …
- **keywords** adls, gen2, operation, failed, returned, invalid, status, code

**4.** given code `AdlsGen2OperationFailed`

```text
ErrorCode=AdlsGen2OperationFailed,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=ADLS Gen2 operation failed for: Operation returned an invalid status code 'BadRequest'. Account: 'adlsedmadifpoc'. FileSystem: 'raw_area'. ErrorCode: 'InvalidResourceName'. Message: 'The specifed resource name contains invalid characters.'. RequestId: '70d7xbfd-6xxf-00ec-2c74-9axxxx000000'. TimeStamp: 'Thu, 26 Aug 2021 12:19:56 GMT'..,Source=Microsoft.DataTransfer.ClientLibrary,''Type=Microsoft.Azure.Storage.Data.Models.ErrorSchemaException,Message=Operation returned an invalid status c …
```

- **type** `ErrorSchemaException` · **fp** `3067b9ac8d7c2229`
- **template** `ADLS <NAME> operation failed for: Operation returned an invalid status code <NAME>. Account: <NAME>. FileSystem: <NAME>. ErrorCode: <NAME>. Message: <NAME>. RequestId: <NAME>. TimeStamp: <NAME>..`
- **values** TS: 12:19:56; NAME: BadRequest, adlsedmadifpoc, raw_area, InvalidResourceName …
- **keywords** adls, gen2, operation, failed, returned, invalid, status, code

**5.** given code `AdlsGen2OperationFailed`

```text
ErrorCode=AdlsGen2OperationFailed,' Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException, Message=ADLS Gen2 operation failed for: An error occurred while sending the request.. Account: 'txcipsstacdwh'. FileSystem: 'txcipsstacdwh'..,Source=Microsoft.DataTransfer.ClientLibrary,''Type=System.Net.Http.HttpRequestException,Message=An error occurred while sending the request.,Source=mscorlib,''Type=System.Net.WebException,Message=The underlying connection was closed: An unexpected error occurred on a send.,Source=System,''Type=System.IO.IOException,Message=Authentication failed because  …
```

- **type** `IOException` · **fp** `342fc6075fec398d`
- **template** `ADLS <NAME> operation failed for: An error occurred while sending the request.. Account: <NAME>. FileSystem: <NAME>..`
- **values** NAME: txcipsstacdwh, txcipsstacdwh, Gen2
- **keywords** adls, gen2, operation, failed, occurred, while, sending, request

### DelimitedTextColumnNameNotAllowNull (5)

**1.** given code `DelimitedTextColumnNameNotAllowNull`

```text
ErrorCode=DelimitedTextColumnNameNotAllowNull,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=The name of column index 236 is empty. Make sure column name is properly specified in the header
```

- **type** `HybridDeliveryException` · **fp** `2619288ddba61f09` ×5
- **template** `The name of column index <NUM> is empty. Make sure column name is properly specified in the header`
- **values** NUM: 236
- **keywords** delimited, text, column, name, not, allow, null, index

**2.** given code `DelimitedTextColumnNameNotAllowNull`

```text
ErrorCode=DelimitedTextColumnNameNotAllowNull,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=The name of column index 3 is empty. Make sure column name is properly specified in the header
```

- **type** `HybridDeliveryException` · **fp** `2619288ddba61f09` ×5
- **template** `The name of column index <NUM> is empty. Make sure column name is properly specified in the header`
- **values** NUM: 3
- **keywords** delimited, text, column, name, not, allow, null, index

**3.** given code `DelimitedTextColumnNameNotAllowNull`

```text
ErrorCode=DelimitedTextColumnNameNotAllowNull,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=The name of column index 36 is empty. Make sure column name is properly specified in the header row.,Source=Microsoft.DataTransfer.Common,'
```

- **type** `HybridDeliveryException` · **fp** `2619288ddba61f09` ×5
- **template** `The name of column index <NUM> is empty. Make sure column name is properly specified in the header row.`
- **values** NUM: 36
- **keywords** delimited, text, column, name, not, allow, null, index

**4.** given code `DelimitedTextColumnNameNotAllowNull`

```text
ErrorCode=DelimitedTextColumnNameNotAllowNull,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=The name of column index 1 is empty. Make sure column name is properly specified in the header row.,Source=Microsoft.DataTransfer.Common
```

- **type** `HybridDeliveryException` · **fp** `2619288ddba61f09` ×5
- **template** `The name of column index <NUM> is empty. Make sure column name is properly specified in the header row.`
- **values** NUM: 1
- **keywords** delimited, text, column, name, not, allow, null, index

**5.** given code `DelimitedTextColumnNameNotAllowNull`

```text
ErrorCode=DelimitedTextColumnNameNotAllowNull,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=The name of column index 22 is empty. Make sure column name is properly specified in the header row.,Source=Microsoft.DataTransfer.Common,'
```

- **type** `HybridDeliveryException` · **fp** `2619288ddba61f09` ×5
- **template** `The name of column index <NUM> is empty. Make sure column name is properly specified in the header row.`
- **values** NUM: 22
- **keywords** delimited, text, column, name, not, allow, null, index

### UserErrorHttpStatusCodeIndicatingFailure (5)

**1.** given code `UserErrorHttpStatusCodeIndicatingFailure`

```text
Operation on target copy_api_to_file failed: Failure happened on 'Source' side. ErrorCode=UserErrorHttpStatusCodeIndicatingFailure, 'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException, Message=The HttpStatusCode 401 indicates failure, xxxx,Source=Microsoft.DataTransfer.ClientLibrary,'
```

- **type** `HybridDeliveryException` · **fp** `eb66ad2f1b5214eb`
- **template** `The HttpStatusCode <NUM> indicates failure, xxxx`
- **values** NUM: 401
- **keywords** user, error, http, status, code, indicating, failure, httpstatuscode

**2.** given code `UserErrorHttpStatusCodeIndicatingFailure`

```text
Failure happened on 'Source' side. ErrorCode=UserErrorHttpStatusCodeIndicatingFailure, 'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException, Message=The HttpStatusCode 500 indicates failure. The cluster has been halted and is not restartable. ,Source=Microsoft.DataTransfer.ClientLibrary,'
```

- **type** `HybridDeliveryException` · **fp** `faa7571d3a8de3c7` ×4
- **template** `The HttpStatusCode <NUM> indicates failure. The cluster has been halted and is not restartable.`
- **values** NUM: 500
- **keywords** user, error, http, status, code, indicating, failure, httpstatuscode

**3.** given code `UserErrorHttpStatusCodeIndicatingFailure`

```text
Failure happened on 'Source' side. ErrorCode=UserErrorHttpStatusCodeIndicatingFailure,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=The HttpStatusCode 400 indicates failure.  {"error":{"code":"400"&#44;"message":"Parameter: endTime. Value is greater than 2019-06-01"}},Source=Microsoft.DataTransfer.ClientLibrary,'
```

- **type** `HybridDeliveryException` · **fp** `faa7571d3a8de3c7` ×4
- **template** `The HttpStatusCode <NUM> indicates failure. {<NAME>:{<NAME>:<NAME>:<NAME>}}`
- **values** TS: 2019-06-01; NAME: error, code, 400, message …; NUM: 400
- **keywords** user, error, http, status, code, indicating, failure, httpstatuscode

**4.** given code `UserErrorHttpStatusCodeIndicatingFailure`

```text
ErrorCode=UserErrorHttpStatusCodeIndicatingFailure,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=The HttpStatusCode 404 indicates failure. { "statusCode": 404, "message": "Resource not found" },Source=Microsoft.DataTransfer.ClientLibrary,'
```

- **type** `HybridDeliveryException` · **fp** `faa7571d3a8de3c7` ×4
- **template** `The HttpStatusCode <NUM> indicates failure. { <NAME>: <NUM>, <NAME>: <NAME> }`
- **values** NAME: statusCode, message, Resource not found; NUM: 404, 404
- **keywords** user, error, http, status, code, indicating, failure, httpstatuscode

**5.** given code `UserErrorHttpStatusCodeIndicatingFailure`

```text
Failure happened on 'Source' side. ErrorCode=UserErrorHttpStatusCodeIndicatingFailure,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=The HttpStatusCode 401 indicates failure. { "Error": { "Message":"Authentication failed: Invalid headers", "Server-Time":"2020-07-27T06:59:24", "Id":"6AAF87BC-5634-4C28-8626-810A19B86BFF" } },Source=Microsoft.DataTransfer.ClientLibrary,'
```

- **type** `HybridDeliveryException` · **fp** `faa7571d3a8de3c7` ×4
- **template** `The HttpStatusCode <NUM> indicates failure. { <NAME>: { <NAME>:<NAME>:<NAME>:<NAME> } }`
- **values** ID: 6AAF87BC-5634-4C28-8626-810A19B86BFF; TS: 2020-07-27T06:59:24; NAME: Error, Message, Authentication failed: Invalid headers, Server-Time …; NUM: 401
- **keywords** user, error, http, status, code, indicating, failure, httpstatuscode

### SqlFailedToConnect (4)

**1.** given code `SqlFailedToConnect`

```text
Operation on target Server failed: ErrorCode=SqlFailedToConnect,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=Cannot connect to SQL Database: 'tcp:SQLServerName', Database: '', User: ''. Check the linked service configuration is correct, and make sure the SQL Database firewall allows the integration runtime to access.,Source=Microsoft.DataTransfer.ClientLibrary,''Type=System.Data.SqlClient.SqlException,Message=Login failed for user ''.,Source=.Net SqlClient Data Provider,SqlErrorNumber=18456,Class=14,ErrorCode=-2146232060,State=1,Errors=[{Class=14,Number=18456,Stat …
```

- **type** `SqlException` · **fp** `c2167be85c56f7d4` ×2
- **template** `Cannot connect to SQL Database: <NAME>, Database: <NAME>, User: '. Check the linked service configuration is correct, and make sure the SQL Database firewall allows the integration runtime to access.`
- **values** NAME: tcp:SQLServerName, 
- **keywords** sql, failed, connect, cannot, database, user, linked, service

**2.** given code `SqlFailedToConnect`

```text
ErrorCode=SqlFailedToConnect,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=Cannot connect to SQL Database: '', Database: '', User: ''. Check the linked service configuration is correct, and make sure the SQL Database firewall allows the integration runtime to access., Source=Microsoft.DataTransfer.ClientLibrary,''Type=System.Data.SqlClient.SqlException,Message=Cannot open server "" requested by the login. The login failed.,Source=.Net SqlClient Data Provider,SqlErrorNumber=40532,Class=14,ErrorCode=-2146232060,State=1,Errors=[{Class=14,Number=40532,State=1,Message=C …
```

- **type** `SqlException` · **fp** `c2167be85c56f7d4` ×2
- **template** `Cannot connect to SQL Database: <NAME>, Database: <NAME>, User: '. Check the linked service configuration is correct, and make sure the SQL Database firewall allows the integration runtime to access.`
- **values** NAME: , 
- **keywords** sql, failed, connect, cannot, database, user, linked, service

**3.** given code `SqlFailedToConnect`

```text
ErrorCode=SqlFailedToConnect,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=Cannot connect to SQL Database: 'sqlsrv', Database: 'database', User: 'user'. Check the linked service configuration is correct, and make sure the SQL Database firewall allows the integration runtime to access.
```

- **type** `HybridDeliveryException` · **fp** `23cf0b58107a63dd`
- **template** `Cannot connect to SQL Database: <NAME>, Database: <NAME>, User: <NAME>. Check the linked service configuration is correct, and make sure the SQL Database firewall allows the integration runtime to access.`
- **values** NAME: sqlsrv, database, user
- **keywords** sql, failed, connect, cannot, database, user, linked, service

**4.** given code `SqlFailedToConnect`

```text
Operation on target Copy data1 failed: ErrorCode=SqlFailedToConnect,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=Cannot connect to SQL Server database: 'tcp:mysqlserver2002.database.windows.net,1433', Database: 'mySampleDatabase', User: 'system'. Check the linked service configuration is correct, and make sure the SQL Server database firewall allows the integration runtime to access.
```

- **type** `HybridDeliveryException` · **fp** `4cafc5b0d11780ad`
- **template** `Cannot connect to SQL Server database: <NAME>, Database: <NAME>, User: <NAME>. Check the linked service configuration is correct, and make sure the SQL Server database firewall allows the integration runtime to access.`
- **values** NAME: tcp:mysqlserver2002.database.windows.net,1433, mySampleDatabase, system
- **keywords** sql, failed, connect, cannot, server, database, user, linked

### DFExecutorUserError (3)

**1.** given code `DFExecutorUserError`

```text
Job failed due to reason: at Sink 'ConvertToDelta': Job aborted.
```

- **type** `—` · **fp** `fdc27865f24735d3`
- **template** `Job failed due to reason: at Sink <NAME>: Job aborted.`
- **values** NAME: ConvertToDelta
- **keywords** dfexecutor, user, error, job, due, reason, sink, aborted

**2.** given code `DFExecutorUserError`

```text
Operation on target dataPracticeFlow failed: {"StatusCode":"DFExecutorUserError","Message":"Job failed due to reason: at Source 'x'(Line 1/Col 0): Limit should be integer value greater than 0","Details":""}
```

- **type** `—` · **fp** `7f2e916c947441ef`
- **template** `Job failed due to reason: at Source <NAME>(Line <PATH> <NUM>): Limit should be integer value greater than <NUM><NAME>Details<NAME>"}`
- **values** NAME: x, ,, :; PATH: 1/Col; NUM: 0, 0
- **keywords** dfexecutor, user, error, job, due, reason, line, limit

**3.** given code `DFExecutorUserError`

```text
"StatusCode":"DFExecutorUserError","Message":"Job failed due to reason: at Source 'source1': Job aborted due to stage failure: Serialized task 10:0 was 135562862 bytes, which exceeds max allowed: spark.rpc.message.maxSize (134217728 bytes). Consider increasing spark.rpc.message.maxSize or using broadcast variables for large values."
```

- **type** `—` · **fp** `4841f439b961a4b4`
- **template** `Job failed due to reason: at Source <NAME>: Job aborted due to stage failure: Serialized task <NUM>:<NUM> was <NUM> bytes, which exceeds max allowed: spark.rpc.message.maxSize (<NUM> bytes). Consider increasing spark.rpc.message.maxSize or using broadcast variables for large values."`
- **values** NAME: source1; NUM: 10, 0, 135562862, 134217728
- **keywords** dfexecutor, user, error, job, due, reason, aborted, stage

### PolybaseOperationFailed (3)

**1.** given code `PolybaseOperationFailed`

```text
ErrorCode=PolybaseOperationFailed,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=Error happened when loading data into SQL Data Warehouse. Operation: 'Polybase operation'.,Source=Microsoft.DataTransfer.ClientLibrary,''Type=System.Data.SqlClient.SqlException,Message=HdfsBridge::recordReaderFillBuffer - Unexpected error encountered filling record reader buffer: ClassCastException: ,Source=.Net SqlClient Data Provider,SqlErrorNumber=106000,Class=16,ErrorCode=-2146232060,State=1,Errors=[{Class=16,Number=106000,State=1,Message=HdfsBridge::recordReaderFillBuffer - Unexpec …
```

- **type** `SqlException` · **fp** `66c0a07c4b027cdb` ×3
- **template** `Error happened when loading data into SQL Data Warehouse. Operation: <NAME>.`
- **values** NAME: Polybase operation
- **keywords** polybase, operation, failed, when, loading, into, sql, warehouse

**2.** given code `PolybaseOperationFailed`

```text
Operation on target Copy isolation_advice_details to SQL failed: ErrorCode=PolybaseOperationFailed,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=Error happened when loading data into SQL Data Warehouse. Operation: 'Polybase operation'.,Source=Microsoft.DataTransfer.ClientLibrary,''Type=System.Data.SqlClient.SqlException,Message=HdfsBridge::recordReaderFillBuffer - Unexpected error encountered filling record reader buffer: HadoopExecutionException: Too long string in column [-1]: Actual len = [251]. MaxLEN=[250],Source=.Net SqlClient Data Provider,SqlErrorNumber=107 …
```

- **type** `SqlException` · **fp** `66c0a07c4b027cdb` ×3
- **template** `Error happened when loading data into SQL Data Warehouse. Operation: <NAME>.`
- **values** NAME: Polybase operation
- **keywords** polybase, operation, failed, when, loading, into, sql, warehouse

**3.** given code `PolybaseOperationFailed`

```text
ErrorCode=PolybaseOperationFailed,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=Error happened when loading data into SQL Data Warehouse. Operation: 'Create external table'.,Source=Microsoft.DataTransfer.ClientLibrary,''Type=System.Data.SqlClient.SqlException,Message=External file access failed due to internal error: 'Error occurred while accessing HDFS: Java exception raised on call to HdfsBridge_IsDirExist. Java exception message: HdfsBridge::isDirExist - Unexpected error encountered checking whether directory exists or not: AbfsRestOperationException: Operation  …
```

- **type** `SqlException` · **fp** `66c0a07c4b027cdb` ×3
- **template** `Error happened when loading data into SQL Data Warehouse. Operation: <NAME>.`
- **values** NAME: Create external table
- **keywords** polybase, operation, failed, when, loading, into, sql, warehouse

### RestCallFailedWithClientError (3)

**1.** given code `RestCallFailedWithClientError`

```text
Failure happened on 'Source' side. ErrorCode=RestCallFailedWithClientError,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=Rest call failed with client error, status code 404 NotFound, please check your activity settings.\nResponse: {"error":{"code":"ErrorInvalidUser","message":"The requested user 'xxxx@yyyy.com' is invalid."}},Source=Microsoft.DataTransfer.ClientLibrary,'
```

- **type** `HybridDeliveryException` · **fp** `cf2422f30f508922`
- **template** `Rest call failed with client error, status code <NUM> NotFound, please check your activity settings. Response: {<NAME>:{<NAME>:<NAME>:<NAME>}}`
- **values** EMAIL: xxxx@yyyy.com; NAME: <EMAIL>, error, code, ErrorInvalidUser …; NUM: 404
- **keywords** rest, call, failed, with, client, error, status, code

**2.** given code `RestCallFailedWithClientError`

```text
Rest call failed with client error, status code 403 Forbidden, please check your activity settings. Response: {"Message":"API is not accessible for application"}
```

- **type** `—` · **fp** `d237dd7ca8f8e775`
- **template** `Rest call failed with client error, status code <NUM> Forbidden, please check your activity settings. Response: {<NAME>:<NAME>}`
- **values** NAME: Message, API is not accessible for application; NUM: 403
- **keywords** rest, call, failed, with, client, error, status, code

**3.** given code `RestCallFailedWithClientError`

```text
Failure happened on 'Source' side. ErrorCode=RestCallFailedWithClientError,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=Rest call failed with client error, status code 429 429, please check your activity settings
```

- **type** `HybridDeliveryException` · **fp** `1d26a0f3222d69d4`
- **template** `Rest call failed with client error, status code <NUM> <NUM>, please check your activity settings`
- **values** NUM: 429, 429
- **keywords** rest, call, failed, with, client, error, status, code

### DF-Executor-InternalServerError (2)

**1.** given code `DF-Executor-InternalServerError`

```text
Job failed due to reason: at Sink 'FinaSink': Failed to execute dataflow with internal server error, please retry later. If issue persists, please contact Microsoft support for further assistance
```

- **type** `—` · **fp** `4941226d1305eff5` ×2
- **template** `Job failed due to reason: at Sink <NAME>: Failed to execute dataflow with internal server error, please retry later. If issue persists, please contact Microsoft support for further assistance`
- **values** NAME: FinaSink
- **keywords** df-executor-internal, server, error, job, due, reason, sink, execute

**2.** given code `DF-Executor-InternalServerError`

```text
Operation on target ForLoopControlTable failed: Activity failed because an inner activity failed; Inner activity name: DFCallSoftDelete, Error: {"StatusCode":"DF-Executor-InternalServerError","Message":"Job failed due to reason: at Sink 'updateDeltaTable': Failed to execute dataflow with internal server error, please retry later. If issue persists, please contact Microsoft support for further assistance","Details":"org.apache.spark.SparkException: Job aborted due to stage failure: Task 179 in stage 11.0 failed 1 times, most recent failure: Lost task 179.0 in stage 11.0 (TID 1910) (vm-67d14591  …
```

- **type** `—` · **fp** `4941226d1305eff5` ×2
- **template** `Job failed due to reason: at Sink <NAME>: Failed to execute dataflow with internal server error, please retry later. If issue persists, please contact Microsoft support for further assistance<NAME>Details<NAME>org.apache.spark.SparkException: Job aborted due to stage failure: Task <NUM> in stage <NU`
- **values** TS: 2023-10-31 19:11:37.455, 2023-10-31 19:11:37.457, 2023-10-31 19:11:37.464; NAME: updateDeltaTable, ,, :, 67d14591 …; NUM: 179, 11.0, 1, 179.0 …
- **keywords** df-executor-internal, server, error, job, due, reason, sink, execute

### DWCopyCommandOperationFailed (2)

**1.** given code `DWCopyCommandOperationFailed`

```text
ErrorCode=DWCopyCommandOperationFailed,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message='Warehouse' Copy Command operation failed with error ''A transport-level error has occurred when receiving results from the server. (provider: TCP Provider, error: 0 - An existing connection was forcibly closed by the remote host.)'.,Source=Microsoft.DataTransfer.Connectors.MSSQLImport,''Type=Microsoft.Data.SqlClient.SqlException,Message=A transport-level error has occurred when receiving results from the server. (provider: TCP Provider, error: 0 - An existing connection was forcib …
```

- **type** `Win32Exception` · **fp** `f2540e8bf1b7d478`
- **template** `<NAME> Copy Command operation failed with error <NAME>.`
- **values** NAME: Warehouse, A transport-level error has occurred when receiving results from the server. (provider: TCP Provider, error: 0 - An existing connection was forcibly closed by the remote host.)
- **keywords** dwcopy, command, operation, failed, copy

**2.** given code `DWCopyCommandOperationFailed`

```text
ErrorCode=DWCopyCommandOperationFailed,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message='AzureSqlDW' Copy Command operation failed with error 'Not able to validate external location because The remote server returned an error: (403) Forbidden.'.,Source=Microsoft.DataTransfer.Connectors.MSSQLImport,''Type=Microsoft.Data.SqlClient.SqlException,Message=Not able to validate external location because The remote server returned an error: (403) Forbidden.,Source=Framework Microsoft SqlClient Data Provider,'
```

- **type** `SqlException` · **fp** `a7cd78aba0ce4f8c`
- **template** `<NAME> Copy Command operation failed with error <NAME>.`
- **values** NAME: AzureSqlDW, Not able to validate external location because The remote server returned an error: (403) Forbidden.
- **keywords** dwcopy, command, operation, failed, copy

### InvalidParameter (2)

**1.** given code `InvalidParameter`

```text
Failure happened on 'Sink' side. ErrorCode=InvalidParameter,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=The value of the property '' is invalid: 'Invalid 3 part name format for TypeName.'.,Source=,''Type=System.ArgumentException,Message=Invalid 3 part name format for TypeName.,Source=System.Data
```

- **type** `ArgumentException` · **fp** `2c7a3ea58dbac48e` ×2
- **template** `The value of the property <NAME> is invalid: <NAME>.`
- **values** NAME: , Invalid 3 part name format for TypeName.
- **keywords** invalid, parameter, property

**2.** given code `InvalidParameter`

```text
ErrorCode=InvalidParameter,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=The value of the property '' is invalid: 'Cross Partition OFFSET / LIMIT is not supported.'.,Source=,''Type=System.ArgumentException,Message=Cross Partition OFFSET / LIMIT is not supported.,Source=Microsoft.Azure.Documents.Client,'
```

- **type** `ArgumentException` · **fp** `2c7a3ea58dbac48e` ×2
- **template** `The value of the property <NAME> is invalid: <NAME>.`
- **values** NAME: , Cross Partition OFFSET / LIMIT is not supported.
- **keywords** invalid, parameter, property

### JsonInvalidDataFormat (2)

**1.** given code `JsonInvalidDataFormat`

```text
Failure happened on 'Source' side. ErrorCode=JsonInvalidDataFormat,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=Error occurred when deserializing source JSON file ''. Check if the data is in valid JSON object format.,Source=Microsoft.DataTransfer.ClientLibrary,'
```

- **type** `HybridDeliveryException` · **fp** `c259d17c8debee78`
- **template** `Error occurred when deserializing source JSON file '. Check if the data is in valid JSON object format.`
- **values** —
- **keywords** json, invalid, data, format, occurred, when, deserializing, file

**2.** given code `JsonInvalidDataFormat`

```text
Failure happened on 'Source' side. ErrorCode=JsonInvalidDataFormat,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=Error occurred when deserializing source JSON file ''. Check if the data is in valid JSON object format.,Source=Microsoft.DataTransfer.ClientLibrary,''Type=Newtonsoft.Json.JsonReaderException,Message=Unterminated string. Expected delimiter: ". Path '[52417].toMetadata['job Title']', line 1, position 64164387.,Source=Newtonsoft.Json,'
```

- **type** `JsonReaderException` · **fp** `fc2c466b47a02f18`
- **template** `Error occurred when deserializing source JSON file '. Check if the data is in valid JSON object format.`
- **values** —
- **keywords** json, invalid, data, format, occurred, when, deserializing, file

### ParquetJavaInvocationException (2)

**1.** given code `ParquetJavaInvocationException`

```text
Operation on target QCR Load failed: Operation on target Copy failed: ErrorCode=ParquetJavaInvocationException,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=An error occurred when invoking java, message: java.lang.NoClassDefFoundError:org/apache/log4j/Level
total entry:13
org.slf4j.LoggerFactory.bind(LoggerFactory.java:128)
org.slf4j.LoggerFactory.performInitialization(LoggerFactory.java:107)
org.slf4j.LoggerFactory.getILoggerFactory(LoggerFactory.java:295)
org.slf4j.LoggerFactory.getLogger(LoggerFactory.java:269)
org.slf4j.LoggerFactory.getLogger(LoggerFactory.jav …
```

- **type** `JavaBridgeException` · **fp** `2812d4ffdcb452a2`
- **template** `An error occurred when invoking java, message: java.lang.NoClassDefFoundError:<PATH> total entry:<NUM> org.<NAME>.LoggerFactory.bind(LoggerFactory.java:<NUM>) org.<NAME>.LoggerFactory.performInitialization(LoggerFactory.java:<NUM>) org.<NAME>.LoggerFactory.getILoggerFactory(LoggerFactory.java:<NUM>)`
- **values** PATH: org/apache/log4j/Level, apache.parquet, apache.parquet, apache.parquet …; NAME: slf4j, slf4j, slf4j, slf4j …; NUM: 13, 128, 107, 295 …
- **keywords** parquet, java, invocation, exception, occurred, when, invoking, lang

**2.** given code `ParquetJavaInvocationException`

```text
Failure happened on 'Sink' side. ErrorCode=ParquetJavaInvocationException,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=An error occurred when invoking java, message: java.lang.IllegalArgumentException:field ended by ';': expected ';' but got 'State' at line 0: message adms_schema { optional int32 SystemID; optional binary System (UTF8); optional binary Description (UTF8); optional binary Defined State
total entry:10
org.apache.parquet.schema.MessageTypeParser.check(MessageTypeParser.java:215)
org.apache.parquet.schema.MessageTypeParser.addPrimitiveType(MessageTy …
```

- **type** `JavaBridgeException` · **fp** `26295b950ea4270e`
- **template** `An error occurred when invoking java, message: java.lang.IllegalArgumentException:field ended by <NAME>: expected <NAME> but got <NAME> at line <NUM>: message <NAME> { optional <NAME> SystemID; optional binary System (<NAME>); optional binary Description (<NAME>); optional binary Defined State total`
- **values** NAME: ;, ;, State, adms_schema …; PATH: apache.parquet, apache.parquet, apache.parquet, apache.parquet …; NUM: 0, 10, 215, 188 …
- **keywords** parquet, java, invocation, exception, occurred, when, invoking, lang

### UserErrorInvalidColumnMappingColumnNotFound (2)

**1.** given code `UserErrorInvalidColumnMappingColumnNotFound`

```text
ErrorCode=UserErrorInvalidColumnMappingColumnNotFound,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=Column 'C2' specified in column mapping cannot be found in source data.,Source=Microsoft.DataTransfer.ClientLibrary,'
```

- **type** `HybridDeliveryException` · **fp** `a5d6acb5c6bd7a02`
- **template** `Column <NAME> specified in column mapping cannot be found in source data.`
- **values** NAME: C2
- **keywords** user, error, invalid, column, mapping, column, not, found

**2.** given code `UserErrorInvalidColumnMappingColumnNotFound`

```text
ErrorCode=UserErrorInvalidColumnMappingColumnNotFound,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=Invalid column mapping provided to copy activity: '{"Prop_0":"id","Prop_1":"name","Prop_2":"address"}', Detailed message: Column 'Prop_2' defined in column mapping cannot be found in Source structure.. Check column mapping in table definition.,Source=Microsoft.DataTransfer.Common,'
```

- **type** `HybridDeliveryException` · **fp** `bbec732687b10384`
- **template** `Invalid column mapping provided to copy activity: <NAME>, Detailed message: Column <NAME> defined in column mapping cannot be found in Source structure.. Check column mapping in table definition.`
- **values** NAME: {"Prop_0":"id","Prop_1":"name","Prop_2":"address"}, Prop_2
- **keywords** user, error, invalid, column, mapping, column, not, found

### UserErrorInvalidColumnName (2)

**1.** given code `UserErrorInvalidColumnName`

```text
Failure happened on 'Sink' side. ErrorCode=UserErrorInvalidColumnName,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=The column Prop_0 is not found in target side,Source=Microsoft.DataTransfer.ClientLibrary.
```

- **type** `HybridDeliveryException` · **fp** `04c9cf187e043e50`
- **template** `The column <NAME> is not found in target side`
- **values** NAME: Prop_0
- **keywords** user, error, invalid, column, name, found, target

**2.** given code `UserErrorInvalidColumnName`

```text
Operation on target Copy data to staging table failed: Failure happened on 'Sink' side. ErrorCode=UserErrorInvalidColumnName, 'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException, Message=Column name <some_column> is not found in the source table., Source=Microsoft.DataTransfer.DataContracts,'
```

- **type** `HybridDeliveryException` · **fp** `8a61934a347c954f`
- **template** `Column name <some_column> is not found in the source table.`
- **values** —
- **keywords** user, error, invalid, column, name, found, table

### AdlsGen2OperationFailedConcurrentWrite (1)

**1.** given code `AdlsGen2OperationFailedConcurrentWrite`

```text
Operation on target ... : Operation on target .....failed: Failure happened on 'Sink' side. ErrorCode=AdlsGen2OperationFailedConcurrentWrite,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=Error occurred when trying to upload a file. It's possible because you have multiple concurrent copy activities runs writing to the same file '...folder path...'. Check your ADF configuration.,Source=Microsoft.DataTransfer.ClientLibrary,''Type=Microsoft.Azure.Storage.Data.Models.ErrorSchemaException,Message=Operation returned an invalid status code 'PreconditionFailed',Source=Micro …
```

- **type** `ErrorSchemaException` · **fp** `1987ef4b43178bbd`
- **template** `Error occurred when trying to upload a file. It<NAME>...folder path...'. Check your ADF configuration.`
- **values** NAME: s possible because you have multiple concurrent copy activities runs writing to the same file 
- **keywords** adls, gen2, operation, failed, concurrent, write, occurred, when

### DF-Executor-InvalidOutputColumns (1)

**1.** given code `DF-Executor-InvalidOutputColumns`

```text
'StatusCode':'DF-Executor-InvalidOutputColumns','Message':'Job failed due to reason: The result has 0 output columns. Please ensure at least one column is mapped. The schema is late binding.
```

- **type** `—` · **fp** `51307f5e473a622a`
- **template** `<NAME>:<NAME>:'Job failed due to reason: The result has <NUM> output columns. Please ensure at least one column is mapped. The schema is late binding.`
- **values** NAME: StatusCode, DF-Executor-InvalidOutputColumns, Message; NUM: 0
- **keywords** df-executor-invalid, output, columns, job, due, reason, result, ensure

### DF-Executor-SourceInvalidPayload (1)

**1.** given code `DF-Executor-SourceInvalidPayload`

```text
Operation on target Data flow1 failed: {"StatusCode":"DF-Executor-SourceInvalidPayload","Message":"Job failed due to reason: Data preview, debug, and pipeline data flow execution failed because container does not exist","Details":""}
```

- **type** `—` · **fp** `b40a14df3bb054f6`
- **template** `Job failed due to reason: Data preview, debug, and pipeline data flow execution failed because container does not exist<NAME>Details<NAME>"}`
- **values** NAME: ,, :
- **keywords** df-executor-source, invalid, payload, job, due, reason, preview, debug

### DF-Executor-UserError (1)

**1.** given code `DF-Executor-UserError`

```text
Job failed due to reason: at Sink 'sink1': Exception is happened while writing error rows to storage.
```

- **type** `—` · **fp** `87d4ca7556b2701b`
- **template** `Job failed due to reason: at Sink <NAME>: Exception is happened while writing error rows to storage.`
- **values** NAME: sink1
- **keywords** df-executor-user, error, job, due, reason, sink, while, writing

### RestSourceCallFailed (1)

**1.** given code `RestSourceCallFailed`

```text
Failure happened on 'Source' side. ErrorCode=RestSourceCallFailed,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=The HttpStatusCode 404 indicates failure. Request URL: https://joyfolie.myshopify.com/admin/api/2021-07/%3Chttps://joyfolie.myshopify.com/admin/api/2021-07/products.json?limit=50&page_info=eyJsYXN0X2lkIjo0NjI0ODcyMjEwNDkwLCJsYXN0X3ZhbHVlIjoiKk5FVyogQmFlIFNraXJ0IGluIE9jaHJlIiwiZGlyZWN0aW9uIjoibmV4dCJ9%3E;%20rel=%22next%22 Response payload:{"errors":"Not Found"},Source=Microsoft.DataTransfer.ClientLibrary,'
```

- **type** `HybridDeliveryException` · **fp** `74d1fffc16c4d666`
- **template** `The HttpStatusCode <NUM> indicates failure. Request URL: <URL>;%<NAME>=%<NAME>%<NUM> Response payload:{<NAME>:<NAME>}`
- **values** URL: https://joyfolie.myshopify.com/admin/api/2021-07/%3Chttps://joyfolie.myshopify.com/admin/api/2021-07/products.json?limit=50&page_info=eyJsYXN0X2lkIjo0NjI0ODcyMjEwNDkwLCJsYXN0X3ZhbHVlIjoiKk5FVyogQmFlIFNraXJ0IGluIE9jaHJlIiwiZGlyZWN0aW9uIjoibmV4dCJ9%3E; NAME: errors, Not Found, 20rel, 22next; NUM: 404, 22
- **keywords** rest, source, call, failed, httpstatuscode, indicates, request, url

### SftpPathNotFound (1)

**1.** given code `SftpPathNotFound`

```text
Failure happened on 'Sink' side. ErrorCode=SftpPathNotFound,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=Can't find SFTP path '/Genesys Sample Call Recordings/callrecordings/00QTLVGRKG8BF9E18AU362LAES06QH9J/00QTLVGRKG8BF9E18AU362LAES06QH9J_2021-08-23_13-34-01-00QTLVGRKG8BF9E18AU362LAES06QH9J_fad2973a343a4fe88ddff263533880df_2021_08_23_13_34_02_4Z58Hvt8RxO1jw780NnUfA.mp4'. Please check if the path exists. If the path you configured does not start with '/', note it is a relative path under the given user's default folder '/'.,Source=Microsoft.DataTransfer.ClientLibr …
```

- **type** `SftpPathNotFoundException` · **fp** `07d33ffcd7cc3b49`
- **template** `Can<NAME>/Genesys Sample Call <PATH><NAME>/<NAME>s default folder <NAME>.`
- **values** NAME: t find SFTP path , . Please check if the path exists. If the path you configured does not start with , , note it is a relative path under the given user, /; PATH: Recordings/callrecordings/00QTLVGRKG8BF9E18AU362LAES06QH9J/00QTLVGRKG8BF9E18AU362LAES06QH9J_2021-08-23_13-34-01-00QTLVGRKG8BF9E18AU362LAES06QH9J_fad2973a343a4fe88ddff263533880df_2021_08_23_13_34_02_4Z58Hvt8RxO1jw780NnUfA.mp4
- **keywords** sftp, path, not, found, can, genesys, sample, call

### SnowflakeExportCopyCommandValidationFailed (1)

**1.** given code `SnowflakeExportCopyCommandValidationFailed`

```text
ErrorCode=SnowflakeExportCopyCommandValidationFailed, 'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException, Message=Snowflake Export Copy Command validation failed: 'The Snowflake copy command payload is invalid. Cannot specify property: column mapping, Source=Microsoft.DataTransfer.ClientLibrary,'
```

- **type** `HybridDeliveryException` · **fp** `d07f86761fe18534`
- **template** `Snowflake Export Copy Command validation failed: 'The Snowflake copy command payload is invalid. Cannot specify property: column mapping`
- **values** —
- **keywords** snowflake, export, copy, command, validation, failed, payload, invalid

### SqlInvalidDbQueryString (1)

**1.** given code `SqlInvalidDbQueryString`

```text
Failure happened on 'Source' side. ErrorCode=SqlInvalidDbQueryString,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=The specified SQL Query is not valid. It could be caused by that the query doesn't return any data. Invalid query: 'INSERT INTO dbo.sampletable (id ,name ,Decription ,Details ,Status ,Failure ,date) VALUES('13', 'test', 'test', ' ', 'Success', 'NULL', '2023/08/22' )',Source=Microsoft.DataTransfer.ClientLibrary,'
```

- **type** `HybridDeliveryException` · **fp** `e166eb8ba60c9886`
- **template** `The specified SQL Query is not valid. It could be caused by that the query doesn<NAME>INSERT INTO dbo.sampletable (id ,name ,Decription ,Details ,Status ,Failure ,date) VALUES(<NAME> )'`
- **values** NAME: t return any data. Invalid query: , 13, test, test …
- **keywords** sql, invalid, query, string, specified, valid, could, caused

### UserErrorDataStoreServiceThrottling (1)

**1.** given code `UserErrorDataStoreServiceThrottling`

```text
ErrorCode=UserErrorDataStoreServiceThrottling,'Type=Microsoft.DataTransfer.Common.Shared.DataStoreThrottlingException,Message=Failed with potential throttling error when accessing AzureBlobFS at side. You are suggested to check and increase the allowed request rate for the data store, or reduce the concurrent workload. More details please refer https://learn.microsoft.com/en-us/azure/data-factory/copy-activity-performance-troubleshooting.. Details: Account: 'xxxx'. FileSystem: 'xxx'. ErrorCode: 'OperationTimedOut'. Message: 'Operation could not be completed within the specified time.'. Request …
```

- **type** `ErrorSchemaException` · **fp** `611b129ee6b5b24b`
- **template** `Failed with potential throttling error when accessing AzureBlobFS at side. You are suggested to check and increase the allowed request rate for the data store, or reduce the concurrent workload. More details please refer <URL> Details: Account: <NAME>. FileSystem: <NAME>. ErrorCode: <NAME>. Message:`
- **values** URL: https://learn.microsoft.com/en-us/azure/data-factory/copy-activity-performance-troubleshooting..; ID: af91c927-301f-0058-6732-e89460000000; TS: 05:28:29; NAME: xxxx, xxx, OperationTimedOut, Operation could not be completed within the specified time. …
- **keywords** user, error, data, store, service, throttling, potential, when

### UserErrorFailedToGetAccessTokenByServicePrincipal (1)

**1.** given code `UserErrorFailedToGetAccessTokenByServicePrincipal`

```text
Failure happened on 'Sink' side. ErrorCode=UserErrorFailedToGetAccessTokenByServicePrincipal,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=There was an error deserializing the object of type Microsoft.IdentityModel.Clients.ActiveDirectory.Internal.OAuth2.TokenResponse. Encountered unexpected character '<'.,Source=Microsoft.DataTransfer.ClientLibrary,''Type=System.Runtime.Serialization.SerializationException,Message=There was an error deserializing the object of type Microsoft.IdentityModel.Clients.ActiveDirectory.Internal.OAuth2.TokenResponse. Encountered unexpecte …
```

- **type** `XmlException` · **fp** `76c4a7bdadf85725`
- **template** `There was an error deserializing the object of type Microsoft.IdentityModel.Clients.ActiveDirectory.Internal.<NAME>.TokenResponse. Encountered unexpected character <NAME>.`
- **values** NAME: <, OAuth2
- **keywords** user, error, failed, get, access, token, service, principal

### UserErrorSalesforceOperationFailed (1)

**1.** given code `UserErrorSalesforceOperationFailed`

```text
Operation on target Copy data1 failed: Failure happened on 'Sink' side. ErrorCode=UserErrorSalesforceOperationFailed,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=[BatchFailure]JobId:7503B000005V9v5QAC, BatchId:7513B000006IF3pQAG, Message:InvalidBatch : Field name not found : ConnectionReceivedId,Source=Microsoft.DataTransfer.Runtime.SalesforceConnector,'
```

- **type** `HybridDeliveryException` · **fp** `10c6ce1a7b80d9bc`
- **template** `<LIST>JobId:<NAME>, BatchId:<NAME>, Message:InvalidBatch : Field name not found : ConnectionReceivedId`
- **values** LIST: [BatchFailure]; NAME: 7503B000005V9v5QAC, 7513B000006IF3pQAG
- **keywords** user, error, salesforce, operation, failed, jobid, batchid, invalidbatch

### UserErrorSourceDataContainsMoreColumnsThanDefined (1)

**1.** given code `UserErrorSourceDataContainsMoreColumnsThanDefined`

```text
Copy activity encountered a user error: ErrorCode=UserErrorSourceDataContainsMoreColumnsThanDefined,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=Error found when processing 'Csv/Tsv Format Text' source '01/1001464881_1001464795_2015-01-01_1.13.05.152__1000.xml' with row number 1: found more columns than expected column count: 1.,Source=Microsoft.DataTransfer.Common,'.
```

- **type** `HybridDeliveryException` · **fp** `d8a6c1fd5d828153`
- **template** `Error found when processing <NAME> source <NAME> with row number <NUM>: found more columns than expected column count: <NUM>.`
- **values** NAME: Csv/Tsv Format Text, 01/1001464881_1001464795_2015-01-01_1.13.05.152__1000.xml; NUM: 1, 1
- **keywords** user, error, source, data, contains, more, columns, than

### UserErrorSourceQueryTimeout (1)

**1.** given code `UserErrorSourceQueryTimeout`

```text
Failure happened on 'Source' side. ErrorCode=UserErrorSourceQueryTimeout,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=Query source database timeout after '7200' seconds.,Source=Microsoft.DataTransfer.DataContracts,''Type=System.TimeoutException,Message=,Source=Microsoft.DataTransfer.DataContracts,'
```

- **type** `TimeoutException` · **fp** `e4ebf63041985c59`
- **template** `Query source database timeout after <NAME> seconds.`
- **values** NAME: 7200
- **keywords** user, error, source, query, timeout, database, after, seconds

### UserErrorSqlBulkCopyInvalidColumnLength (1)

**1.** given code `UserErrorSqlBulkCopyInvalidColumnLength`

```text
ErrorCode=UserErrorSqlBulkCopyInvalidColumnLength,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=SQL Bulk Copy failed due to received an invalid column length from the bcp client.,Source=Microsoft.DataTransfer.ClientLibrary,''Type=System.Data.SqlClient.SqlException,Message=The service has encountered an error processing your request. Please try again. Error code 4815.\r\nA severe error occurred on the current command.  The results&#44; if any&#44; should be discarded.,Source=.Net SqlClient Data Provider,SqlErrorNumber=40197,Class=20,ErrorCode=-2146232060,State=1,Err …
```

- **type** `SqlException` · **fp** `9045bba0bb95026d`
- **template** `SQL Bulk Copy failed due to received an invalid column length from the bcp client.`
- **values** —
- **keywords** user, error, sql, bulk, copy, invalid, column, length

### UserErrorSqlDWCopyCommandError (1)

**1.** given code `UserErrorSqlDWCopyCommandError`

```text
ErrorCode=UserErrorSqlDWCopyCommandError,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=SQL DW Copy Command operation failed with error 'Column 'PACKAGE_SIZE' of type 'FLOAT' is not compatible with external data type 'Parquet physical type: BYTE_ARRAY, logical type: UTF8', please try with 'VARCHAR(8000)'.
```

- **type** `HybridDeliveryException` · **fp** `bc5b8ebac50f2c07`
- **template** `SQL DW Copy Command operation failed with error <NAME><NAME><NAME>FLOAT<NAME>Parquet physical type: <NAME>, logical type: <NAME><NAME>VARCHAR(<NUM>)'.`
- **values** NAME: Column ,  of type ,  is not compatible with external data type , , please try with  …; NUM: 8000
- **keywords** user, error, sql, dwcopy, command, error, copy, float

## synapse (29)

### — (13)

**1.** given code `—`

```text
Operation on target Fact_XX failed: Operation on target Merge_XX failed: Execution fail against sql server. Sql error number: 100090. Error Message: Updating a distribution key column in a MERGE statement is not supported.
```

- **type** `—` · **fp** `b00c5ff951711393`
- **template** `Execution fail against sql server. Sql error number: <NUM>. Error Message: Updating a distribution key column in a MERGE statement is not supported.`
- **values** NUM: 100090
- **keywords** execution, against, sql, server, number, updating, distribution, key

**2.** given code `6000`

```text
{
  "code": 400,
  "message": "Failed to run notebook due to invalid request. [Error: Not supported language in Synapse: ]",
  "result": {
    "errorMessage": null,
    "details": null
  }
}
```

- **type** `—` · **fp** `a17724cd583e314c`
- **template** `{ <NAME>: <NUM>, <NAME>: <NAME>: { <NAME>: null, <NAME>: null } }`
- **values** NAME: code, message, Failed to run notebook due to invalid request. [Error: Not supported language in Synapse: ], result …; NUM: 400
- **keywords** null

**3.** given code `—`

```text
External table 'serverlessdbtest.dbo.CAN2_gnssspeed' is not accessible because content of directory cannot be listed.
```

- **type** `—` · **fp** `d7df6b7ed3057612`
- **template** `External table <NAME> is not accessible because content of directory cannot be listed.`
- **values** NAME: serverlessdbtest.dbo.CAN2_gnssspeed
- **keywords** external, table, accessible, because, content, directory, cannot, listed

**4.** given code `145`

```text
Internal Server Error in Synapse batch operation: '[plugins.C4T-PRIV-SAW-CAS.IR-Test.19 WorkspaceType: CCID:] [Monitoring] Livy Endpoint=[ https://hubservice1.westeurope.azuresynapse.net:8001/api/v1.0/publish/c1e53348-b457-4afd-a61d-76553bdd369c ]. Livy Id=[4] Job failed during run time with state=[dead].'.
```

- **type** `—` · **fp** `1558b6098eb8b4a8`
- **template** `Internal Server Error in Synapse batch operation: <NAME>.`
- **values** URL: https://hubservice1.westeurope.azuresynapse.net:8001/api/v1.0/publish/c1e53348-b457-4afd-a61d-76553bdd369c; NAME: [plugins.C4T-PRIV-SAW-CAS.IR-Test.19 WorkspaceType: CCID:] [Monitoring] Livy Endpoint=[ <URL> ]. Livy Id=[4] Job failed during run time with state=[dead].
- **keywords** internal, server, synapse, batch

**5.** given code `2108`

```text
{"odata.error":{"code":"-2147024891, System.UnauthorizedAccessException","message":{"lang":"en-US","value":"Attempted to perform an unauthorized operation."}}}
```

- **type** `—` · **fp** `5b3fda8a1368d318`
- **template** `{<NAME>:{<NAME>:<NAME>:{<NAME>:<NAME>:<NAME>}}}`
- **values** NAME: odata.error, code, -2147024891, System.UnauthorizedAccessException, message …
- **keywords** —

**6.** given code `—`

```text
Operation on target LoadFactSalesDoc_without_DimResource failed: MessageQueueFullException: The message queue is full or is completed and cannot accept more items.
```

- **type** `—` · **fp** `ae0bfc63a8e2303c`
- **template** `MessageQueueFullException: The message queue is full or is completed and cannot accept more items.`
- **values** —
- **keywords** messagequeuefullexception, queue, full, completed, cannot, accept, items

**7.** given code `—`

```text
Py4JJavaError: An error occurred while calling o1216.load.
: org.apache.spark.SparkException: Job aborted due to stage failure: Task 0 in stage 0.0 failed 4 times, most recent failure: Lost task 0.3 in stage 0.0 (TID 3) (vm-5fb81713 executor 1): org.apache.spark.SparkException: Exception thrown in awaitResult:
```

- **type** `—` · **fp** `54772d24397866df` ×2
- **template** `<NAME>: An error occurred while calling <NAME>.load. : org.apache.spark.SparkException: Job aborted due to stage failure: Task <NUM> in stage <NUM> failed <NUM> times, most recent failure: Lost task <NUM> in stage <NUM> (TID <NUM>) (vm-<NAME> executor <NUM>): org.apache.spark.SparkException: Excepti`
- **values** NAME: Py4JJavaError, o1216, 5fb81713; NUM: 0, 0.0, 4, 0.3 …
- **keywords** occurred, while, calling, load, org, apache, spark, sparkexception

**8.** given code `6002`

```text
Py4JJavaError: An error occurred while calling o666.csv.\n: java.nio.file.AccessDeniedException: Operation failed: \"This request is not authorized to perform this operation using this permission.\", 403, HEAD, https://bcnpricing.dfs.core.windows.net/test/test/data/output/test_df3.csv?upn=false&action=getStatus&timeout=90
```

- **type** `—` · **fp** `0b8ba639dfed2700` ×2
- **template** `<NAME>: An error occurred while calling <PATH>. : java.nio.file.AccessDeniedException: Operation failed: \<NAME>, <NUM>, HEAD, <URL>`
- **values** URL: https://bcnpricing.dfs.core.windows.net/test/test/data/output/test_df3.csv?upn=false&action=getStatus&timeout=90; NAME: This request is not authorized to perform this operation using this permission.\, Py4JJavaError; PATH: o666.csv; NUM: 403
- **keywords** occurred, while, calling, java, nio, file, accessdeniedexception, head

**9.** given code `—`

```text
Py4JJavaError: An error occurred while calling o1659.load. : Status code: -1 error code: null error message: InvalidAbfsRestOperationExceptionjava.net.UnknownHostException: sasyoccutableaudev.dfs.core.windows.net
```

- **type** `—` · **fp** `54772d24397866df` ×2
- **template** `<NAME>: An error occurred while calling <NAME>.load. : Status code: <NUM> error code: null error message: InvalidAbfsRestOperationExceptionjava.net.UnknownHostException: sasyoccutableaudev.dfs.core.windows.net`
- **values** NAME: Py4JJavaError, o1659; NUM: -1
- **keywords** occurred, while, calling, load, status, code, null, invalidabfsrestoperationexceptionjava

**10.** given code `—`

```text
Py4JJavaError: An error occurred while calling o4538.csv.
: java.nio.file.AccessDeniedException: Operation failed: "This request is not authorized to perform this operation.", 403, HEAD, https://myaccount.dfs.core.windows.net/fsglasdp/?upn=false&action=getAccessControl&timeout=90
```

- **type** `—` · **fp** `0b8ba639dfed2700` ×2
- **template** `<NAME>: An error occurred while calling <PATH>. : java.nio.file.AccessDeniedException: Operation failed: <NAME>, <NUM>, HEAD, <URL>`
- **values** URL: https://myaccount.dfs.core.windows.net/fsglasdp/?upn=false&action=getAccessControl&timeout=90; NAME: This request is not authorized to perform this operation., Py4JJavaError; PATH: o4538.csv; NUM: 403
- **keywords** occurred, while, calling, java, nio, file, accessdeniedexception, head

**11.** given code `—`

```text
Py4JJavaError: An error occurred while calling z:com.microsoft.spark.notebook.visualization.display.getDisplayResultForIPython.
: org.apache.spark.SparkException: Job aborted due to stage failure: Task 34 in stage 9.0 failed 4 times, most recent failure: Lost task 34.3 in stage 9.0 (TID 463) (vm-d2249026 executor 5): org.apache.spark.sql.execution.QueryExecutionException: Parquet column cannot be converted in file abfss://******@dsprdsapisco.dfs.core.windows.net/opc/A14/20230626T211927.parquet. Column: [value], Expected: string, Found: DOUBLE
```

- **type** `—` · **fp** `f27e8b36e7619878`
- **template** `<NAME>: An error occurred while calling z:com.microsoft.spark.notebook.visualization.display.getDisplayResultForIPython. : org.apache.spark.SparkException: Job aborted due to stage failure: Task <NUM> in stage <NUM> failed <NUM> times, most recent failure: Lost task <NUM> in stage <NUM> (TID <NUM>) `
- **values** URL: abfss://******@dsprdsapisco.dfs.core.windows.net/opc/A14/20230626T211927.parquet.; LIST: [value]; PATH: spark.sql; NAME: Py4JJavaError, d2249026; NUM: 34, 9.0, 4, 34.3 …
- **keywords** occurred, while, calling, com, microsoft, spark, notebook, visualization

**12.** given code `—`

```text
Py4JJavaError: An error occurred while calling o4549.save. : org.apache.spark.SparkException: Job 106 cancelled because SparkContext was shut down
```

- **type** `—` · **fp** `a4e11cd894fa05ae`
- **template** `<NAME>: An error occurred while calling <NAME>.save. : org.apache.spark.SparkException: Job <NUM> cancelled because SparkContext was shut down`
- **values** NAME: Py4JJavaError, o4549; NUM: 106
- **keywords** occurred, while, calling, save, org, apache, spark, sparkexception

**13.** given code `3204`

```text
Databricks execution failed with error state: InternalError, error message: Cluster 0106-082338-jk5fnd4k was terminated while waiting on it to be ready: Cluster 0106-082338-jk5fnd4k is in unexpected state Terminated: INVALID_ARGUMENT(CLIENT_ERROR): databricks_error_message:Operation could not be completed as it results in exceeding approved Total Regional Cores quota. Additional details - Deployment Model: Resource Manager, Location: eastus, Current Limit: 10, Current Usage: 8, Additional Required: 4, (Minimum) New Limit Required: 12. Submit a request for Quota increase at https://aka.ms/Prodp …
```

- **type** `—` · **fp** `55b680e771edfd5b`
- **template** `Databricks execution failed with error state: InternalError, error message: Cluster <NUM>-<NUM>-<NAME> was terminated while waiting on it to be ready: Cluster <NUM>-<NUM>-<NAME> is in unexpected state Terminated: <NAME>(<NAME>): <NAME>:Operation could not be completed as it results in exceeding appr`
- **values** URL: https://aka.ms/ProdportalCRP/#blade/Microsoft_Azure_Capacity/UsageAndQuota.ReactView/Parameters/%7B%22subscriptionId%22:%22666e43b3-6184-40e8-9fdf-561360dc8ea2%22, https://adb-4181940747004694.14.azuredatabricks.net/?o=4181940747004694#job/382562378777542/run/522321628328303.; NAME: jk5fnd4k, jk5fnd4k, INVALID_ARGUMENT, CLIENT_ERROR …; NUM: 0106, 082338, 0106, 082338 …
- **keywords** databricks, execution, state, internalerror, cluster, terminated, while, waiting

### SqlOperationFailed (3)

**1.** given code `SqlOperationFailed`

```text
Operation on target Move InvItemDist to DP failed: Failure happened on 'Source' side. ErrorCode=SqlOperationFailed,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=A database operation failed with the following error: 'Incorrect syntax near 'FORMAT'.',Source=,''Type=System.Data.SqlClient.SqlException,Message=Incorrect syntax near 'FORMAT'.,Source=.Net SqlClient Data Provider,SqlErrorNumber=102,Class=15,ErrorCode=-2146232060,State=1,Errors=[{Class=15,Number=102,State=1,Message=Incorrect syntax near 'FORMAT'.,},],'
```

- **type** `SqlException` · **fp** `b4dd7fc36f9c2fee`
- **template** `A database operation failed with the following error: <NAME>FORMAT<NAME>`
- **values** NAME: Incorrect syntax near , .
- **keywords** sql, operation, failed, database, following, format

**2.** given code `SqlOperationFailed`

```text
Operation on target Copy_oe4 failed: ErrorCode=SqlOperationFailed,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=A database operation failed with the following error: 'Incorrect syntax near 'HEAP'.',Source=,''Type=System.Data.SqlClient.SqlException,Message=Incorrect syntax near 'HEAP'.,Source=.Net SqlClient Data Provider,SqlErrorNumber=102,Class=15,ErrorCode=-2146232060,State=1,Errors=[{Class=15,Number=102,State=1,Message=Incorrect syntax near 'HEAP'.,},],'
```

- **type** `SqlException` · **fp** `1ae2fade05add531` ×2
- **template** `A database operation failed with the following error: <NAME>HEAP<NAME>`
- **values** NAME: Incorrect syntax near , .
- **keywords** sql, operation, failed, database, following, heap

**3.** given code `SqlOperationFailed`

```text
Operation on target Copy_ky9 failed: ErrorCode=SqlOperationFailed,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=A database operation failed with the following error: 'Incorrect syntax near 'HEAP'.',Source=,''Type=System.Data.SqlClient.SqlException,Message=Incorrect syntax near 'HEAP'.,Source=.Net SqlClient Data Provider,SqlErrorNumber=102,Class=15,ErrorCode=-2146232060,State=1,Errors=[{Class=15,Number=102,State=1,Message=Incorrect syntax near 'HEAP'.,},],'
```

- **type** `SqlException` · **fp** `1ae2fade05add531` ×2
- **template** `A database operation failed with the following error: <NAME>HEAP<NAME>`
- **values** NAME: Incorrect syntax near , .
- **keywords** sql, operation, failed, database, following, heap

### AVAILABLE_COMPUTE_CAPACITY_EXCEEDED (1)

**1.** given code `AVAILABLE_COMPUTE_CAPACITY_EXCEEDED`

```text
AVAILABLE_COMPUTE_CAPACITY_EXCEEDED: Livy session has failed. Session state: Error. Error code: AVAILABLE_COMPUTE_CAPACITY_EXCEEDED. Your job requested 12 vcores. However, the pool only has 0 vcores available out of quota of 12 vcores. Try ending the running job(s) in the pool, reducing the numbers of vcores requested, increasing the pool maximum size or using another pool. Source: User.
```

- **type** `—` · **fp** `fed83545a3cee519`
- **template** `<NAME>: Livy session has failed. Session state: Error. Error code: <NAME>. Your job requested <NUM> vcores. However, the pool only has <NUM> vcores available out of quota of <NUM> vcores. Try ending the running job(s) in the pool, reducing the numbers of vcores requested, increasing the pool maximum`
- **values** NAME: AVAILABLE_COMPUTE_CAPACITY_EXCEEDED, AVAILABLE_COMPUTE_CAPACITY_EXCEEDED; NUM: 12, 0, 12
- **keywords** available, compute, capacity, exceeded, livy, session, state, code

### BadRequest (1)

**1.** given code `BadRequest`

```text
Error code: OK
Inner error code: BadRequest
Message: Databricks Activity Not Supported.
```

- **type** `—` · **fp** `4717184beca372db`
- **template** `Error code: OK Inner error code: BadRequest Message: Databricks Activity Not Supported.`
- **values** —
- **keywords** bad, request, code, inner, badrequest, databricks, activity, supported

### DF-Executor-OutOfMemoryError (1)

**1.** given code `DF-Executor-OutOfMemoryError`

```text
Job failed due to reason: Cluster ran into out of memory issue during execution, please retry using an integration runtime with bigger core count and/or memory optimized compute type. Details:null
```

- **type** `—` · **fp** `0905b56a645eafc3`
- **template** `Job failed due to reason: Cluster ran into out of memory issue during execution, please retry using an integration runtime with bigger core count <PATH> memory optimized compute type. Details:null`
- **values** PATH: and/or
- **keywords** df-executor-out, memory, error, job, due, reason, cluster, ran

### DelimitedTextMoreColumnsThanDefined (1)

**1.** given code `DelimitedTextMoreColumnsThanDefined`

```text
ErrorCode=DelimitedTextMoreColumnsThanDefined,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=Error found when processing 'Csv/Tsv Format Text' source 'PomOP_PRF_Status20240311_033449-00001.txt' with row number 11: found more columns than expected column count 14.,Source=Microsoft.DataTransfer.Common,'
```

- **type** `HybridDeliveryException` · **fp** `1f68b91cbe11fb06`
- **template** `Error found when processing <NAME> source <NAME> with row number <NUM>: found more columns than expected column count <NUM>.`
- **values** NAME: Csv/Tsv Format Text, PomOP_PRF_Status20240311_033449-00001.txt; NUM: 11, 14
- **keywords** delimited, text, more, columns, than, defined, found, when

### EXCEPTION_DURING_SPARK_JOB_CLEANUP (1)

**1.** given code `EXCEPTION_DURING_SPARK_JOB_CLEANUP`

```text
[plugins.mooboo9-synapse.mooboo9cluster.479 WorkspaceType:<Synapse> CCID:<dd232b79-7565-4825-bf5c-af847424a079>]. [Cleanup] -> [Ended] JobResult=[Cancelled] LivyJobState=[idle]. Unable to kill livy job.
```

- **type** `—` · **fp** `e1d1962091f7c225`
- **template** `[plugins.<NAME>-synapse.<NAME>.<NUM> WorkspaceType:<Synapse> CCID:<<ID>>]. <LIST> -> <LIST> JobResult=<LIST> LivyJobState=<LIST>. Unable to kill livy job.`
- **values** ID: dd232b79-7565-4825-bf5c-af847424a079; LIST: [Cleanup], [Ended], [Cancelled], [idle]; NAME: mooboo9, mooboo9cluster; NUM: 479
- **keywords** exception, during, spark, job, cleanup, plugins, synapse, workspacetype

### FlowRunSizeLimitExceeded (1)

**1.** given code `FlowRunSizeLimitExceeded`

```text
ErrorCode=FlowRunSizeLimitExceeded, ErrorMessage=Triggering the pipeline failed due to large run size. This could happen when a run has a large number of activities or large inputs used in some of the activities, including parameters.
```

- **type** `—` · **fp** `cbfa24b5372c2f26`
- **template** `Triggering the pipeline failed due to large run size. This could happen when a run has a large number of activities or large inputs used in some of the activities, including parameters.`
- **values** —
- **keywords** flow, run, size, limit, exceeded, triggering, pipeline, due

### LIVY_JOB_STATE_DEAD (1)

**1.** given code `LIVY_JOB_STATE_DEAD`

```text
[plugins.synapse-ent-tekura.sparkpoolsmall.180 WorkspaceType:<Synapse> CCID:<b6f6c9c4-250d-44c3-9c28-bce4525c42df>] [Monitoring] Livy Endpoint=[https://<url>:8001/api/v1.0/publish/1567bc8e-206c-475f-bf1f-7c550c17a6d6]. Livy Id=[23] Job failed during run time with state=[dead].
```

- **type** `—` · **fp** `6c4025bfb651600b`
- **template** `[plugins.synapse-ent-tekura.sparkpoolsmall.<NUM> WorkspaceType:<Synapse> CCID:<<ID>>] <LIST> Livy Endpoint=[https://<url>:<PATH>/<ID>]. Livy Id=<LIST> Job failed during run time with state=<LIST>.`
- **values** ID: b6f6c9c4-250d-44c3-9c28-bce4525c42df, 1567bc8e-206c-475f-bf1f-7c550c17a6d6; LIST: [Monitoring], [23], [dead]; PATH: 8001/api/v1.0/publish; NUM: 180
- **keywords** livy, job, state, dead, plugins, synapse, ent, tekura

### ParquetInvalidColumnName (1)

**1.** given code `ParquetInvalidColumnName`

```text
ErrorCode=ParquetInvalidColumnName,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=The column name is invalid. Column name cannot contain these character:[,;{}()\n\t=],Source=Microsoft.DataTransfer.Common,'
```

- **type** `HybridDeliveryException` · **fp** `6ef4cd1ed8aa82fb`
- **template** `The column name is invalid. Column name cannot contain these character:<LIST>`
- **values** LIST: [,;{}() \t=]
- **keywords** parquet, invalid, column, name, cannot, contain, these, character

### RestSourceCallFailed (1)

**1.** given code `RestSourceCallFailed`

```text
Failure happened on 'Source' side. ErrorCode=RestSourceCallFailed,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=The HttpStatusCode 401 indicates failure.
Request URL: https://api.box.com/2.0/files/:984786751561/content
Response payload:,Source=Microsoft.DataTransfer.ClientLibrary,'
```

- **type** `HybridDeliveryException` · **fp** `bcd2ab16c507057b`
- **template** `The HttpStatusCode <NUM> indicates failure. Request URL: <URL> Response payload:`
- **values** URL: https://api.box.com/2.0/files/:984786751561/content; NUM: 401
- **keywords** rest, source, call, failed, httpstatuscode, indicates, request, url

### SapOdpOperationFailed (1)

**1.** given code `SapOdpOperationFailed`

```text
Operation on target TARGETNAME failed: {"StatusCode":"DF-SAPODP-ExecuteFuncModuleWithPointerFailed","Message":"Job failed due to reason: at Source 'KNA1': Error Message: DF-SAPODP-012 - SapOdp copy activity failure with run id: c194054d-876f-4684-8105-9e038ca3b7e1, error code: 2200 and error message: Failure happened on 'Source' side. ErrorCode=SapOdpOperationFailed,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=Sap Odp operation 'Execute function module RODPS_REPL_ODP_FETCH with pointer 20221107095340.000094000, package id 20221107095436.000183000' failed. Error Nu …
```

- **type** `HybridDeliveryException` · **fp** `ceccd3d0bb487bab`
- **template** `Sap Odp operation <NAME> failed. Error Number: <NAME>, error message: <NAME>`
- **values** NAME: Execute function module RODPS_REPL_ODP_FETCH with pointer 20221107095340.000094000, package id 20221107095436.000183000, 404, DataSource QUEUENAME~KNA1 does not exist in version A
- **keywords** sap, odp, operation, failed, number

### UnsupportedDataStoreEndpoint (1)

**1.** given code `UnsupportedDataStoreEndpoint`

```text
Operation on target Copy failed: ErrorCode=UnsupportedDataStoreEndpoint,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=The data store endpoint is not supported in 'AzureBlobFS' connector. Error message : 'The domain of this endpoint is not in allow list. Original endpoint: '::redacted::.blob.core.windows.net'',Source=Microsoft.DataTransfer.ClientLibrary,''Type=Microsoft.DataTransfer.SecurityValidation.Exceptions.UrlValidationException,Message=The domain of this endpoint is not in allow list. Original endpoint: '::redacted::.blob.core.windows.net',Source=Microsoft.Da …
```

- **type** `UrlValidationException` · **fp** `ac858fef2335b4b5`
- **template** `The data store endpoint is not supported in <NAME> connector. Error message : <NAME>::redacted::.blob.core.windows.net'`
- **values** NAME: AzureBlobFS, The domain of this endpoint is not in allow list. Original endpoint: 
- **keywords** unsupported, data, store, endpoint, supported, connector, redacted, blob

### UserErrorFailedFileOperation (1)

**1.** given code `UserErrorFailedFileOperation`

```text
Operation on target Copy data1_copy1 failed: Failure happened on 'Sink' side. ErrorCode=UserErrorFailedFileOperation,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=Upload file failed at path tfs/OU Cosmos Data/LATAM/fact\dl-br-prod.,Source=Microsoft.DataTransfer.Common,''Type=Microsoft.Azure.Documents.RequestTimeoutException,Message=Request timed out.
```

- **type** `RequestTimeoutException` · **fp** `811eb88df208e309`
- **template** `Upload file failed at path <PATH> Cosmos <PATH>`
- **values** PATH: tfs/OU, Data/LATAM/fact\dl-br-prod.
- **keywords** user, error, failed, file, operation, upload, path, cosmos

### UserErrorSqlDWCopyCommandError (1)

**1.** given code `UserErrorSqlDWCopyCommandError`

```text
ErrorCode=UserErrorSqlDWCopyCommandError,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=SQL DW Copy Command operation failed with error 'HdfsBridge::recordReaderFillBuffer - Unexpected error encountered filling record reader buffer: ClassCastException: ',Source=Microsoft.DataTransfer.ClientLibrary,''Type=System.Data.SqlClient.SqlException,Message=HdfsBridge::recordReaderFillBuffer - Unexpected error encountered filling record reader buffer: ClassCastException: ,Source=.Net SqlClient Data Provider,SqlErrorNumber=106000,Class=16,ErrorCode=-2146232060,State=1,Errors=[{ …
```

- **type** `SqlException` · **fp** `6561ab4f0621d39d`
- **template** `SQL DW Copy Command operation failed with error <NAME>`
- **values** NAME: HdfsBridge::recordReaderFillBuffer - Unexpected error encountered filling record reader buffer: ClassCastException: 
- **keywords** user, error, sql, dwcopy, command, error, copy

## fabric (16)

### — (3)

**1.** given code `—`

```text
Mashup Exception Error: Couldn't refresh the entity because of an issue with the mashup document MashupException.Error: Microsoft SQL: A network-related or instance-specific error occurred while establishing a connection to SQL Server. The server was not found or was not accessible. Verify that the instance name is correct and that SQL Server is configured to allow remote connections. (provider: TCP Provider, error: 0 - An attempt was made to access a socket in a way forbidden by its access permissions.) Details: DataSourceKind = Lakehouse;DataSourcePath = Lakehouse;Message = A network-related …
```

- **type** `—` · **fp** `4ed66cad4b0f1e43`
- **template** `Mashup Exception Error: Couldn't refresh the entity because of an issue with the mashup document MashupException.Error: Microsoft SQL: A network-related or instance-specific error occurred while establishing a connection to SQL Server. The server was not found or was not accessible. Verify that the `
- **values** NUM: 0, 0, -2146232060, 10013
- **keywords** mashup, couldn, refresh, entity, because, issue, document, mashupexception

**2.** given code `—`

```text
An error occurred while calling o6734.collectToPython. : org.apache.spark.SparkException: Job aborted due to stage failure: Task 0 in stage 18.0 failed 4 times, most recent failure: Lost task 0.3 in stage 18.0 (TID 23) (vm-4f039835 executor 1): com.microsoft.sqlserver.jdbc.SQLServerException: An error occurred during the current command (Done status 0). Failed to complete the command because the underlying location does not exist. Underlying data description: table '\<lakehouse table path\>', file '\<lakehouse table url\>'.
```

- **type** `—` · **fp** `41490bcef4f7cdff`
- **template** `An error occurred while calling <NAME>.collectToPython. : org.apache.spark.SparkException: Job aborted due to stage failure: Task <NUM> in stage <NUM> failed <NUM> times, most recent failure: Lost task <NUM> in stage <NUM> (TID <NUM>) (vm-<NAME> executor <NUM>): com.microsoft.sqlserver.jdbc.SQLServe`
- **values** NAME: \<lakehouse table path\>, \<lakehouse table url\>, o6734, 4f039835; NUM: 0, 18.0, 4, 0.3 …
- **keywords** occurred, while, calling, collecttopython, org, apache, spark, sparkexception

**3.** given code `—`

```text
OSError: Generic MicrosoftAzure error: Error performing token request: Error after 10 retries in 13.93100353s, max_retries:10, retry_timeout:180s, source:error sending request for url (http://xxx.xxx.xxx.xxx/metadata/identity/oauth2/token?api-version=2019-08-01&resource=https%3A%2F%2Fstorage.azure.com)
```

- **type** `—` · **fp** `7a7d7292782b726f`
- **template** `OSError: Generic MicrosoftAzure error: Error performing token request: Error after <NUM> retries in <NUM>.<NAME>:<NUM>, <NAME>:<NAME>, source:error sending request for url (<URL>)`
- **values** URL: http://xxx.xxx.xxx.xxx/metadata/identity/oauth2/token?api-version=2019-08-01&resource=https%3A%2F%2Fstorage.azure.com; NAME: 93100353s, max_retries, retry_timeout, 180s; NUM: 10, 13, 10
- **keywords** oserror, generic, microsoftazure, performing, token, request, after, retries

### ActionUserFailure (1)

**1.** given code `ActionUserFailure`

```text
There was a problem refreshing the dataflow: 'Something went wrong, please try again later. If the error persists, please contact support.'. Error code: ActionUserFailure. (Request ID: 2*****8-5***-4***-9***-3***1***f***).
```

- **type** `—` · **fp** `ef37f7dbcae2a606`
- **template** `There was a problem refreshing the dataflow: <NAME>. Error code: ActionUserFailure. (Request ID: <NUM>*****<NUM>-<NUM>***<NUM>***<NUM>***<NUM>***<NUM>***f***).`
- **values** NAME: Something went wrong, please try again later. If the error persists, please contact support.; NUM: 2, 8, 5, -4 …
- **keywords** action, user, failure, there, problem, refreshing, dataflow, code

### AdlsGen2OperationFailed (1)

**1.** given code `AdlsGen2OperationFailed`

```text
ErrorCode=AdlsGen2OperationFailed,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=ADLS Gen2 operation failed for: Operation returned an invalid status code 'BadRequest'. Account: ''. FileSystem: '3fb7192f-f276-49d1-a0c7-01047a2d313d'. Path: 'DemoAcquireEmployeeDataLakehouse/Tables/EmployeesWorldWide/_delta_log'. ErrorCode: 'BadRequest'. Message: 'Bad Request'. TimeStamp: 'Mon, 30 Oct 2023 10:21:56 GMT'..,Source=Microsoft.DataTransfer.ClientLibrary,''Type=Microsoft.Azure.Storage.Data.Models.ErrorSchemaException,Message=Operation returned an invalid status code 'BadReq …
```

- **type** `ErrorSchemaException` · **fp** `2c656af6fe7e66ea`
- **template** `ADLS <NAME> operation failed for: Operation returned an invalid status code <NAME>. Account: <NAME><ID><NAME><PATH><NAME>BadRequest<NAME>Bad Request<NAME>Mon, <NUM> Oct <NUM> <TS> GMT'..`
- **values** ID: 3fb7192f-f276-49d1-a0c7-01047a2d313d; TS: 10:21:56; NAME: BadRequest, . FileSystem: , . Path: , . ErrorCode:  …; PATH: DemoAcquireEmployeeDataLakehouse/Tables/EmployeesWorldWide/_delta_log; NUM: 30, 2023
- **keywords** adls, gen2, operation, failed, returned, invalid, status, code

### AnalysisException (1)

**1.** given code `AnalysisException`

```text
Operation on target Load Sales notebook failed: Notebook execution failed at Notebook service with http status code - '200', please check the Run logs on Notebook, additional details - 'Error name - AnalysisException, Error value - org.apache.hadoop.hive.ql.metadata.HiveException: MetaException(message:Spark SQL queries are only possible in the context of a lakehouse. Please attach a lakehouse to proceed.)'
```

- **type** `—` · **fp** `203988e5fb0f8970`
- **template** `Notebook execution failed at Notebook service with http status code - <NAME>, please check the Run logs on Notebook, additional details - 'Error name - AnalysisException, Error value - org.apache.hadoop.hive.ql.metadata.HiveException: MetaException(message:Spark SQL queries are only possible in the `
- **values** NAME: 200
- **keywords** analysis, exception, notebook, execution, service, http, status, code

### DataSource.Error (1)

**1.** given code `DataSource.Error`

```text
An exception occurred: DataSource.Error: Microsoft SQL: A network-related or instance-specific error occurred while establishing a connection to SQL Server. The server was not found or was not accessible. Verify that the instance name is correct and that SQL Server is configured to allow remote connections. (provider: Named Pipes Provider, error: 40 - Could not open a connection to SQL Server)
```

- **type** `—` · **fp** `3068ce29bf1609b1`
- **template** `An exception occurred: DataSource.Error: Microsoft SQL: A network-related or instance-specific error occurred while establishing a connection to SQL Server. The server was not found or was not accessible. Verify that the instance name is correct and that SQL Server is configured to allow remote conn`
- **values** NUM: 40
- **keywords** data, source, error, occurred, datasource, microsoft, sql, network

### DeltaTableNotCheckpointed (1)

**1.** given code `DeltaTableNotCheckpointed`

```text
ErrorCode: DeltaTableNotCheckpointed
Message: Delta table 'SomeTableName' has atleast '100' transaction logs, but no checkpoints. For performance reasons, it is recommended to regularly checkpoint the delta table more frequently than every '100' transactions. As a workaround, please use SQL or Spark to retrieve table schema.
```

- **type** `—` · **fp** `d413a87334934333`
- **template** `ErrorCode: DeltaTableNotCheckpointed Message: Delta table <NAME> has atleast <NAME> transaction logs, but no checkpoints. For performance reasons, it is recommended to regularly checkpoint the delta table more frequently than every <NAME> transactions. As a workaround, please use SQL or Spark to ret`
- **values** NAME: SomeTableName, 100, 100
- **keywords** delta, table, not, checkpointed, errorcode, deltatablenotcheckpointed, atleast, transaction

### DmsImportDatabaseException (1)

**1.** given code `DmsImportDatabaseException`

```text
File: dbo/DbRoles/db_rls_admin_bypass.sql, Error: Cannot find the user 'xyz@xyz.com', because it does not exist or you do not have permission., File: xyz/StoredProcedures/sp_create_init_dim_hierarchy.sql, Error: The specified schema name "xyz" either does not exist or you do not have permission to use it., File: dwh/StoredProcedures/sp_create_star_dim_contract.sql, Error: The specified schema name "dwh" either does not exist or you do not have permission to use it.,File: dbo/DbRoles/db_view_readers.sql, Error: Cannot find the user 'xyz@xyz.com', because it does not exist or you do not have per …
```

- **type** `—` · **fp** `b0e626b7ea7be231`
- **template** `File: <PATH>, Error: Cannot find the user <NAME>, because it does not exist or you do not have permission., File: <PATH>, Error: The specified schema name <NAME> either does not exist or you do not have permission to use it., File: <PATH>, Error: The specified schema name <NAME> either does not exis`
- **values** EMAIL: xyz@xyz.com, xyz@xyz.com; NAME: <EMAIL>, <EMAIL>, xyz, dwh; PATH: dbo/DbRoles/db_rls_admin_bypass.sql, xyz/StoredProcedures/sp_create_init_dim_hierarchy.sql, dwh/StoredProcedures/sp_create_star_dim_contract.sql, dbo/DbRoles/db_view_readers.sql
- **keywords** dms, import, database, exception, file, cannot, find, user

### Exception (1)

**1.** given code `—`

```text
Notebook execution failed at Notebook service with http status code - '200', please check the Run logs on Notebook, additional details - 'Error name - Exception, Error value - Error while creating the livy session, RunId: 964b2f2b-50c8-4033-90f6-a1c8e443091f'
```

- **type** `—` · **fp** `d9be4ff664c5b5cf`
- **template** `Notebook execution failed at Notebook service with http status code - <NAME>, please check the Run logs on Notebook, additional details - <NAME>`
- **values** ID: 964b2f2b-50c8-4033-90f6-a1c8e443091f; NAME: 200, Error name - Exception, Error value - Error while creating the livy session, RunId: <ID>
- **keywords** exception, notebook, execution, service, http, status, code, run

### HttpFileFailedToRead (1)

**1.** given code `HttpFileFailedToRead`

```text
ErrorCode=HttpFileFailedToRead,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=Failed to read data from http server. Check the error from http server：The request was aborted: The connection was closed unexpectedly.,Source=Microsoft.DataTransfer.ClientLibrary,''Type=System.Net.WebException,Message=The request was aborted: The connection was closed unexpectedly.,Source=System,'
```

- **type** `WebException` · **fp** `e2458537a01f8cab`
- **template** `Failed to read data from http server. Check the error from http server：The request was aborted: The connection was closed unexpectedly.`
- **values** —
- **keywords** http, file, failed, read, server, request, aborted, connection

### KustoMappingReferenceHasWrongKind (1)

**1.** given code `KustoMappingReferenceHasWrongKind`

```text
ErrorCode=KustoMappingReferenceHasWrongKind,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=Mapping reference should be of kind 'Csv'. Mapping reference: 'HistoryRaw_EMR_New_mapping'. Kind 'Json'.,Source=Microsoft.DataTransfer.Runtime.KustoConnector,'
```

- **type** `HybridDeliveryException` · **fp** `545f3f8596115854`
- **template** `Mapping reference should be of kind <NAME>. Mapping reference: <NAME>. Kind <NAME>.`
- **values** NAME: Csv, HistoryRaw_EMR_New_mapping, Json
- **keywords** kusto, mapping, reference, has, wrong, kind, should

### MagicUsageError (1)

**1.** given code `MagicUsageError`

```text
Notebook execution failed at Notebook service with http status code - '200', please check the Run logs on Notebook, additional details - 'Error name - MagicUsageError, Error value - %pip magic command is disabled.'
```

- **type** `—` · **fp** `745d6b913dccc12e`
- **template** `Notebook execution failed at Notebook service with http status code - <NAME>, please check the Run logs on Notebook, additional details - <NAME>`
- **values** NAME: 200, Error name - MagicUsageError, Error value - %pip magic command is disabled.
- **keywords** magic, usage, error, notebook, execution, service, http, status

### RestResourceReadFailed (1)

**1.** given code `RestResourceReadFailed`

```text
Failure happened on 'Source' side. ErrorCode=RestResourceReadFailed,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=Fail to read from REST resource.,Source=Microsoft.DataTransfer.ClientLibrary,''Type=System.IO.InvalidDataException,Message=Found invalid data while decoding.,Source=System,'
```

- **type** `InvalidDataException` · **fp** `285c7713f2ea22b3`
- **template** `Fail to read from REST resource.`
- **values** —
- **keywords** rest, resource, read, failed

### SparkCoreError/SessionDidNotEnterIdle (1)

**1.** given code `SparkCoreError/SessionDidNotEnterIdle`

```text
Notebook execution failed at Notebook service with http status code - '200', please check the Run logs on Notebook, additional details - 'Error name - Exception, Error value - Failed to create Livy session for executing notebook
error":{"ename":"Exception","evalue":"Failed to create Livy session for executing notebook. LivySessionId: d9cdeeb4-235c-4d57-8bb9-efab552001bf","traceback":["Exception: Failed to create Livy session for executing notebook. LivySessionId: d9cdeeb4-235c-4d57-8bb9-efab552001bf","--> SparkCoreError/SessionDidNotEnterIdle: Livy session has failed. Error code: SparkCoreErro …
```

- **type** `—` · **fp** `3f89ff0f262b9ff3`
- **template** `Notebook execution failed at Notebook service with http status code - <NAME>, please check the Run logs on Notebook, additional details - 'Error name - Exception, Error value - Failed to create Livy session for executing notebook error<NAME>ename<NAME>Exception<NAME>evalue<NAME>Failed to create Livy`
- **values** ID: d9cdeeb4-235c-4d57-8bb9-efab552001bf, d9cdeeb4-235c-4d57-8bb9-efab552001bf; NAME: 200, :{, :, , …; PATH: SparkCoreError/SessionDidNotEnterIdle, SparkCoreError/SessionDidNotEnterIdle.; NUM: 10
- **keywords** spark, core, error/session, did, not, enter, idle, notebook

### UserErrorWriteFailedFileOperation (1)

**1.** given code `UserErrorWriteFailedFileOperation`

```text
Failure happened on 'Source' side. ErrorCode=UserErrorWriteFailedFileOperation,'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException,Message=The file operation is failed, upload file failed at path: '/Tables/table_name'.,Source=mscorlib,''Type=Microsoft.Data.SqlClient.SqlException,Message=Error 0x5 occurred when opening a connection from distribution 1 to distribution 1. Additional details: '0xa(MWC service error: Server responded with error: 400)'. Please try to run the query again. If the error persists, please contact support.
```

- **type** `SqlException` · **fp** `ae12456d04eeb461`
- **template** `The file operation is failed, upload file failed at path: <NAME>.`
- **values** NAME: /Tables/table_name
- **keywords** user, error, write, failed, file, operation, upload, path

## databricks (61)

### — (9)

**1.** given code `—`

```text
org.apache.hadoop.mapreduce.lib.input.InvalidInputException: Input Pattern abfss://containername@storageaccountname.dfs.core.windows.net/foldername/File name [file1]_2023.csv matches 0 files
```

- **type** `InvalidInputException` · **fp** `5da65d2ae6456c1b`
- **template** `Input Pattern <URL> name <LIST><PATH> matches <NUM> files`
- **values** URL: abfss://containername@storageaccountname.dfs.core.windows.net/foldername/File; LIST: [file1]; PATH: _2023.csv; NUM: 0
- **keywords** input, pattern, name, matches, files

**2.** given code `—`

```text
ConcurrentAppendException: Files were added to partition [country=Panamá, process_date=2022-01-01 00:00:00] by a concurrent update. Please try the operation again.
```

- **type** `ConcurrentAppendException` · **fp** `8f3a3f15502fdd3e`
- **template** `Files were added to partition [country=Panamá, <NAME>=<TS>] by a concurrent update. Please try the operation again.`
- **values** TS: 2022-01-01 00:00:00; NAME: process_date
- **keywords** files, added, partition, country, panam, concurrent, update, try

**3.** given code `—`

```text
ConcurrentAppendException: Files were added to the root of the table by a concurrent update. Please try the operation again.
```

- **type** `ConcurrentAppendException` · **fp** `782e7aabe9dd0362`
- **template** `Files were added to the root of the table by a concurrent update. Please try the operation again.`
- **values** —
- **keywords** files, added, root, table, concurrent, update, try, again

**4.** given code `—`

```text
The spark driver has stopped unexpectedly and is restarting.
```

- **type** `—` · **fp** `c56b6949dda337f1` ×2
- **template** `The spark driver has stopped unexpectedly and is restarting.`
- **values** —
- **keywords** spark, driver, stopped, unexpectedly, restarting

**5.** given code `—`

```text
The spark driver has stopped unexpectedly and is restarting. Your notebook will be automatically reattached.
```

- **type** `—` · **fp** `c56b6949dda337f1` ×2
- **template** `The spark driver has stopped unexpectedly and is restarting. Your notebook will be automatically reattached.`
- **values** —
- **keywords** spark, driver, stopped, unexpectedly, restarting, your, notebook, will

**6.** given code `—`

```text
org.apache.spark.memory.SparkOutOfMemoryError: Unable to acquire 44 bytes of memory, got 0
```

- **type** `SparkOutOfMemoryError` · **fp** `c08868b27c20cbc2`
- **template** `Unable to acquire <NUM> bytes of memory, got <NUM>`
- **values** NUM: 44, 0
- **keywords** unable, acquire, bytes, memory, got

**7.** given code `—`

```text
Job terminated with exception: assertion failed: There are [X] sources in the checkpoint offsets, and now there are [X+Y] sources requested by the query. Cannot continue. SQLSTATE: XXKST
```

- **type** `—` · **fp** `653393b5741654a1`
- **template** `Job terminated with exception: assertion failed: There are <LIST> sources in the checkpoint offsets, and now there are <LIST> sources requested by the query. Cannot continue.`
- **values** LIST: [X], [X+Y]
- **keywords** job, terminated, assertion, there, sources, checkpoint, offsets, now

**8.** given code `—`

```text
java.lang.UnsupportedOperationException: Error in SQL statement:
IllegalStateException: File (s3a://xxx/table1) to be rewritten not found among candidate files:
s3a://xxx/table1/part-00001-39cae1bb-9406-49d2-99fb-8c865516fbaa-c000.snappy.parquet
```

- **type** `UnsupportedOperationException` · **fp** `3543d1c608f2151f`
- **template** `Error in SQL statement: IllegalStateException: File (<URL>) to be rewritten not found among candidate files: <URL>`
- **values** URL: s3a://xxx/table1, s3a://xxx/table1/part-00001-39cae1bb-9406-49d2-99fb-8c865516fbaa-c000.snappy.parquet
- **keywords** sql, statement, illegalstateexception, file, rewritten, found, among, candidate

**9.** given code `—`

```text
Library installation failed for library due to infra fault. Error messages: Failed due to cluster termination, cluster was in state: Terminating
Could not reach driver of cluster <cluster-id> for 120 seconds.
```

- **type** `—` · **fp** `bd1686f73928ede8`
- **template** `Library installation failed for library due to infra fault. Error messages: Failed due to cluster termination, cluster was in state: Terminating Could not reach driver of cluster <cluster-id> for <NUM> seconds.`
- **values** NUM: 120
- **keywords** library, installation, due, infra, fault, messages, cluster, termination

### UNRESOLVED_COLUMN.WITH_SUGGESTION (6)

**1.** given code `UNRESOLVED_COLUMN.WITH_SUGGESTION`

```text
org.apache.spark.sql.AnalysisException: [UNRESOLVED_COLUMN.WITH_SUGGESTION] A column or function parameter with name `team_names` cannot be resolved. Did you mean one of the following? [`data`, `meta`].;
```

- **type** `AnalysisException` · **fp** `9dca5fe55f926498` ×2
- **template** `A column or function parameter with name <NAME> cannot be resolved. Did you mean one of the following? [<NAME>].;`
- **values** NAME: team_names, data, meta
- **keywords** unresolved, column, with, suggestion, function, parameter, name, cannot

**2.** given code `UNRESOLVED_COLUMN.WITH_SUGGESTION`

```text
[UNRESOLVED_COLUMN.WITH_SUGGESTION] A column, variable, or function parameter with name graduate_program cannot be resolved. Did you mean one of the following? [degree, department, id, school]. SQLSTATE: 42703
```

- **type** `—` · **fp** `105fd027c18a017a`
- **template** `A column, variable, or function parameter with name <NAME> cannot be resolved. Did you mean one of the following? <LIST>.`
- **values** LIST: [degree, department, id, school]; NAME: graduate_program
- **keywords** unresolved, column, with, suggestion, variable, function, parameter, name

**3.** given code `UNRESOLVED_COLUMN.WITH_SUGGESTION`

```text
org.apache.spark.sql.AnalysisException: [UNRESOLVED_COLUMN.WITH_SUGGESTION] A column or function parameter with name `newValue` cannot be resolved. Did you mean one of the following? [`value`]
```

- **type** `AnalysisException` · **fp** `9dca5fe55f926498` ×2
- **template** `A column or function parameter with name <NAME> cannot be resolved. Did you mean one of the following? [<NAME>]`
- **values** NAME: newValue, value
- **keywords** unresolved, column, with, suggestion, function, parameter, name, cannot

**4.** given code `UNRESOLVED_COLUMN.WITH_SUGGESTION`

```text
AnalysisException: [UNRESOLVED_COLUMN.WITH_SUGGESTION] A column or function parameter with the name Column<'x_1'> cannot be resolved. Did you mean one of the following? [id, alert, operation, lookup].
```

- **type** `AnalysisException` · **fp** `54b81f0d08097045`
- **template** `A column or function parameter with the name Column<<NAME>> cannot be resolved. Did you mean one of the following? <LIST>.`
- **values** NAME: x_1; LIST: [id, alert, operation, lookup]
- **keywords** unresolved, column, with, suggestion, function, parameter, name, cannot

**5.** given code `UNRESOLVED_COLUMN.WITH_SUGGESTION`

```text
[UNRESOLVED_COLUMN.WITH_SUGGESTION] A column, variable, or function parameter with name [ cannot be resolved. Did you mean one of the following? [Name, pkey, Value, dq_check, Description]. SQLSTATE: 42703;
```

- **type** `—` · **fp** `1fdee21c1c025011`
- **template** `A column, variable, or function parameter with name [ cannot be resolved. Did you mean one of the following? <LIST>.;`
- **values** LIST: [Name, pkey, Value, dq_check, Description]
- **keywords** unresolved, column, with, suggestion, variable, function, parameter, name

**6.** given code `UNRESOLVED_COLUMN.WITH_SUGGESTION` · *template from Spark JSON*

```text
[UNRESOLVED_COLUMN.WITH_SUGGESTION] A column, variable, or function parameter with name <objectName> cannot be resolved.
Did you mean one of the following? [<proposal>]. SQLSTATE: 42703
```

- **type** `—` · **fp** `ea30709e4e53dcfe`
- **template** `A column, variable, or function parameter with name <objectName> cannot be resolved. Did you mean one of the following? [<proposal>].`
- **values** —
- **keywords** unresolved, column, with, suggestion, variable, function, parameter, name

### PARSE_SYNTAX_ERROR (5)

**1.** given code `PARSE_SYNTAX_ERROR`

```text
ParseException: 
[PARSE_SYNTAX_ERROR] Syntax error at or near '('.(line 3, pos 9)

== SQL ==
SELECT
  CASE
    WHEN (SELECT name FROM bop WHERE Id='1') IS NOT NULL
---------^^^
      AND (SELECT name FROM bop WHERE Id='7') IS NOT NULL
    THEN name
    ELSE null
    END as result
FROM bop
```

- **type** `ParseException` · **fp** `0dd19058d9d6c2a2` ×2
- **template** `Syntax error at or near <NAME>.(line <NUM>, pos <NUM>)`
- **values** NAME: (; NUM: 3, 9
- **keywords** parse, syntax, error, near, line, pos

**2.** given code `PARSE_SYNTAX_ERROR`

```text
ParseException: 
[PARSE_SYNTAX_ERROR] Syntax error at or near 'answer_option_name'.(line 3, pos 9)

== SQL ==
SELECT
  CASE
    WHEN name IS NOT NULL WHERE Id in ('1', '7')
---------^^^
    THEN name
    ELSE null
    END as result
FROM bop
```

- **type** `ParseException` · **fp** `0dd19058d9d6c2a2` ×2
- **template** `Syntax error at or near <NAME>.(line <NUM>, pos <NUM>)`
- **values** NAME: answer_option_name; NUM: 3, 9
- **keywords** parse, syntax, error, near, line, pos

**3.** given code `PARSE_SYNTAX_ERROR`

```text
ERROR [42601] [Simba][Hardy] (80) Syntax or semantic analysis error thrown in server while executing query. 
Error message from server: org.apache.hive.service.cli.HiveSQLException: Error running query: [PARSE_SYNTAX_ERROR] org.apache.spark.sql.catalyst.parser.ParseException: 
[PARSE_SYNTAX_ERROR] Syntax error at or near 'SELECT': extra input 'SELECT'. SQLSTATE: 42601 (line xx, pos 0)
```

- **type** `HiveSQLException` · **fp** `0d68fd985caeb7a2`
- **template** `org.apache.<PATH>.catalyst.parser.ParseException: <LIST> Syntax error at or near <NAME>: extra input <NAME>. (line xx, pos <NUM>)`
- **values** NAME: SELECT, SELECT; LIST: [PARSE_SYNTAX_ERROR]; PATH: spark.sql; NUM: 0
- **keywords** parse, syntax, error, org, apache, catalyst, parser, parseexception

**4.** given code `PARSE_SYNTAX_ERROR`

```text
ParseException: [PARSE_SYNTAX_ERROR] Syntax error at or near ''PROD_DATAMGMT_WH'': extra input ''PROD_DATAMGMT_WH''.(line 1, pos 14)
```

- **type** `ParseException` · **fp** `b24476aee454d8a4`
- **template** `Syntax error at or near <NAME><NAME><NAME>: extra input <NAME><NAME><NAME>.(line <NUM>, pos <NUM>)`
- **values** NAME: , , ,  …; NUM: 1, 14
- **keywords** parse, syntax, error, near, extra, input, line, pos

**5.** given code `PARSE_SYNTAX_ERROR`

```text
ParseException:[PARSE_SYNTAX_ERROR] Syntax error at or near 'from'(line 5, pos 0)
```

- **type** `ParseException` · **fp** `b0bc3c299627f3c6`
- **template** `Syntax error at or near <NAME>(line <NUM>, pos <NUM>)`
- **values** NAME: from; NUM: 5, 0
- **keywords** parse, syntax, error, near, line, pos

### TABLE_OR_VIEW_NOT_FOUND (4)

**1.** given code `TABLE_OR_VIEW_NOT_FOUND`

```text
AnalysisException: [TABLE_OR_VIEW_NOT_FOUND] The table or view `mytable` cannot be found. Verify the spelling and correctness of the schema and catalog
```

- **type** `AnalysisException` · **fp** `dc681a9b9bcb37ba`
- **template** `The table or view <NAME> cannot be found. Verify the spelling and correctness of the schema and catalog`
- **values** NAME: mytable
- **keywords** table, view, not, found, cannot, verify, spelling, correctness

**2.** given code `TABLE_OR_VIEW_NOT_FOUND`

```text
[TABLE_OR_VIEW_NOT_FOUND] The table or view hive_metastore.MY_SCHEMA.MY_TABLE cannot be found. Verify the spelling and correctness of the schema and catalog.
```

- **type** `—` · **fp** `a14b889dc54caf3e` ×2
- **template** `The table or view <NAME> cannot be found. Verify the spelling and correctness of the schema and catalog.`
- **values** NAME: hive_metastore, MY_SCHEMA, MY_TABLE
- **keywords** table, view, not, found, cannot, verify, spelling, correctness

**3.** given code `TABLE_OR_VIEW_NOT_FOUND`

```text
[TABLE_OR_VIEW_NOT_FOUND] The table or view `dlt_test_dlt_db`.`live_gold` cannot be found.
```

- **type** `—` · **fp** `a14b889dc54caf3e` ×2
- **template** `The table or view <NAME> cannot be found.`
- **values** NAME: dlt_test_dlt_db, live_gold
- **keywords** table, view, not, found, cannot

**4.** given code `TABLE_OR_VIEW_NOT_FOUND` · *template from Spark JSON*

```text
[TABLE_OR_VIEW_NOT_FOUND] The table or view <relationName> cannot be found. Verify the spelling and correctness of the schema and catalog.
Search path: <searchPath>.
If you did not qualify the name with a schema, verify the current_schema() output, or qualify the name with the correct schema and catalog.
To tolerate the error on drop use DROP VIEW IF EXISTS or DROP TABLE IF EXISTS. SQLSTATE: 42P01
```

- **type** `—` · **fp** `78d6da56cb9bb8ad`
- **template** `The table or view <relationName> cannot be found. Verify the spelling and correctness of the schema and catalog. Search path: <searchPath>. If you did not qualify the name with a schema, verify the <NAME>() output, or qualify the name with the correct schema and catalog. To tolerate the error on dro`
- **values** NAME: current_schema
- **keywords** table, view, not, found, cannot, verify, spelling, correctness

### CAST_INVALID_INPUT (3)

**1.** given code `CAST_INVALID_INPUT`

```text
Job aborted due to stage failure: Task 18 in stage 15526.0 failed 4 times, most recent failure: Lost task 18.3 in stage 15526.0 (TID 3281950) (10.179.0.125 executor 1190): org.apache.spark.SparkDateTimeException: [CAST_INVALID_INPUT] The value '04/12/2024 01:37:07.000 AM' of the type "STRING" cannot be cast to "TIMESTAMP" because it is malformed. Correct the value as per the syntax, or change its target type.
```

- **type** `SparkDateTimeException` · **fp** `3e013eb1a06949ad`
- **template** `The value <NAME> of the type <NAME> cannot be cast to <NAME> because it is malformed. Correct the value as per the syntax, or change its target type.`
- **values** TS: 04/12/2024 01:37:07; NAME: <TS>.000 AM, STRING, TIMESTAMP
- **keywords** cast, invalid, input, cannot, because, malformed, correct, per

**2.** given code `CAST_INVALID_INPUT`

```text
[CAST_INVALID_INPUT] The value 'UNKNOWN' of the type "STRING" cannot be cast to "BIGINT" because it is malformed.
```

- **type** `—` · **fp** `2f2360d3a4a69e15`
- **template** `The value <NAME> of the type <NAME> cannot be cast to <NAME> because it is malformed.`
- **values** NAME: UNKNOWN, STRING, BIGINT
- **keywords** cast, invalid, input, cannot, because, malformed

**3.** given code `CAST_INVALID_INPUT` · *template from Spark JSON*

```text
[CAST_INVALID_INPUT] The value <expression> of the type <sourceType> cannot be cast to <targetType> because it is malformed. Correct the value as per the syntax, or change its target type. Use `try_cast` to tolerate malformed input and return NULL instead. SQLSTATE: 22018
```

- **type** `—` · **fp** `70ba634881c6af99`
- **template** `The value <expression> of the type <sourceType> cannot be cast to <targetType> because it is malformed. Correct the value as per the syntax, or change its target type. Use <NAME> to tolerate malformed input and return NULL instead.`
- **values** NAME: try_cast
- **keywords** cast, invalid, input, cannot, because, malformed, correct, per

### INSUFFICIENT_PERMISSIONS (3)

**1.** given code `INSUFFICIENT_PERMISSIONS`

```text
[INSUFFICIENT_PERMISSIONS] Insufficient privileges:
User does not have permission SELECT on table `brxxxx8`.`0xxxxxxx`.
User does not have permission USAGE on database `brxxxx8`. SQLSTATE: 42501
```

- **type** `—` · **fp** `5a8235eadd1ed3e7`
- **template** `Insufficient privileges: User does not have permission SELECT on table <NAME>. User does not have permission USAGE on database <NAME>.`
- **values** NAME: brxxxx8, 0xxxxxxx, brxxxx8
- **keywords** insufficient, permissions, privileges, user, does, permission, select, table

**2.** given code `INSUFFICIENT_PERMISSIONS`

```text
org.apache.spark.SparkSecurityException: [INSUFFICIENT_PERMISSIONS] Insufficient privileges:
User does not have permission SELECT on any file. SQLSTATE: 42501
```

- **type** `SparkSecurityException` · **fp** `49319c242ae12581`
- **template** `Insufficient privileges: User does not have permission SELECT on any file.`
- **values** —
- **keywords** insufficient, permissions, privileges, user, does, permission, select, any

**3.** given code `INSUFFICIENT_PERMISSIONS`

```text
An error occurred while calling o790.withColumn.
: org.apache.spark.SparkSecurityException: [INSUFFICIENT_PERMISSIONS] Insufficient privileges:
User does not have permission SELECT on anonymous function. SQLSTATE: 42501
```

- **type** `SparkSecurityException` · **fp** `b49dba3f8e7406b4`
- **template** `Insufficient privileges: User does not have permission SELECT on anonymous function.`
- **values** —
- **keywords** insufficient, permissions, privileges, user, does, permission, select, anonymous

### UNRESOLVED_ROUTINE (3)

**1.** given code `UNRESOLVED_ROUTINE`

```text
[UNRESOLVED_ROUTINE] Cannot resolve function md5 on search path [system.builtin, system.session, spark_catalog.default]
```

- **type** `—` · **fp** `105f46cce532df3e`
- **template** `Cannot resolve function <NAME> on search path <LIST>`
- **values** LIST: [system.builtin, system.session, spark_catalog.default]; NAME: md5
- **keywords** unresolved, routine, cannot, resolve, function, search, path

**2.** given code `UNRESOLVED_ROUTINE`

```text
AnalysisException: [UNRESOLVED_ROUTINE] Cannot resolve function `distinct` on search path [`system`.`builtin`, `system`.`session`, `spark_catalog`.`default`].; line 1 pos 1
```

- **type** `AnalysisException` · **fp** `89d93012afcbf65e`
- **template** `Cannot resolve function <NAME> on search path [<NAME>].; line <NUM> pos <NUM>`
- **values** NAME: distinct, system, builtin, system …; NUM: 1, 1
- **keywords** unresolved, routine, cannot, resolve, function, search, path, line

**3.** given code `UNRESOLVED_ROUTINE`

```text
[UNRESOLVED_ROUTINE] Cannot resolve function `ST_Distance` on search path [`system`.`builtin`, `system`.`session`, `spark_catalog`.`default`].; line 3 pos 4
```

- **type** `—` · **fp** `461db1f3a84a5e01`
- **template** `Cannot resolve function <NAME> on search path [<NAME>].; line <NUM> pos <NUM>`
- **values** NAME: ST_Distance, system, builtin, system …; NUM: 3, 4
- **keywords** unresolved, routine, cannot, resolve, function, search, path, line

### FAILED_READ_FILE.PARQUET_COLUMN_DATA_TYPE_MISMATCH (2)

**1.** given code `FAILED_READ_FILE.PARQUET_COLUMN_DATA_TYPE_MISMATCH`

```text
[FAILED_READ_FILE.PARQUET_COLUMN_DATA_TYPE_MISMATCH] Error while reading file dbfs:/<path-to-parquet-file>.snappy.parquet. Data type mismatches when reading Parquet column . Expected Spark type <data-type>, actual Parquet type <data-type>. SQLSTATE: KD001
```

- **type** `—` · **fp** `8380e59e085b51cf`
- **template** `Error while reading file dbfs:/<path-to-parquet-file>.<PATH>. Data type mismatches when reading Parquet column . Expected Spark type <data-type>, actual Parquet type <data-type>.`
- **values** PATH: snappy.parquet
- **keywords** failed, read, file, parquet, column, data, type, mismatch

**2.** given code `FAILED_READ_FILE.PARQUET_COLUMN_DATA_TYPE_MISMATCH` · *template from Spark JSON*

```text
[FAILED_READ_FILE.PARQUET_COLUMN_DATA_TYPE_MISMATCH] Encountered error while reading file <path>.
Data type mismatches when reading Parquet column <column>. Expected Spark type <expectedType>, actual Parquet type <actualType>. SQLSTATE: KD001
```

- **type** `—` · **fp** `3530c7c0968ba3d6`
- **template** `Encountered error while reading file <path>. Data type mismatches when reading Parquet column <column>. Expected Spark type <expectedType>, actual Parquet type <actualType>.`
- **values** —
- **keywords** failed, read, file, parquet, column, data, type, mismatch

### PATH_NOT_FOUND (2)

**1.** given code `PATH_NOT_FOUND`

```text
pyspark.errors.exceptions.captured.AnalysisException: [PATH_NOT_FOUND] Path does not exist: file:/D:/Dir1/Dir1.1/File1.csv, D:/Dir2/Dir2.1/File2.csv.
```

- **type** `AnalysisException` · **fp** `8dc2455776a8421b`
- **template** `Path does not exist: file:/D:/<PATH>, D:/<PATH>`
- **values** PATH: Dir1/Dir1.1/File1.csv, Dir2/Dir2.1/File2.csv.
- **keywords** path, not, found, does, exist, file

**2.** given code `PATH_NOT_FOUND` · *template from Spark JSON*

```text
[PATH_NOT_FOUND] Path does not exist: <path>. SQLSTATE: 42K03
```

- **type** `—` · **fp** `ec56bbc27a198b03`
- **template** `Path does not exist: <path>.`
- **values** —
- **keywords** path, not, found, does, exist

### SCHEMA_NOT_FOUND (2)

**1.** given code `SCHEMA_NOT_FOUND`

```text
AnalysisException: [SCHEMA_NOT_FOUND] The schema general_schema cannot be found. Verify the spelling and correctness of the schema and catalog. If you did not qualify the name with a catalog, verify the current_schema() output, or qualify the name with the correct catalog.
```

- **type** `AnalysisException` · **fp** `63b4b2c1e507892b`
- **template** `The schema <NAME> cannot be found. Verify the spelling and correctness of the schema and catalog. If you did not qualify the name with a catalog, verify the <NAME>() output, or qualify the name with the correct catalog.`
- **values** NAME: general_schema, current_schema
- **keywords** schema, not, found, cannot, verify, spelling, correctness, catalog

**2.** given code `SCHEMA_NOT_FOUND` · *template from Spark JSON*

```text
[SCHEMA_NOT_FOUND] The schema <schemaName> cannot be found. Verify the spelling and correctness of the schema and catalog.
If you did not qualify the name with a catalog, verify the current_schema() output, or qualify the name with the correct catalog.
To tolerate the error on drop use DROP SCHEMA IF EXISTS. SQLSTATE: 42704
```

- **type** `—` · **fp** `b8c8b5f946106c46`
- **template** `The schema <schemaName> cannot be found. Verify the spelling and correctness of the schema and catalog. If you did not qualify the name with a catalog, verify the <NAME>() output, or qualify the name with the correct catalog. To tolerate the error on drop use DROP SCHEMA IF EXISTS.`
- **values** NAME: current_schema
- **keywords** schema, not, found, cannot, verify, spelling, correctness, catalog

### UC_COMMAND_NOT_SUPPORTED (2)

**1.** given code `UC_COMMAND_NOT_SUPPORTED`

```text
[UC_COMMAND_NOT_SUPPORTED] Creating a persistent view that references both Unity Catalog and Hive Metastore objects is not supported in Unity Catalog.
```

- **type** `—` · **fp** `b36bc56a700346e5`
- **template** `Creating a persistent view that references both Unity Catalog and Hive Metastore objects is not supported in Unity Catalog.`
- **values** —
- **keywords** command, not, supported, creating, persistent, view, references, both

**2.** given code `UC_COMMAND_NOT_SUPPORTED`

```text
AnalysisException: [UC_COMMAND_NOT_SUPPORTED] AttachDistributedSequence is not supported in Unity Catalog.;
```

- **type** `AnalysisException` · **fp** `152a9220a477accb`
- **template** `AttachDistributedSequence is not supported in Unity Catalog.;`
- **values** —
- **keywords** command, not, supported, attachdistributedsequence, unity, catalog

### ARITHMETIC_OVERFLOW (1)

**1.** given code `ARITHMETIC_OVERFLOW`

```text
Job aborted due to stage failure: Task 0 in stage 29.0 failed 4 times, most recent failure: Lost task 0.3 in stage 29.0 (TID 2517) (10.128.2.66 executor 3): org.apache.spark.SparkArithmeticException: [ARITHMETIC_OVERFLOW] long overflow. If necessary set ansi_mode to "false" to bypass this error.
```

- **type** `SparkArithmeticException` · **fp** `4a3e59c7730ffff1`
- **template** `long overflow. If necessary set <NAME> to <NAME> to bypass this error.`
- **values** NAME: false, ansi_mode
- **keywords** arithmetic, overflow, long, necessary, set, bypass

### CANNOT_MERGE_INCOMPATIBLE_DATA_TYPE (1)

**1.** given code `CANNOT_MERGE_INCOMPATIBLE_DATA_TYPE` · *template from Spark JSON*

```text
[CANNOT_MERGE_INCOMPATIBLE_DATA_TYPE] Failed to merge incompatible data types <left> and <right>. Please check the data types of the columns being merged and ensure that they are compatible. If necessary, consider casting the columns to compatible data types before attempting the merge. SQLSTATE: 42825
```

- **type** `—` · **fp** `f7292d891f0bf9f2`
- **template** `Failed to merge incompatible data types <left> and <right>. Please check the data types of the columns being merged and ensure that they are compatible. If necessary, consider casting the columns to compatible data types before attempting the merge.`
- **values** —
- **keywords** cannot, merge, incompatible, data, type, types, columns, being

### CHECKPOINT_RDD_BLOCK_ID_NOT_FOUND (1)

**1.** given code `CHECKPOINT_RDD_BLOCK_ID_NOT_FOUND`

```text
[CHECKPOINT_RDD_BLOCK_ID_NOT_FOUND] Checkpoint block rdd_XXXX not found!
Either the executor that originally checkpointed this partition is no longer alive, or the original RDD is unpersisted.
If this problem persists, you may consider using `rdd.checkpoint()` instead, which is slower than local checkpointing but more fault-tolerant. SQLSTATE: 56000
```

- **type** `—` · **fp** `876a035be18f77c6`
- **template** `Checkpoint block <NAME> not found! Either the executor that originally checkpointed this partition is no longer alive, or the original RDD is unpersisted. If this problem persists, you may consider using <NAME> instead, which is slower than local checkpointing but more fault-tolerant.`
- **values** NAME: rdd.checkpoint(), rdd_XXXX
- **keywords** checkpoint, rdd, block, not, found, either, executor, originally

### DATATYPE_MISMATCH.DATA_DIFF_TYPES (1)

**1.** given code `DATATYPE_MISMATCH.DATA_DIFF_TYPES`

```text
AnalysisException:[DATATYPE_MISMATCH.DATA_DIFF_TYPES] Cannot resolve "coalesce(reference, )" due to data type mismatch: Input to coalesce should all be the same type, but it's ("ARRAY<STRUCT<key: STRING, timestamp: TIMESTAMP>>" or "STRING").;
```

- **type** `AnalysisException` · **fp** `be803a11deb8f19d`
- **template** `Cannot resolve <NAME> due to data type mismatch: Input to coalesce should all be the same type, but it's (<NAME> or <NAME>).;`
- **values** NAME: coalesce(reference, ), ARRAY<STRUCT<key: STRING, timestamp: TIMESTAMP>>, STRING
- **keywords** datatype, mismatch, data, diff, types, cannot, resolve, due

### DELTA_CONCURRENT_APPEND (1)

**1.** given code `DELTA_CONCURRENT_APPEND`

```text
[DELTA_CONCURRENT_APPEND] ConcurrentAppendException: Files were added to the root of the table by a concurrent update. Please try the operation again. Conflicting commit: {"timestamp":1722250928325,"userId":"5954939804701401","userName":"aaaaaaa@xyz.com","operation":"MERGE","operationParameters":{"predicate":["((ITEM#22092922 = seg1_repcol#22092878) AND (LOC#22092925 = seg2_repcol#22092879))"],"matchedPredicates":[{"actionType":"update"}],"statsOnLoad":false,"notMatchedBySourcePredicates":[],"notMatchedPredicates":[]},"readVersion":2917,"isolationLevel":"WriteSerializable","isBlindAppend":fals …
```

- **type** `ConcurrentAppendException` · **fp** `877d96382b353fc0`
- **template** `ConcurrentAppendException: Files were added to the root of the table by a concurrent update. Please try the operation again. Conflicting commit: {<NAME>:<NUM>,<NAME>:<NAME>:<NAME>:<NAME>:{<NAME>:[<NAME>],<NAME>:[{<NAME>:<NAME>}],<NAME>:false,<NAME>:[],<NAME>:[]},<NAME>:<NUM>,<NAME>:<NAME>:false,<NAM`
- **values** EMAIL: aaaaaaa@xyz.com; ID: eb912069-75fd-4f33-9829-a9cb191b4b7e; HEX: 5954939804701401; NAME: timestamp, userId, <HEX>, userName …; NUM: 1722250928325, 2917
- **keywords** delta, concurrent, append, concurrentappendexception, files, added, root, table

### DELTA_FAILED_TO_MERGE_FIELDS (1)

**1.** given code `DELTA_FAILED_TO_MERGE_FIELDS`

```text
AnalysisException: [DELTA_FAILED_TO_MERGE_FIELDS] Failed to merge fields 'latitude' and 'latitude'
```

- **type** `AnalysisException` · **fp** `8187b280e88f8f28`
- **template** `Failed to merge fields <NAME> and <NAME>`
- **values** NAME: latitude, latitude
- **keywords** delta, failed, merge, fields

### DELTA_INSERT_COLUMN_ARITY_MISMATCH (1)

**1.** given code `DELTA_INSERT_COLUMN_ARITY_MISMATCH`

```text
[DELTA_INSERT_COLUMN_ARITY_MISMATCH] target table has 23 column(s) but the inserted data has 2 column(s).
```

- **type** `—` · **fp** `814c84290a805396`
- **template** `target table has <NUM> column(s) but the inserted data has <NUM> column(s).`
- **values** NUM: 23, 2
- **keywords** delta, insert, column, arity, mismatch, target, table, but

### DELTA_MERGE_INCOMPATIBLE_DECIMAL_TYPE (1)

**1.** given code `DELTA_MERGE_INCOMPATIBLE_DECIMAL_TYPE`

```text
Caused by: com.databricks.sql.transaction.tahoe.DeltaAnalysisException: [DELTA_MERGE_INCOMPATIBLE_DECIMAL_TYPE] Failed to merge decimal types with incompatible scale 6 and 5 (or any other scale) when attempting to merge fields with decimal types in Databricks.
```

- **type** `DeltaAnalysisException` · **fp** `ec12dc7ec1867a14`
- **template** `Failed to merge decimal types with incompatible scale <NUM> and <NUM> (or any other scale) when attempting to merge fields with decimal types in Databricks.`
- **values** NUM: 6, 5
- **keywords** delta, merge, incompatible, decimal, type, types, scale, any

### DELTA_METADATA_CHANGED (1)

**1.** given code `DELTA_METADATA_CHANGED`

```text
io.delta.exceptions.MetadataChangedException: [DELTA_METADATA_CHANGED] MetadataChangedException: The metadata of the Delta table has been changed by a concurrent update. Please try the operation again.
```

- **type** `MetadataChangedException` · **fp** `29701edaa78c2db9`
- **template** `MetadataChangedException: The metadata of the Delta table has been changed by a concurrent update. Please try the operation again.`
- **values** —
- **keywords** delta, metadata, changed, metadatachangedexception, table, concurrent, update, try

### DELTA_UNSUPPORTED_FEATURES_FOR_READ (1)

**1.** given code `DELTA_UNSUPPORTED_FEATURES_FOR_READ`

```text
[DELTA_UNSUPPORTED_FEATURES_FOR_READ] Unsupported Delta read feature: table "<catalog>.<schema>.<table>" requires reader table feature(s) that are unsupported by this version of Databricks: variantType-preview. Please refer to https://docs.databricks.com/delta/feature-compatibility.html for more information on Delta lake feature compatibility. SQLSTATE: 56038
```

- **type** `—` · **fp** `81c5296b6a237632`
- **template** `Unsupported Delta read feature: table <NAME> requires reader table feature(s) that are unsupported by this version of Databricks: variantType-preview. Please refer to <URL> for more information on Delta lake feature compatibility.`
- **values** URL: https://docs.databricks.com/delta/feature-compatibility.html; NAME: <catalog>.<schema>.<table>
- **keywords** delta, unsupported, features, for, read, feature, table, requires

### DIVIDE_BY_ZERO (1)

**1.** given code `DIVIDE_BY_ZERO` · *template from Spark JSON*

```text
[DIVIDE_BY_ZERO] Division by zero. Use `try_divide` to tolerate divisor being 0 and return NULL instead. If necessary set <config> to "false" to bypass this error. SQLSTATE: 22012
```

- **type** `—` · **fp** `dde255ac2c8255ae`
- **template** `Division by zero. Use <NAME> to tolerate divisor being <NUM> and return NULL instead. If necessary set <config> to <NAME> to bypass this error.`
- **values** NAME: false, try_divide; NUM: 0
- **keywords** divide, zero, division, use, tolerate, divisor, being, return

### DRIVER_EVICTION (1)

**1.** given code `DRIVER_EVICTION`

```text
Cluster <cluster-id> was terminated. Reason: DRIVER_EVICTION (CLIENT_ERROR). Parameters: databricks_error_message:driver-xxxxxxxxxx-xxxxx for cluster <cluster-id> was killed by underlying node
```

- **type** `—` · **fp** `ada94aae177361d8`
- **template** `Cluster <cluster-id> was terminated. Reason: <NAME> (<NAME>). Parameters: <NAME>:driver-xxxxxxxxxx-xxxxx for cluster <cluster-id> was killed by underlying node`
- **values** NAME: DRIVER_EVICTION, CLIENT_ERROR, databricks_error_message
- **keywords** driver, eviction, cluster, terminated, reason, parameters, xxxxxxxxxx, xxxxx

### GCP_QUOTA_EXCEEDED (1)

**1.** given code `GCP_QUOTA_EXCEEDED`

```text
Cluster terminated. Reason: Gcp Quota Exceeded
```

- **type** `—` · **fp** `616bec7a98a93aaa`
- **template** `Cluster terminated. Reason: Gcp Quota Exceeded`
- **values** —
- **keywords** gcp, quota, exceeded, cluster, terminated, reason

### INIT_SCRIPT_FAILURE (1)

**1.** given code `INIT_SCRIPT_FAILURE`

```text
Cluster terminated. Reason: Init Script Failure
```

- **type** `—` · **fp** `627df3f88feca112`
- **template** `Cluster terminated. Reason: Init Script Failure`
- **values** —
- **keywords** init, script, failure, cluster, terminated, reason

### INSERT_COLUMN_ARITY_MISMATCH.NOT_ENOUGH_DATA_COLUMNS (1)

**1.** given code `INSERT_COLUMN_ARITY_MISMATCH.NOT_ENOUGH_DATA_COLUMNS` · *template from Spark JSON*

```text
[INSERT_COLUMN_ARITY_MISMATCH.NOT_ENOUGH_DATA_COLUMNS] Cannot write to <tableName>, the reason is
not enough data columns:
Table columns: <tableColumns>.
Data columns: <dataColumns>. SQLSTATE: 21S01
```

- **type** `—` · **fp** `e62fbb422f0a9dc2`
- **template** `Cannot write to <tableName>, the reason is not enough data columns: Table columns: <tableColumns>. Data columns: <dataColumns>.`
- **values** —
- **keywords** insert, column, arity, mismatch, not, enough, data, columns

### MALFORMED_RECORD_IN_PARSING.WITHOUT_SUGGESTION (1)

**1.** given code `MALFORMED_RECORD_IN_PARSING.WITHOUT_SUGGESTION` · *template from Spark JSON*

```text
[MALFORMED_RECORD_IN_PARSING.WITHOUT_SUGGESTION] Malformed records are detected in record parsing: <badRecord>.
Parse Mode: <failFastMode>. To process malformed records as null result, try setting the option 'mode' as 'PERMISSIVE'. SQLSTATE: 22023
```

- **type** `—` · **fp** `1575c03e2f6d1226`
- **template** `Malformed records are detected in record parsing: <badRecord>. Parse Mode: <failFastMode>. To process malformed records as null result, try setting the option <NAME> as <NAME>.`
- **values** NAME: mode, PERMISSIVE
- **keywords** malformed, record, parsing, without, suggestion, records, detected, parse

### RunExecutionError (1)

**1.** given code `RunExecutionError`

```text
[RunExecutionError] Cluster 0824-184221-zlg0oon6 was terminated during the run (cluster state message: Cluster terminated by WORKSPACE_UPDATE)
```

- **type** `—` · **fp** `79ddbc0c4ee0628c`
- **template** `<LIST> Cluster <NUM>-<NUM>-<NAME> was terminated during the run (cluster state message: Cluster terminated by <NAME>)`
- **values** LIST: [RunExecutionError]; NAME: zlg0oon6, WORKSPACE_UPDATE; NUM: 0824, 184221
- **keywords** run, execution, error, cluster, terminated, during, state

### STREAM_FAILED (1)

**1.** given code `STREAM_FAILED`

```text
org.apache.spark.sql.streaming.StreamingQueryException: [STREAM_FAILED] Query [id = <id>, runId = <run-id>] terminated with exception: [DELTA_MERGE_MATERIALIZE_SOURCE_FAILED_REPEATEDLY] Keeping the source of the MERGE statement materialized has failed repeatedly. SQLSTATE: XXKST
```

- **type** `StreamingQueryException` · **fp** `17bff13416de39a5`
- **template** `Query [id = <id>, runId = <run-id>] terminated with exception: <LIST> Keeping the source of the MERGE statement materialized has failed repeatedly.`
- **values** LIST: [DELTA_MERGE_MATERIALIZE_SOURCE_FAILED_REPEATEDLY]
- **keywords** stream, failed, query, runid, run, terminated, keeping, merge

### UC_DEPENDENCY_DOES_NOT_EXIST (1)

**1.** given code `UC_DEPENDENCY_DOES_NOT_EXIST`

```text
[UC_DEPENDENCY_DOES_NOT_EXIST] Dependency does not exist in Unity Catalog: Table <catalog.schema.table> is invalid because one of the underlying resources does not exist.SQLSTATE: 42P01
```

- **type** `—` · **fp** `bc34aa0747975d47`
- **template** `Dependency does not exist in Unity Catalog: Table <catalog.schema.table> is invalid because one of the underlying resources does not exist.`
- **values** —
- **keywords** dependency, does, not, exist, unity, catalog, table, schema

### UNABLE_TO_ACQUIRE_MEMORY (1)

**1.** given code `UNABLE_TO_ACQUIRE_MEMORY`

```text
org.apache.spark.memory.SparkOutOfMemoryError:[UNABLE_TO_ACQUIRE_MEMORY] Unable to acquire 104857600 bytes of memory, got 38125049.SQLSTATE: 53200
```

- **type** `SparkOutOfMemoryError` · **fp** `b5230ccd901c7ed9`
- **template** `Unable to acquire <NUM> bytes of memory, got <NUM>.`
- **values** NUM: 104857600, 38125049
- **keywords** unable, acquire, memory, bytes, got

## dbt (53)

### — (43)

**1.** given code `—`

```text
Database Error in model un_company_sat (models/2_un/partner/sats/un_company_sat.sql)
Couldn't initialize file system for path abfss://dp-ext-fab@stcssdpextfabprd.dfs.core.windows.net/__unitystorage/catalogs/12345678-9abc-4c5f-b4a7-ef123456789a/tables/1bd27775-ca51-435a-8c1a-1042391ac471/part-00000-8121312f-d7a0-4a5b-964a-4c2f4ea4f2ec-c000.snappy.parquet
```

- **type** `dbt_database_error` · **fp** `e1fcea7d1e5e8449`
- **template** `Couldn't initialize file system for path <URL>`
- **values** URL: abfss://dp-ext-fab@stcssdpextfabprd.dfs.core.windows.net/__unitystorage/catalogs/12345678-9abc-4c5f-b4a7-ef123456789a/tables/1bd27775-ca51-435a-8c1a-1042391ac471/part-00000-8121312f-d7a0-4a5b-964a-4c2f4ea4f2ec-c000.snappy.parquet
- **keywords** couldn, initialize, file, system, path

**2.** given code `—`

```text
Compilation Error in test record_count_prontoform_prod_lptr_grower_prontoform_prod_lptr_grower__LPTR_GROWER_RAW_SUBMISSIONS__RAW_SUBMISSIONS (models\marts\schema_prontoform_prod_lptr_plant.yml) macro 'dbt_macro__test_record_count' takes no keyword argument 'model'
```

- **type** `dbt_compilation_error` · **fp** `004559a87826fe0e`
- **template** `macro <NAME> takes no keyword argument <NAME>`
- **values** NAME: dbt_macro__test_record_count, model
- **keywords** macro, takes, keyword, argument

**3.** given code `—`

```text
Failure in test
dbt_expectations_expect_column_values_to_be_of_type_stg_holidays_updated_at__timestamptz
(models/stage/stg_schema.yml)
Got 1 result, configured to fail if != 0
```

- **type** `—` · **fp** `db8dfc3fa732ccd9`
- **template** `Failure in test <NAME> (<PATH>) Got <NUM> result, configured to fail if != <NUM>`
- **values** PATH: models/stage/stg_schema.yml; NAME: dbt_expectations_expect_column_values_to_be_of_type_stg_holidays_updated_at__timestamptz; NUM: 1, 0
- **keywords** test, got, result, configured

**4.** given code `—`

```text
17:59:30  Failure in test dbt_expectations_expect_column_values_to_be_of_type_company_CREATED_AT__TIMESTAMP_TZ (models/fizzbuzz/domain/company.yml)
17:59:30    Got 1 result, configured to fail if != 0
17:59:30  
17:59:30    compiled Code at target/compiled/myapp/models/fizzbuzz/domain/company.yml/dbt_expectations_expect_column_837854ce21e79ee1abe42f69891c68e9.sql
```

- **type** `dbt_test_failure` · **fp** `642dd777e18656e9`
- **template** `Failure in test <NAME> (<PATH>) Got <NUM> result, configured to fail if != <NUM>`
- **values** PATH: models/fizzbuzz/domain/company.yml; NAME: dbt_expectations_expect_column_values_to_be_of_type_company_CREATED_AT__TIMESTAMP_TZ; NUM: 1, 0
- **keywords** test, got, result, configured

**5.** given code `—`

```text
ERROR: Runtime Error Could not find profile named 'learn_dbt' Encountered an error: Runtime Error Could not run dbt
```

- **type** `—` · **fp** `5d99a29cf55853c8`
- **template** `ERROR: Runtime Error Could not find profile named <NAME> Encountered an error: Runtime Error Could not run dbt`
- **values** NAME: learn_dbt
- **keywords** runtime, could, find, profile, named, encountered, run, dbt

**6.** given code `—`

```text
07:13:06  Error importing adapter: No module named 'dbt.adapters.sqlserver'
07:13:06  Encountered an error while reading profiles:
  ERROR: Runtime Error
  Credentials in profile "mssql", target "dev" invalid: Runtime Error
    Could not find adapter type sqlserver!Defined profiles:
 - mssql
For more information on configuring profiles, please consult the dbt docs:

https://docs.getdbt.com/docs/configure-your-profile

07:13:06  Encountered an error:
Runtime Error
  Could not run dbt
```

- **type** `—` · **fp** `26658551e6c3108f`
- **template** `Error importing adapter: No module named <NAME> Encountered an error while reading profiles: ERROR: Runtime Error Credentials in profile <NAME>, target <NAME> invalid: Runtime Error Could not find adapter type sqlserver!Defined profiles: - mssql For more information on configuring profiles, please c`
- **values** URL: https://docs.getdbt.com/docs/configure-your-profile; NAME: dbt.adapters.sqlserver, mssql, dev
- **keywords** importing, adapter, module, named, encountered, while, reading, profiles

**7.** given code `—`

```text
Profile loading failed for the following reason:
Runtime Error
  Credentials in profile "databricks_sql", target "default" invalid: Runtime Error
    Could not find adapter type databricks!
```

- **type** `—` · **fp** `0864469d3887c1d7` ×2
- **template** `Profile loading failed for the following reason: Runtime Error Credentials in profile <NAME>, target <NAME> invalid: Runtime Error Could not find adapter type databricks!`
- **values** NAME: databricks_sql, default
- **keywords** profile, loading, following, reason, runtime, credentials, target, invalid

**8.** given code `—`

```text
Parsing Error
Env var required but not provided: 'profilePassword'
```

- **type** `—` · **fp** `27286f1c8ba74abe`
- **template** `Parsing Error Env var required but not provided: <NAME>`
- **values** NAME: profilePassword
- **keywords** parsing, env, var, required, but, provided

**9.** given code `—`

```text
11:17:07  Encountered an error:
Parsing Error
  Env var required but not provided: 'non-existing-env-var'
```

- **type** `—` · **fp** `ba04313378b295f4`
- **template** `Encountered an error: Parsing Error Env var required but not provided: <NAME>`
- **values** NAME: non-existing-env-var
- **keywords** encountered, parsing, env, var, required, but, provided

**10.** given code `—`

```text
11:31:07    Compilation Error in test foo_thing_my_model_ (models/<path-to>/my_model.yml)
  'test_foo_thing' is undefined. This can happen when calling a macro that does not exist. Check for typos and/or install package dependencies with "dbt deps".
```

- **type** `dbt_compilation_error` · **fp** `6ebb7b24d5f49b38`
- **template** `<NAME> is undefined. This can happen when calling a macro that does not exist. Check for typos <PATH> install package dependencies with <NAME>.`
- **values** NAME: test_foo_thing, dbt deps; PATH: and/or
- **keywords** undefined, can, happen, when, calling, macro, does, exist

**11.** given code `—`

```text
Encountered an error:
the JSON object must be str, bytes or bytearray, not Undefined
```

- **type** `—` · **fp** `6f7f3505d540c6cb`
- **template** `Encountered an error: the JSON object must be str, bytes or bytearray, not Undefined`
- **values** —
- **keywords** encountered, json, object, must, str, bytes, bytearray, undefined

**12.** given code `—`

```text
Encountered an error while running operation: Compilation Error in macro stage_external_sources (macros/stage_external_sources.sql)
'dict object' has no attribute 'sources'
```

- **type** `dbt_compilation_error` · **fp** `6181d58bef42f793` ×4
- **template** `<NAME> has no attribute <NAME>`
- **values** NAME: dict object, sources
- **keywords** attribute

**13.** given code `—`

```text
Encountered an error while running operation: Compilation Error in macro statement (macros/etc/statement.sql)
  no loader for this environment specified
```

- **type** `dbt_compilation_error` · **fp** `3f917a92be45b84f`
- **template** `no loader for this environment specified`
- **values** —
- **keywords** loader, environment, specified

**14.** given code `—`

```text
21:03:04  Encountered an error while running operation: Database Error
  cross-database reference to database "example_db" is not supported
```

- **type** `—` · **fp** `7f9be45825c697d9`
- **template** `Encountered an error while running operation: Database Error cross-database reference to database <NAME> is not supported`
- **values** NAME: example_db
- **keywords** encountered, while, running, database, cross, reference, supported

**15.** given code `—`

```text
14:20:59  Encountered an error:
Compilation Error in operation dbt_constraints-on-run-end-0 (./dbt_project.yml)
  'dbt.tableA.graph.compiled.CompiledSingularTestNode object' has no attribute 'test_metadata’
```

- **type** `—` · **fp** `1c86f2ff2bcc77e7`
- **template** `Encountered an error: Compilation Error in operation <NAME>-on-run-end-<NUM> (<PATH>) <NAME> has no attribute '<NAME>’`
- **values** NAME: dbt.tableA.graph.compiled.CompiledSingularTestNode object, dbt_constraints, test_metadata; PATH: ./dbt_project.yml; NUM: 0
- **keywords** encountered, compilation, run, end, attribute

**16.** given code `—`

```text
Parsing Error
at path : Snapshots must be configured with a ‘strategy’, ‘unique_key’, and ‘target_schema’.
```

- **type** `—` · **fp** `6a24a415e42cd851`
- **template** `Parsing Error at path : Snapshots must be configured with a ‘strategy’, ‘<NAME>’, and ‘<NAME>’.`
- **values** NAME: unique_key, target_schema
- **keywords** parsing, path, snapshots, must, configured, strategy

**17.** given code `—`

```text
Error while parsing node: inline_query
Sql_Operation 'sql_operation.<project_name>.inline_query' (from remote system.sql) depends on a node named 'inline_query' which was not found
```

- **type** `—` · **fp** `9a8312858bf0f2b4`
- **template** `Error while parsing node: <NAME> <NAME> <NAME> (from remote <PATH>) depends on a node named <NAME> which was not found`
- **values** NAME: sql_operation.<project_name>.inline_query, inline_query, inline_query, Sql_Operation; PATH: system.sql
- **keywords** while, parsing, node, remote, depends, named, found

**18.** given code `—`

```text
Parsing Error in model test_post_to_api (models/geronimo/test_post_to_api.py)
  dbt allows exactly one model defined per python file, found 0
```

- **type** `dbt_parsing_error` · **fp** `c79629e733c98f34`
- **template** `dbt allows exactly one model defined per python file, found <NUM>`
- **values** NUM: 0
- **keywords** dbt, allows, exactly, one, model, defined, per, python

**19.** given code `—`

```text
dbt encountered an error while trying to read your profiles.yml file.

Could not automatically determine credentials. Please set GOOGLE_APPLICATION_CREDENTIALS or explicitly create credentials and re-run the application. For more information, please see https://cloud.google.com/docs/authentication/getting-started
```

- **type** `—` · **fp** `232565bc11fa80a5`
- **template** `dbt encountered an error while trying to read your <PATH> file. Could not automatically determine credentials. Please set <NAME> or explicitly create credentials and re-run the application. For more information, please see <URL>`
- **values** URL: https://cloud.google.com/docs/authentication/getting-started; PATH: profiles.yml; NAME: GOOGLE_APPLICATION_CREDENTIALS
- **keywords** dbt, encountered, while, trying, read, your, file, could

**20.** given code `—`

```text
Runtime Error in model yo (models/yo.sql)
404 Not found: Dataset hello-data-pipeline:staging_benjamin was not found in location EU
```

- **type** `dbt_runtime_error` · **fp** `aecf5651810d261a`
- **template** `<NUM> Not found: Dataset hello-data-pipeline:<NAME> was not found in location EU`
- **values** NAME: staging_benjamin; NUM: 404
- **keywords** found, dataset, hello, pipeline, location

**21.** given code `—`

```text
[2024-12-05, 14:39:08 UTC] {pod_manager.py:356} INFO - e[0m14:39:08  Encountered an error:
[2024-12-05, 14:39:08 UTC] {pod_manager.py:356} INFO - Database Error
[2024-12-05, 14:39:08 UTC] {pod_manager.py:356} INFO -   [Errno 2] No such file or directory: '/etc/secrets/[GCP_PROJECT]/credentials.json'
```

- **type** `—` · **fp** `587620019947d010`
- **template** `[<TS> UTC] {<PATH>:<NUM>} INFO - e[<NAME>:<NUM>:<NUM> Encountered an error: [<TS> UTC] {<PATH>:<NUM>} INFO - Database Error [<TS> UTC] {<PATH>:<NUM>} INFO - <LIST> No such file or directory: <NAME>`
- **values** TS: 2024-12-05, 2024-12-05, 2024-12-05, 14:39:08 …; NAME: /etc/secrets/[GCP_PROJECT]/credentials.json, 0m14; LIST: [Errno 2]; PATH: pod_manager.py, pod_manager.py, pod_manager.py; NUM: 356, 39, 08, 356 …
- **keywords** utc, info, encountered, database, such, file, directory

**22.** given code `—`

```text
ERROR: Database Error
  timeout expired
```

- **type** `—` · **fp** `1bf7364bc63b78a9`
- **template** `ERROR: Database Error timeout expired`
- **values** —
- **keywords** database, timeout, expired

**23.** given code `—`

```text
Database Error in model customers (models/customers.sql)
  Access Denied: Table dbt-tutorial:jaffle_shop.orders: User does not have permission to query table dbt-tutorial:jaffle_shop.orders.
  compiled SQL at target/run/jaffle_shop/models/customers.sql
```

- **type** `dbt_database_error` · **fp** `ffcd50c3fb933156`
- **template** `Access Denied: Table dbt-tutorial:<NAME>.orders: User does not have permission to query table dbt-tutorial:<NAME>.orders.`
- **values** NAME: jaffle_shop, jaffle_shop
- **keywords** access, denied, table, dbt, tutorial, orders, user, does

**24.** given code `—`

```text
12:57:32  Encountered an error:
Database Error
  expected str, bytes or os.PathLike object, not NoneType
```

- **type** `—` · **fp** `ac74e235485dde0b`
- **template** `Encountered an error: Database Error expected str, bytes or os.PathLike object, not NoneType`
- **values** —
- **keywords** encountered, database, expected, str, bytes, pathlike, object, nonetype

**25.** given code `—`

```text
19:09:40  Compilation Error in model testy_mctest_face (models\testy_mctest_face.sql)
19:09:40    When searching for a relation, dbt found an approximate match. Instead of guessing
19:09:40    which relation to use, dbt will move on. Please delete AYC58.TESTY_MCTEST_FACE, or rename it to be less ambiguous.
19:09:40    Searched for: AYC58.TESTY_MCTEST_FACE
19:09:40    Found: AYC58.TESTY_MCTEST_FACE
19:09:40
19:09:40    > in macro materialization_table_oracle (macros\materializations\table\table.sql)
19:09:40    > called by model testy_mcte
```

- **type** `dbt_compilation_error` · **fp** `fd93f06e4a173193`
- **template** `When searching for a relation, dbt found an approximate match. Instead of guessing which relation to use, dbt will move on. Please delete <NAME>, or rename it to be less ambiguous. Searched for: <NAME> Found: <NAME> > in macro <NAME> (<PATH>) > called by model <NAME>`
- **values** PATH: macros\materializations\table\table.sql; NAME: AYC58, TESTY_MCTEST_FACE, AYC58, TESTY_MCTEST_FACE …
- **keywords** when, searching, relation, dbt, found, approximate, match, instead

**26.** given code `—`

```text
Compilation Error in model jira_custops (models/jira_custops.sql)
'None' has no attribute 'table'. This can happen when calling a macro that does not exist. Check for typos and/or install package dependencies with "dbt deps".
```

- **type** `dbt_compilation_error` · **fp** `6181d58bef42f793` ×4
- **template** `<NAME> has no attribute <NAME>. This can happen when calling a macro that does not exist. Check for typos <PATH> install package dependencies with <NAME>.`
- **values** NAME: None, table, dbt deps; PATH: and/or
- **keywords** attribute, can, happen, when, calling, macro, does, exist

**27.** given code `—`

```text
Encountered an error: Runtime Error Compilation Error in sql_operation inline_query (from remote system.sql) 'dbt.context.macros.MacroNamespace object' has no attribute 'sha2'. This can happen when calling a macro that does not exist. Check for typos and/or install package dependencies with "dbt deps".
```

- **type** `—` · **fp** `55dfd8e665488257`
- **template** `Encountered an error: Runtime Error Compilation Error in <NAME> <NAME> (from remote <PATH>) <NAME> has no attribute <NAME>. This can happen when calling a macro that does not exist. Check for typos <PATH> install package dependencies with <NAME>.`
- **values** NAME: dbt.context.macros.MacroNamespace object, sha2, dbt deps, sql_operation …; PATH: and/or, system.sql
- **keywords** encountered, runtime, compilation, remote, attribute, can, happen, when

**28.** given code `—`

```text
Compilation Error in model fedex_2_client_charges (models\fedex_2\fedex_2_client_charges.sql)
  'None' has no attribute 'table'. This can happen when calling a macro that does not exist. Check for typos and/or install package dependencies with "dbt deps".
```

- **type** `dbt_compilation_error` · **fp** `6181d58bef42f793` ×4
- **template** `<NAME> has no attribute <NAME>. This can happen when calling a macro that does not exist. Check for typos <PATH> install package dependencies with <NAME>.`
- **values** NAME: None, table, dbt deps; PATH: and/or
- **keywords** attribute, can, happen, when, calling, macro, does, exist

**29.** given code `—`

```text
Encountered an error:
Got a non-zero returncode running: ['C:\\Program Files\\Git\\cmd\\git.EXE', 'clone', '--depth', '1', 'https://dev.azure.com/XYZ/z1', '8d432d9f6809c664']
```

- **type** `—` · **fp** `b065bd826d97124f`
- **template** `Encountered an error: Got a non-zero returncode running: [<NAME>]`
- **values** URL: https://dev.azure.com/XYZ/z1; HEX: 8d432d9f6809c664; NAME: C:\\Program Files\\Git\\cmd\\git.EXE, clone, --depth, 1 …
- **keywords** encountered, got, non, zero, returncode, running

**30.** given code `—`

```text
17:17:17  Encountered an error:
    External connection exception occurred: HTTPSConnectionPool(host='codeload.github.com', port=443): Max retries exceeded with url: /dbt-labs/dbt-utils/tar.gz/1.1.1 (Caused by SSLError(SSLCertVerificationError(1, '[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self signed certificate in certificate chain (_ssl.c:992)')))
```

- **type** `—` · **fp** `0c7f62b6259767ef`
- **template** `Encountered an error: External connection exception occurred: HTTPSConnectionPool(host=<NAME>, port=<NUM>): Max retries exceeded with url: /<PATH> (Caused by SSLError(SSLCertVerificationError(<NUM>, <NAME>)))`
- **values** NAME: codeload.github.com, [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self signed certificate in certificate chain (_ssl.c:992); PATH: dbt-labs/dbt-utils/tar.gz/1.1.1; NUM: 443, 1
- **keywords** encountered, external, connection, occurred, httpsconnectionpool, host, port, max

**31.** given code `—`

```text
Encountered an error:
Unable to connect to registry hub
```

- **type** `—` · **fp** `dd7552b2bb3ee1bc`
- **template** `Encountered an error: Unable to connect to registry hub`
- **values** —
- **keywords** encountered, unable, connect, registry, hub

**32.** given code `—`

```text
13:54:01  Encountered an error while generating catalog: Database Error
  TrinoExternalError(type=EXTERNAL, name=JDBC_ERROR, message="Error listing table columns for catalog ga_ds_datamart_qa: Failed to get case sensitivity for columns. Invalid column name 'ServiceOrganisationCode'.", query_id=20250630_135323_24382_eup2w)
13:54:01  dbt encountered 1 failure while writing the catalog
13:54:01  Catalog written to /workspaces/Dbt_Starburst_Galaxy/target/catalog.json
```

- **type** `—` · **fp** `46582dbbb268a7dc`
- **template** `Encountered an error while generating catalog: Database Error TrinoExternalError(type=EXTERNAL, name=<NAME>, message=<NAME>=<NAME>) dbt encountered <NUM> failure while writing the catalog Catalog written to /<PATH>`
- **values** NAME: ServiceOrganisationCode, Error listing table columns for catalog ga_ds_datamart_qa: Failed to get case sensitivity for columns. Invalid column name <NAME>., JDBC_ERROR, query_id …; PATH: workspaces/Dbt_Starburst_Galaxy/target/catalog.json; NUM: 1
- **keywords** encountered, while, generating, catalog, database, trinoexternalerror, external, name

**33.** given code `—`

```text
Profile loading failed for the following reason:
Runtime Error
  Credentials in profile "dandelion-bq", target "dev" invalid: Runtime Error
    Could not find adapter type bigquery!
```

- **type** `—` · **fp** `0864469d3887c1d7` ×2
- **template** `Profile loading failed for the following reason: Runtime Error Credentials in profile <NAME>, target <NAME> invalid: Runtime Error Could not find adapter type bigquery!`
- **values** NAME: dandelion-bq, dev
- **keywords** profile, loading, following, reason, runtime, credentials, target, invalid

**34.** given code `—`

```text
Encountered an error:
Version error for package fivetran/fivetran_utils: Could not find a satisfactory version from options: ['=0.2.9', '>=0.2.0', '<0.3.0', '>=0.2.0', '<0.3.0', '>=0.2.0', '<0.3.0', '>=0.3.0', '<0.4.0']
```

- **type** `—` · **fp** `b69be064c65cf750`
- **template** `Encountered an error: Version error for package <PATH>: Could not find a satisfactory version from options: [<NAME>]`
- **values** NAME: =0.2.9, >=0.2.0, <0.3.0, >=0.2.0 …; PATH: fivetran/fivetran_utils
- **keywords** encountered, version, package, could, find, satisfactory, options

**35.** given code `—`

```text
Compilation Error
dbt found two resources with the name "google_ads__url_ad_adapter". Since these resources have 
the same name,
dbt will be unable to find the correct resource when ref("google_ads__url_ad_adapter") is 
used. To fix this,
change the name of one of these resources:
- model.google_ads.google_ads__url_ad_adapter    (models/url_google_ads/google_ads__url_ad_adapter.sql)
- model.google_ads.google_ads__url_ad_adapter    (models/url_adwords/google_ads__url_ad_adapter.sql)
```

- **type** `—` · **fp** `2baabb44ebf601f0`
- **template** `Compilation Error dbt found two resources with the name <NAME>. Since these resources have the same name, dbt will be unable to find the correct resource when ref(<NAME>) is used. To fix this, change the name of one of these resources: - model.<NAME> (<PATH>) - model.<NAME> (<PATH>)`
- **values** NAME: google_ads__url_ad_adapter, google_ads__url_ad_adapter, google_ads, google_ads__url_ad_adapter …; PATH: models/url_google_ads/google_ads__url_ad_adapter.sql, models/url_adwords/google_ads__url_ad_adapter.sql
- **keywords** compilation, dbt, found, two, resources, name, since, these

**36.** given code `—`

```text
Compilation Error in model stg_vocabulary_hub__mappayer_ri_drg (models/staging/vocabulary_hub/stg_vocabulary_hub__mappayer_ri_drg.sql)
  TransactionContext Error: Catalog write-write conflict on create with "vocabulary_hub"
```

- **type** `dbt_compilation_error` · **fp** `98ed3a8f7519ae10`
- **template** `TransactionContext Error: Catalog write-write conflict on create with <NAME>`
- **values** NAME: vocabulary_hub
- **keywords** transactioncontext, catalog, write, conflict, create

**37.** given code `—`

```text
Compilation Error in model stg_netsuite2__account_types_tmp (models/netsuite2/staging/tmp/stg_netsuite2__account_types_tmp.sql)
  'dict object' has no attribute 'union_connections'. This can happen when calling a macro that does not exist. Check for typos and/or install package dependencies with "dbt deps".
```

- **type** `dbt_compilation_error` · **fp** `6181d58bef42f793` ×4
- **template** `<NAME> has no attribute <NAME>. This can happen when calling a macro that does not exist. Check for typos <PATH> install package dependencies with <NAME>.`
- **values** NAME: dict object, union_connections, dbt deps; PATH: and/or
- **keywords** attribute, can, happen, when, calling, macro, does, exist

**38.** given code `—`

```text
Compilation Error in model snowplow_web_ua_parser_context (models/page_views/optional/snowplow_web_ua_parser_context.sql)
  at path ['enabled']: None is not of type 'boolean' Code: 10004
```

- **type** `dbt_compilation_error` · **fp** `dae1b1ec52e5d742`
- **template** `at path [<NAME>]: None is not of type <NAME> Code: <NUM>`
- **values** NAME: enabled, boolean; NUM: 10004
- **keywords** path, none, code

**39.** given code `—`

```text
Model 'model.test_dbt.my_first_dbt_model' (project2/models/example/my_first_dbt_model.sql) depends on a node named 'abc' which was not found
```

- **type** `—` · **fp** `3da92eda56b77501`
- **template** `Model <NAME> (<PATH>) depends on a node named <NAME> which was not found`
- **values** NAME: model.test_dbt.my_first_dbt_model, abc; PATH: project2/models/example/my_first_dbt_model.sql
- **keywords** model, depends, node, named, found

**40.** given code `—`

```text
12:59:42    Compilation Error in unit_test test_customer_type_mapping (models/marts/__models.yml)
  Unit_Test 'unit_test.customer_success.customers.test_customer_type_mapping' (models/marts/__models.yml) depends on a node named 'orders' in package or project 'revenue' which was not found
```

- **type** `—` · **fp** `32763f41a4c4b099`
- **template** `Compilation Error in <NAME> <NAME> (<PATH>) <NAME> <NAME> (<PATH>) depends on a node named <NAME> in package or project <NAME> which was not found`
- **values** NAME: unit_test.customer_success.customers.test_customer_type_mapping, orders, revenue, unit_test …; PATH: models/marts/__models.yml, models/marts/__models.yml
- **keywords** compilation, depends, node, named, package, project, found

**41.** given code `—`

```text
Compilation Error in model customers (models/customers.sql)
  Model 'model.jaffle_shop.customers' (models/customers.sql) depends on a node named 'stg_customer' which was not found
```

- **type** `dbt_compilation_error` · **fp** `49264c367dae8533`
- **template** `Model <NAME> (<PATH>) depends on a node named <NAME> which was not found`
- **values** NAME: model.jaffle_shop.customers, stg_customer; PATH: models/customers.sql
- **keywords** model, depends, node, named, found

**42.** given code `—`

```text
Found a cycle: model.jaffle_shop.customers --> model.jaffle_shop.stg_customers --> model.jaffle_shop.customers
```

- **type** `—` · **fp** `17454a23e1ec1dcf`
- **template** `Found a cycle: model.<NAME>.customers --> model.<NAME> --> model.<NAME>.customers`
- **values** NAME: jaffle_shop, jaffle_shop, stg_customers, jaffle_shop
- **keywords** found, cycle, model, customers

**43.** given code `—`

```text
Database Error in model customers (models/customers.sql)
  Syntax error: Expected ")" but got identifier `your-info-12345` at [13:15]
  compiled SQL at target/run/jaffle_shop/customers.sql
```

- **type** `dbt_database_error` · **fp** `def1b54a43e15ce9`
- **template** `Syntax error: Expected <NAME> but got identifier <NAME> at <LIST>`
- **values** NAME: ), your-info-12345; LIST: [13:15]
- **keywords** syntax, expected, but, got, identifier

### 001003 (3)

**1.** given code `001003`

```text
09:06:09  Encountered an error while running operation: Database Error
  001003 (42000): SQL compilation error:
  syntax error line 1 at position 0 unexpected '<'.
root@2c50ba8af043:/dbt#
```

- **type** `—` · **fp** `6ab369741f2ed380`
- **template** `Encountered an error while running operation: Database Error <NUM> (<NUM>): SQL compilation error: syntax error line <NUM> at position <NUM> unexpected <NAME>. root@<NAME>:/dbt#`
- **values** NAME: <, 2c50ba8af043; NUM: 001003, 42000, 1, 0
- **keywords** 001003, encountered, while, running, database, sql, compilation, syntax

**2.** given code `001003`

```text
Encountered an error:
Database Error
  001003 (42000): SQL compilation error:
  syntax error line 1 at position 31 unexpected '<EOF>'.
  syntax error line 1 at position 30 unexpected '.'.
```

- **type** `—` · **fp** `55582c5d8145b59c`
- **template** `Encountered an error: Database Error <NUM> (<NUM>): SQL compilation error: syntax error line <NUM> at position <NUM> unexpected <NAME>. syntax error line <NUM> at position <NUM> unexpected <NAME>.`
- **values** NAME: <EOF>, .; NUM: 001003, 42000, 1, 31 …
- **keywords** 001003, encountered, database, sql, compilation, syntax, line, position

**3.** given code `001003`

```text
Database Error in model customers (models/customers.sql)
  001003 (42000): SQL compilation error:
  syntax error line 14 at position 4 unexpected 'from'.
  compiled SQL at target/run/jaffle_shop/models/customers.sql
```

- **type** `dbt_database_error` · **fp** `f98586b01543668c`
- **template** `<NUM> (<NUM>): SQL compilation error: syntax error line <NUM> at position <NUM> unexpected <NAME>.`
- **values** NAME: from; NUM: 001003, 42000, 14, 4
- **keywords** 001003, sql, compilation, syntax, line, position, unexpected

### 002043 (2)

**1.** given code `002043`

```text
Encountered an error:
Runtime Error
  Database error while listing schemas in database "LEE_Test"
  Database Error
    002043 (02000): SQL compilation error:
    Object does not exist, or operation cannot be performed.
```

- **type** `—` · **fp** `4480a82a3a96b32a` ×2
- **template** `Encountered an error: Runtime Error Database error while listing schemas in database <NAME> Database Error <NUM> (<NUM>): SQL compilation error: Object does not exist, or operation cannot be performed.`
- **values** NAME: LEE_Test; NUM: 002043, 02000
- **keywords** 002043, encountered, runtime, database, while, listing, schemas, sql

**2.** given code `002043`

```text
Encountered an error: Runtime Error Database error while listing schemas in database "DEV" Database Error 002043 (02000): SQL compilation error: Object does not exist, or operation cannot be performed.
```

- **type** `—` · **fp** `4480a82a3a96b32a` ×2
- **template** `Encountered an error: Runtime Error Database error while listing schemas in database <NAME> Database Error <NUM> (<NUM>): SQL compilation error: Object does not exist, or operation cannot be performed.`
- **values** NAME: DEV; NUM: 002043, 02000
- **keywords** 002043, encountered, runtime, database, while, listing, schemas, sql

### 250001 (2)

**1.** given code `250001`

```text
dbt was unable to connect to the specified database.
The database returned the following error:

>Database Error
250001: Could not connect to Snowflake backend after 2 attempt(s).Aborting
```

- **type** `—` · **fp** `a06802a6f3ef8fcc`
- **template** `dbt was unable to connect to the specified database. The database returned the following error: >Database Error <NUM>: Could not connect to Snowflake backend after <NUM> attempt(s).Aborting`
- **values** NUM: 250001, 2
- **keywords** 250001, dbt, unable, connect, specified, database, returned, following

**2.** given code `250001`

```text
Encountered an error:
Runtime Error
  Database error while listing schemas in database "analytics"
  Database Error
    250001 (08001): Failed to connect to DB: your_db.snowflakecomputing.com:443. Incorrect username or password was specified.
```

- **type** `—` · **fp** `f9377806f0d8f4d5`
- **template** `Encountered an error: Runtime Error Database error while listing schemas in database <NAME> Database Error <NUM> (<NUM>): Failed to connect to DB: <NAME>.snowflakecomputing.com:<NUM>. Incorrect username or password was specified.`
- **values** NAME: analytics, your_db; NUM: 250001, 08001, 443
- **keywords** 250001, encountered, runtime, database, while, listing, schemas, connect

### 002037 (1)

**1.** given code `002037`

```text
Database Error in test not_null_stg_mytable_myid (models\staging\schema_staging.yml)
14:43:19    002037 (42601): SQL compilation error:
14:43:19    Failure during expansion of view 'STG_MYTABLE': SQL compilation error:
14:43:19    Database 'MYDB' does not exist or not authorized.
14:43:19    compiled Code at 
target\run\myproject\models\staging\schema_staging.yml\not_null_stg_mytable_myid.sql
```

- **type** `dbt_database_error` · **fp** `ae2d26999cf5f363`
- **template** `<NUM> (<NUM>): SQL compilation error: Failure during expansion of view <NAME>: SQL compilation error: Database <NAME> does not exist or not authorized.`
- **values** NAME: STG_MYTABLE, MYDB; NUM: 002037, 42601
- **keywords** 002037, sql, compilation, during, expansion, view, database, does

### 390190 (1)

**1.** given code `390190`

```text
Encountered an error:
Runtime Error
  Database error while listing schemas in database "tgt"
  Database Error
    390190 (08001): Failed to connect to DB: *****.east-us-2.azure.snowflakecomputing.com:443, There was an error related to the SAML Identity Provider account parameter. Contact Snowflake support.
```

- **type** `—` · **fp** `77862725f6f99224`
- **template** `Encountered an error: Runtime Error Database error while listing schemas in database <NAME> Database Error <NUM> (<NUM>): Failed to connect to DB: *****.east-us-<NUM>.azure.snowflakecomputing.com:<NUM>, There was an error related to the SAML Identity Provider account parameter. Contact Snowflake sup`
- **values** NAME: tgt; NUM: 390190, 08001, 2, 443
- **keywords** 390190, encountered, runtime, database, while, listing, schemas, connect

### 42883 (1)

**1.** given code `42883`

```text
Database Error in model my_incremental_model(models\my_incremental_model.sql)
operator does not exist: text || boolean
HINT:  No operator matches the given name and argument type(s). You may need to add explicit type casts.
compiled SQL at target\run\dbt\models\my_incremental_model.sql
```

- **type** `dbt_database_error` · **fp** `33390be0b879afcf`
- **template** `operator does not exist: text \|\| boolean HINT: No operator matches the given name and argument type(s). You may need to add explicit type casts.`
- **values** —
- **keywords** 42883, operator, does, exist, text, boolean, hint, matches

## fivetran (32)

### — (28)

**1.** given code `—`

```text
com.fivetran.port_forwarder.TunnelableConnectionException: Auth fail
```

- **type** `TunnelableConnectionException` · **fp** `5a48478ffc38b2df`
- **template** `com.fivetran.<NAME>.TunnelableConnectionException: Auth fail`
- **values** NAME: port_forwarder
- **keywords** com, fivetran, tunnelableconnectionexception, auth

**2.** given code `—`

```text
Communications link failure\n\n The last packet sent successfully to the server was 0 milliseconds ago. The driver has not received any packets from the server.
```

- **type** `—` · **fp** `6585d7d4f561c50d`
- **template** `Communications link <PATH> The last packet sent successfully to the server was <NUM> milliseconds ago. The driver has not received any packets from the server.`
- **values** PATH: failure\n\n; NUM: 0
- **keywords** communications, link, last, packet, sent, successfully, server, milliseconds

**3.** given code `—`

```text
Lost connection to MySQL server at reading initial communication packet, system error: 0
```

- **type** `—` · **fp** `715251d71da13e92`
- **template** `Lost connection to MySQL server at reading initial communication packet, system error: <NUM>`
- **values** NUM: 0
- **keywords** lost, connection, mysql, server, reading, initial, communication, packet

**4.** given code `—`

```text
Error: The driver received an unexpected pre-login response. Verify the connection properties and check that an instance of SQL Server is running on the host and accepting TCP/IP connections at the port.
```

- **type** `—` · **fp** `d898d3e780635557`
- **template** `Error: The driver received an unexpected pre-login response. Verify the connection properties and check that an instance of SQL Server is running on the host and accepting <PATH> connections at the port.`
- **values** PATH: TCP/IP
- **keywords** driver, received, unexpected, pre, login, response, verify, connection

**5.** given code `—`

```text
Unable to connect to host. Connection error: Connect timed out
```

- **type** `—` · **fp** `0144538b9fbc50cd`
- **template** `Unable to connect to host. Connection error: Connect timed out`
- **values** —
- **keywords** unable, connect, host, connection, timed, out

**6.** given code `—`

```text
Unable to connect to SSH tunnel. Connection error: connect timed out
```

- **type** `—` · **fp** `d1bda708d9f456f6`
- **template** `Unable to connect to SSH tunnel. Connection error: connect timed out`
- **values** —
- **keywords** unable, connect, ssh, tunnel, connection, timed, out

**7.** given code `—`

```text
SSH_MSG_DISCONNECT: 2 Too many authentication failures
```

- **type** `—` · **fp** `7b502399024db108`
- **template** `<NAME>: <NUM> Too many authentication failures`
- **values** NAME: SSH_MSG_DISCONNECT; NUM: 2
- **keywords** too, many, authentication, failures

**8.** given code `—`

```text
Call to Microsoft.Sql/servers failed. Error message: The Resource 'Microsoft.Sql/servers/{serverIdentifier}' under resource group 'proxl-uk' was not found. For more details please go to https://aka.ms/ARMResourceNotFoundFix
```

- **type** `—` · **fp** `debeffb16a052897`
- **template** `Call to <PATH> failed. Error message: The Resource <NAME> under resource group <NAME> was not found. For more details please go to <URL>`
- **values** URL: https://aka.ms/ARMResourceNotFoundFix; NAME: Microsoft.Sql/servers/{serverIdentifier}, proxl-uk; PATH: Microsoft.Sql/servers
- **keywords** call, resource, under, group, found

**9.** given code `—`

```text
Ambiguous column name _fivetran_id
```

- **type** `—` · **fp** `bcc0ac1f56eba081`
- **template** `Ambiguous column name <NAME>`
- **values** NAME: _fivetran_id
- **keywords** ambiguous, column, name

**10.** given code `—`

```text
Hub is unknown to this Hublet, but it appears to exist in Hublet eu1.
```

- **type** `—` · **fp** `bf94d1104473526f`
- **template** `Hub is unknown to this Hublet, but it appears to exist in Hublet <NAME>.`
- **values** NAME: eu1
- **keywords** hub, unknown, hublet, but, appears, exist

**11.** given code `—`

```text
"status": "FAILURE",
"reason": "Failed to sync endpoint(s) with error: {CONTACT=java.lang.NullPointerException, DEAL=java.lang.NullPointerException, LINE_ITEM=java.lang.NullPointerException, COMPANY=java.lang.NullPointerException}"
```

- **type** `java.lang.NullPointerException` · **fp** `571d0c72e668f5a4`
- **template** `<NAME>: <NAME>: <NAME>`
- **values** NAME: status, FAILURE, reason, Failed to sync endpoint(s) with error: {CONTACT=java.lang.NullPointerException, DEAL=java.lang.NullPointerException, LINE_ITEM=java.lang.NullPointerException, COMPANY=java.lang.NullPointerException}
- **keywords** —

**12.** given code `—`

```text
java.net.SocketTimeoutException: Connect timed out
```

- **type** `java.net.SocketTimeoutException` · **fp** `a95e006a5ba48a89`
- **template** `java.net.SocketTimeoutException: Connect timed out`
- **values** —
- **keywords** java, net, sockettimeoutexception, connect, timed, out

**13.** given code `—`

```text
Unable to connect to API. Setup test failed with "javax.ws.rs.ProcessingException: java.net.ConnectException: Connection timed out".
```

- **type** `javax.ws.rs.ProcessingException` · **fp** `673861a470c182ff`
- **template** `Unable to connect to API. Setup test failed with <NAME>.`
- **values** NAME: javax.ws.rs.ProcessingException: java.net.ConnectException: Connection timed out
- **keywords** unable, connect, api, setup, test

**14.** given code `—`

```text
javax.ws.rs.ProcessingException: java.net.UnknownHostException: https
```

- **type** `javax.ws.rs.ProcessingException` · **fp** `3f315e648712089b`
- **template** `javax.ws.rs.ProcessingException: java.net.UnknownHostException: https`
- **values** —
- **keywords** javax, processingexception, java, net, unknownhostexception, https

**15.** given code `—`

```text
Tried connecting to Netsuite.com data source and failed. java.sql.SQLException: [NetSuite][SuiteAnalytics Connect JDBC Driver][OpenAccess SDK SQL Engine]Failed to login using TBA. Error ticket# l7tfl2ac1sdtaf8qmy9ol[232]
```

- **type** `java.sql.SQLException` · **fp** `2e7cd92722d276e7`
- **template** `Tried connecting to Netsuite.com data source and failed. <PATH>.SQLException: <LIST><LIST><LIST>Failed to login using TBA. Error ticket# <NAME><LIST>`
- **values** LIST: [NetSuite], [SuiteAnalytics Connect JDBC Driver], [OpenAccess SDK SQL Engine], [232]; PATH: java.sql; NAME: l7tfl2ac1sdtaf8qmy9ol
- **keywords** tried, connecting, netsuite, com, sqlexception, login, using, tba

**16.** given code `—`

```text
Error updating table: <TABLE NAME> java.sql.SQLException:
\[NetSuite\]\[SuiteAnalytics Connect JDBC Driver\]\[OpenAccess SDK SQL Engine\]
Disk cache error. Field length:4000000 exceeds maximum limit of 65535.\[10232\]
```

- **type** `java.sql.SQLException` · **fp** `bc2539c50394ed13`
- **template** `Error updating table: <TABLE NAME> <PATH>.SQLException: \<LIST>\<LIST>\<LIST> Disk cache error. Field length:<NUM> exceeds maximum limit of <NUM>.\<LIST>`
- **values** LIST: [NetSuite\], [SuiteAnalytics Connect JDBC Driver\], [OpenAccess SDK SQL Engine\], [10232\]; PATH: java.sql; NUM: 4000000, 65535
- **keywords** updating, table, name, sqlexception, disk, cache, field, length

**17.** given code `—`

```text
Setup test failed with "Failure(origin=(informer=(type=connector, externalName=NetSuite connection), server=(name=NetSuite, type=SOURCE)), code=oauth2/token, message=We could not connect to NetSuite because the request either is missing a required parameter or includes an unsupported parameter.)"
```

- **type** `—` · **fp** `e5395c5d066d1dec`
- **template** `Setup test failed with "Failure(origin=(informer=(type=connector, externalName=NetSuite connection), server=(name=NetSuite, type=SOURCE)), code=<PATH>, message=We could not connect to NetSuite because the request either is missing a required parameter or includes an unsupported parameter.)"`
- **values** PATH: oauth2/token
- **keywords** setup, test, origin, informer, connector, externalname, netsuite, connection

**18.** given code `—`

```text
java.sql.SQLException: [NetSuite][SuiteAnalytics Connect JDBC Driver][OpenAccess SDK SQL Engine]You do not have permission to use SuiteAnalytics: Connect service. Please contact your account administrator for assistance. Error ticket#<ticket_id>
```

- **type** `java.sql.SQLException` · **fp** `5439ef5adba6f663`
- **template** `<PATH>.SQLException: <LIST><LIST><LIST>You do not have permission to use SuiteAnalytics: Connect service. Please contact your account administrator for assistance. Error ticket#<ticket_id>`
- **values** LIST: [NetSuite], [SuiteAnalytics Connect JDBC Driver], [OpenAccess SDK SQL Engine]; PATH: java.sql
- **keywords** sqlexception, you, permission, use, suiteanalytics, connect, service, contact

**19.** given code `—`

```text
Error occurred while getting response from Recharge API: Forbidden
```

- **type** `—` · **fp** `b31890488d05c251`
- **template** `Error occurred while getting response from Recharge API: Forbidden`
- **values** —
- **keywords** occurred, while, getting, response, recharge, api, forbidden

**20.** given code `—`

```text
Unable to validate Export folder path: Unable to find Export folder – No such file.
```

- **type** `—` · **fp** `e556489827609ac2`
- **template** `Unable to validate Export folder path: Unable to find Export folder – No such file.`
- **values** —
- **keywords** unable, validate, export, folder, path, find, such, file

**21.** given code `—`

```text
Test connection exception with cause: Access denied for user (using password: YES). Current charset is UTF-8. If password has been set using other charset, consider using option 'passwordCharacterEncoding'.
```

- **type** `—` · **fp** `5c5072f8685923a0`
- **template** `Test connection exception with cause: Access denied for user (using password: YES). Current charset is UTF-<NUM>. If password has been set using other charset, consider using option <NAME>.`
- **values** NAME: passwordCharacterEncoding; NUM: 8
- **keywords** test, connection, cause, access, denied, user, using, password

**22.** given code `—`

```text
Host '10.50.46.137' is blocked because of many connection errors; unblock with 'mysqladmin flush-hosts'
```

- **type** `—` · **fp** `ac98a5d2642aec4a`
- **template** `Host <NAME> is blocked because of many connection errors; unblock with <NAME>`
- **values** IP: 10.50.46.137; NAME: <IP>, mysqladmin flush-hosts
- **keywords** host, blocked, because, many, connection, unblock

**23.** given code `—`

```text
We encountered a table without a primary key in your database that we failed to import after several attempts. To proceed with syncing, please de-select this table in the Schema tab or add a primary key.
```

- **type** `—` · **fp** `061ae199a0dc92da`
- **template** `We encountered a table without a primary key in your database that we failed to import after several attempts. To proceed with syncing, please de-select this table in the Schema tab or add a primary key.`
- **values** —
- **keywords** encountered, table, without, primary, key, your, database, import

**24.** given code `—`

```text
Shut down sync. Heartbeat expired.
```

- **type** `—` · **fp** `ac061aaaa50f481a`
- **template** `Shut down sync. Heartbeat expired.`
- **values** —
- **keywords** shut, down, sync, heartbeat, expired

**25.** given code `—`

```text
Unable to authenticate to Binlog. Try creating the Fivetran user using the 'mysql\_native\_password' password plugin.
```

- **type** `—` · **fp** `fec336418cf1f31a`
- **template** `Unable to authenticate to Binlog. Try creating the Fivetran user using the <NAME> password plugin.`
- **values** NAME: mysql\_native\_password
- **keywords** unable, authenticate, binlog, try, creating, fivetran, user, using

**26.** given code `—`

```text
java.sql.SQLRecoverableException: IO Error: Connection reset by peer, Authentication lapse 0 ms.
```

- **type** `java.sql.SQLRecoverableException` · **fp** `58214f569b4fb2b8`
- **template** `<PATH>.SQLRecoverableException: IO Error: Connection reset by peer, Authentication lapse <NUM> ms.`
- **values** PATH: java.sql; NUM: 0
- **keywords** sqlrecoverableexception, connection, reset, peer, authentication, lapse

**27.** given code `—`

```text
Cannot open log file path C:/<path>/tde/cwallet.sso
```

- **type** `—` · **fp** `af86112cfbcf3dcd`
- **template** `Cannot open log file path C:/<path>/<PATH>`
- **values** PATH: tde/cwallet.sso
- **keywords** cannot, open, log, file, path

**28.** given code `—`

```text
Failed Accessing Glue Resources. We encountered the following error : software.amazon.awssdk.services.s3.model.S3Exception: null (Service: S3, Status Code: 400, Request ID: C0JJM26Q8HKX85S7, Extended Request ID: SUhF5M94lRj10YoDbK6L47MIU/8CZyKZXiJtPljjrS47L7Nh7v0hfITjBOwQPharCRPQ4qFI994=)
```

- **type** `model.S3Exception` · **fp** `14352ea897b769cf`
- **template** `Failed Accessing Glue Resources. We encountered the following error : software.amazon.awssdk.services.s3.model.<NAME>: null (Service: S3, Status Code: <NUM>, Request ID: <NAME>, Extended Request ID: <PATH>=)`
- **values** PATH: SUhF5M94lRj10YoDbK6L47MIU/8CZyKZXiJtPljjrS47L7Nh7v0hfITjBOwQPharCRPQ4qFI994; NAME: S3Exception, C0JJM26Q8HKX85S7; NUM: 400
- **keywords** accessing, glue, resources, encountered, following, software, amazon, awssdk

### 10007 (1)

**1.** given code `10007`

```text
{"message":"This integration is not eligible to use the legacy /v1/requestToken endpoint because the integration uses enhanced OAuth 2.0 functionality. To obtain a token for this integration, use the applicable Marketing Cloud OAuth 2.0 endpoint for authentication. For a web or public app, use /v2/authorize and then /v2/token. For a server-to-server integration, use /v2/token.","errorcode":10007,"documentation":""}
```

- **type** `—` · **fp** `f8480922289fe60f`
- **template** `{<NAME>:"This integration is not eligible to use the legacy /<PATH> endpoint because the integration uses enhanced OAuth <NUM> functionality. To obtain a token for this integration, use the applicable Marketing Cloud OAuth <NUM> endpoint for authentication. For a web or public app, use /<PATH> and t`
- **values** NAME: message, ,, :10007,, :; PATH: v1/requestToken, v2/authorize, v2/token., v2/token.; NUM: 2.0, 2.0
- **keywords** 10007, integration, eligible, use, legacy, endpoint, because, uses

### 429 (1)

**1.** given code `429`

```text
HTTP 429: Rate limit exceeded
```

- **type** `—` · **fp** `fe9f5fd498879702`
- **template** `HTTP <NUM>: Rate limit exceeded`
- **values** NUM: 429
- **keywords** 429, http, rate, limit, exceeded

### ORA-01031 (1)

**1.** given code `ORA-01031`

```text
Unable to validate archive log access.  Could not execute DBMS_LOGMNR.START_LOGMNR: ORA-01031: insufficient privileges    ORA-06512: at ""SYS.DBMS_LOGMNR"", line 82 ORA-06512: at line 1
```

- **type** `—` · **fp** `b74848da374a70cc`
- **template** `Unable to validate archive log access. Could not execute <NAME>: ORA-<NUM>: insufficient privileges ORA-<NUM>: at "<NAME>", line <NUM> ORA-<NUM>: at line <NUM>`
- **values** NAME: SYS.DBMS_LOGMNR, DBMS_LOGMNR, START_LOGMNR; NUM: 01031, 06512, 82, 06512 …
- **keywords** ora-01031, unable, validate, archive, log, access, could, execute

### XL03000006 (1)

**1.** given code `XL03000006`

```text
Error no: XL03000006, Incorrect Intacct XML Partner ID or password.
```

- **type** `—` · **fp** `c4dafd899a665836`
- **template** `Error no: <NAME>, Incorrect Intacct XML Partner ID or password.`
- **values** NAME: XL03000006
- **keywords** xl03000006, incorrect, intacct, xml, partner, password

## matillion (24)

### — (21)

**1.** given code `—`

```text
Environment connection creation failed: JDBC driver encountered communication error. Message: HTTP status=404.
```

- **type** `—` · **fp** `46a0c61728f47db7`
- **template** `Environment connection creation failed: JDBC driver encountered communication error. Message: HTTP status=<NUM>.`
- **values** NUM: 404
- **keywords** environment, connection, creation, jdbc, driver, encountered, communication, http

**2.** given code `—`

```text
ERROR: syntax error at or near "SET"
  Position: 88
```

- **type** `—` · **fp** `556d7db211afff33`
- **template** `ERROR: syntax error at or near <NAME> Position: <NUM>`
- **values** NAME: SET; NUM: 88
- **keywords** syntax, near, position

**3.** given code `—`

```text
Error Max LOB size (16777216) exceeded, actual size of parsed column is xxx
```

- **type** `—` · **fp** `43c2767e5aeab4da`
- **template** `Error Max LOB size (<NUM>) exceeded, actual size of parsed column is xxx`
- **values** NUM: 16777216
- **keywords** max, lob, size, exceeded, actual, parsed, column, xxx

**4.** given code `—`

```text
SQL compilation error:
syntax error line 2 at position 32 unexpected '19'.
syntax error line 2 at position 36 unexpected '28'.
syntax error line 2 at position 39 unexpected '51'.
```

- **type** `—` · **fp** `bf485986bdd9c56a`
- **template** `SQL compilation error: syntax error line <NUM> at position <NUM> unexpected <NAME>. syntax error line <NUM> at position <NUM> unexpected <NAME>. syntax error line <NUM> at position <NUM> unexpected <NAME>.`
- **values** NAME: 19, 28, 51; NUM: 2, 32, 2, 36 …
- **keywords** sql, compilation, syntax, line, position, unexpected

**5.** given code `—`

```text
Traceback (most recent call last):
  File "/tmp/interpreter-input-8418eaf0-9ef7-4d99-a0fd-7cb519c67759.tmp", line 19, in <module>
    call(["python", "r'//caid-fs02/Python Work/data.py"])
NameError: name 'call' is not defined
Script failed with status: 1
```

- **type** `NameError` · **fp** `d440040139e1ee18`
- **template** `Traceback (most recent call last): File <NAME>, line <NUM>, in <module> call([<NAME>]) NameError: name <NAME> is not defined Script failed with status: <NUM>`
- **values** ID: 8418eaf0-9ef7-4d99-a0fd-7cb519c67759; NAME: call, /tmp/interpreter-input-<ID>.tmp, python, r'//caid-fs02/Python Work/data.py; NUM: 19, 1
- **keywords** traceback, most, recent, call, last, file, line, nameerror

**6.** given code `—`

```text
#434 [Query Facebook] - Parameter Validation Failure:

SQL Query - [190] (#190) This method must be called with a Page Access Token.
```

- **type** `—` · **fp** `db8f8ea50a8d9cae`
- **template** `#<NUM> <LIST> - Parameter Validation Failure: SQL Query - <LIST> (#<NUM>) This method must be called with a Page Access Token.`
- **values** LIST: [Query Facebook], [190]; NUM: 434, 190
- **keywords** parameter, validation, sql, query, method, must, called, page

**7.** given code `—`

```text
Traceback (most recent call last):
  File "/tmp/interpreter-input-106f3f10-6834-4b31-bfca-ea489348086f.tmp", line 15, in <module>
    import boto3
ModuleNotFoundError: No module named 'boto3'
```

- **type** `ModuleNotFoundError` · **fp** `ae1314ad68abb622`
- **template** `Traceback (most recent call last): File <NAME>, line <NUM>, in <module> import <NAME> ModuleNotFoundError: No module named <NAME>`
- **values** ID: 106f3f10-6834-4b31-bfca-ea489348086f; NAME: boto3, /tmp/interpreter-input-<ID>.tmp, boto3; NUM: 15
- **keywords** traceback, most, recent, call, last, file, line, import

**8.** given code `—`

```text
java.lang.ClassCastException: java.lang.ClassCastException: java.lang.String cannot be cast to org.python.core.PyList in  at line number 26
```

- **type** `java.lang.ClassCastException` · **fp** `9dd3ceb2d5edaafb`
- **template** `java.lang.ClassCastException: java.lang.ClassCastException: java.lang.String cannot be cast to org.python.core.PyList in at line number <NUM>`
- **values** NUM: 26
- **keywords** java, lang, classcastexception, string, cannot, cast, org, python

**9.** given code `—`

```text
This type of correlated subquery pattern is not supported due to internal error
```

- **type** `—` · **fp** `a014bcf2556f6ee1`
- **template** `This type of correlated subquery pattern is not supported due to internal error`
- **values** —
- **keywords** correlated, subquery, pattern, supported, due, internal

**10.** given code `—`

```text
No active warehouse selected in the current session. Select an active warehouse with the 'use warehouse' command.
```

- **type** `—` · **fp** `322bf558b00a90ee`
- **template** `No active warehouse selected in the current session. Select an active warehouse with the <NAME> command.`
- **values** NAME: use warehouse
- **keywords** active, warehouse, selected, current, session, select, command

**11.** given code `—`

```text
Sorry. You can't add more items to a closed queue.
```

- **type** `—` · **fp** `923197bf9cd14cec`
- **template** `Sorry. You can't add more items to a closed queue.`
- **values** —
- **keywords** sorry, you, can, add, items, closed, queue

**12.** given code `—`

```text
Exception: java.io.IOException: Stream is already closed.
```

- **type** `java.io.IOException` · **fp** `545fd01568dd695b`
- **template** `Exception: java.io.IOException: Stream is already closed.`
- **values** —
- **keywords** java, ioexception, stream, already, closed

**13.** given code `—`

```text
SQL compilation error: error line 1 at position 60
```

- **type** `—` · **fp** `945083c9081e7a2e`
- **template** `SQL compilation error: error line <NUM> at position <NUM>`
- **values** NUM: 1, 60
- **keywords** sql, compilation, line, position

**14.** given code `—`

```text
invalid identifier '"COUNT(*)"'
```

- **type** `—` · **fp** `443c89d81ba3cb58`
- **template** `invalid identifier <NAME>`
- **values** NAME: COUNT(*)
- **keywords** invalid, identifier

**15.** given code `—`

```text
Parameter Validation Failure: Stage - Unrecognised options.
```

- **type** `—` · **fp** `fcfcacb7fdb529d1`
- **template** `Parameter Validation Failure: Stage - Unrecognised options.`
- **values** —
- **keywords** parameter, validation, stage, unrecognised, options

**16.** given code `—`

```text
Could not connect: Access denied for user 'srcuser'@'ec2-44-204-125-37.compute-1.amazonaws.com' (using password: YES)
```

- **type** `—` · **fp** `b1c1d9e34c4ff479`
- **template** `Could not connect: Access denied for user <NAME>@<NAME> (using password: YES)`
- **values** NAME: srcuser, ec2-44-204-125-37.compute-1.amazonaws.com
- **keywords** could, connect, access, denied, user, using, password, yes

**17.** given code `—`

```text
[jcc][t4][2030][11211][4.27.25] A communication error occurred during operations on the connection's underlying socket, socket input stream,
```

- **type** `—` · **fp** `419cba4f674d0324`
- **template** `<LIST><LIST><LIST><LIST><LIST> A communication error occurred during operations on the connection's underlying socket, socket input stream,`
- **values** LIST: [jcc], [t4], [2030], [11211] …
- **keywords** communication, occurred, during, operations, connection, underlying, socket, input

**18.** given code `—`

```text
No X11 DISPLAY variable was set, but this program performed an operation which requires it.
```

- **type** `—` · **fp** `8f1295f63d6e6604`
- **template** `No <NAME> DISPLAY variable was set, but this program performed an operation which requires it.`
- **values** NAME: X11
- **keywords** display, variable, set, but, program, performed, requires

**19.** given code `—`

```text
software.amazon.awssdk.services.s3.model.NoSuchBucketException: The specified bucket does not exist (Service: S3, Status Code: 404, Request ID: BPYPXQWD0FGKFF5B, Extended Request ID: HHzvdNKh1JPqvIWPItOTlcCG7cqnfxPtf7u2hAot52NtrQtsYZ/+YqQGB3VCHo2o5cCKfT/8gqo=)
```

- **type** `model.NoSuchBucketException` · **fp** `04c72a4deca40af2`
- **template** `software.amazon.awssdk.services.s3.model.NoSuchBucketException: The specified bucket does not exist (Service: S3, Status Code: <NUM>, Request ID: <NAME>, Extended Request ID: <NAME>/+<PATH>=)`
- **values** PATH: YqQGB3VCHo2o5cCKfT/8gqo; NAME: BPYPXQWD0FGKFF5B, HHzvdNKh1JPqvIWPItOTlcCG7cqnfxPtf7u2hAot52NtrQtsYZ; NUM: 404
- **keywords** software, amazon, awssdk, services, model, nosuchbucketexception, specified, bucket

**20.** given code `—`

```text
java.lang.OutOfMemoryError: Java heap space
```

- **type** `java.lang.OutOfMemoryError` · **fp** `35d8db9a30fe3a9c`
- **template** `java.lang.OutOfMemoryError: Java heap space`
- **values** —
- **keywords** java, lang, outofmemoryerror, heap, space

**21.** given code `—`

```text
Initialization of repository destination INERP_JCO_DESTINATION_NAME3 failed
```

- **type** `—` · **fp** `62d6e089b831f278`
- **template** `Initialization of repository destination <NAME> failed`
- **values** NAME: INERP_JCO_DESTINATION_NAME3
- **keywords** initialization, repository, destination

### 1214 (1)

**1.** given code `1214`

```text
err code: 1214    Delimited value missing end quote
```

- **type** `—` · **fp** `afadf29c465bbd89`
- **template** `err code: <NUM> Delimited value missing end quote`
- **values** NUM: 1214
- **keywords** 1214, err, code, delimited, missing, end, quote

### 352 (1)

**1.** given code `352`

```text
Error code: [352] - "Unsupported OP_QUERY command: listCollections. The client driver may require an upgrade. For more details see https://dochub.mongodb.org/core/legacy-opcode-removal".`
```

- **type** `—` · **fp** `f5d3f59c2a881dc7`
- **template** `Error code: <LIST> - <NAME>.``
- **values** URL: https://dochub.mongodb.org/core/legacy-opcode-removal; NAME: Unsupported OP_QUERY command: listCollections. The client driver may require an upgrade. For more details see <URL>; LIST: [352]
- **keywords** 352, code

### 401 (1)

**1.** given code `401`

```text
HTTP protocol error. 401 .
```

- **type** `—` · **fp** `b7d12da773243ab6`
- **template** `HTTP protocol error. <NUM> .`
- **values** NUM: 401
- **keywords** 401, http, protocol
