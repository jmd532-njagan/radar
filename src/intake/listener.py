import hashlib
import hmac
import logging
import uuid
from dataclasses import asdict
from datetime import UTC, datetime

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from chat.notification import prepare_notification
from config.settings import settings
from db import failure_patterns
from db.models import FailureEvent
from db.projects import ensure_project_metadata
from gateway.credential_resolution import get_adf_credential
from intake import signature

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/events")

_SIGNATURE_HEADER = "X-Radar-Signature-256"


class ErrorDetail(BaseModel):
    error_code: str | None = None
    message: str | None = None
    failed_activity_name: str | None = None
    failed_activity_run_id: str | None = None


class PipelineFailureEvent(BaseModel):
    project: str
    platform: str
    pipeline_name: str
    run_status: str
    start_time: datetime
    end_time: datetime | None = None
    trigger_type: str | None = None
    last_error: str | None = None
    error_detail: ErrorDetail | None = None
    # `project` is WatchTower's projectName, used verbatim; RADAR looks up the ADF connection
    # itself (gateway/credential_resolution.py). The HMAC signature comes in a header
    # (X-Radar-Signature-256, like GitHub's X-Hub-Signature-256), signing the raw body.


def _verify_hmac(payload_bytes: bytes, signature: str, secret: str) -> bool:
    expected = hmac.HMAC(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("/pipeline-failure", status_code=202)
async def receive_pipeline_failure(
    request: Request,
    event: PipelineFailureEvent,
    x_radar_signature_256: str | None = Header(default=None, alias=_SIGNATURE_HEADER),
):
    body = await request.body()
    if not x_radar_signature_256 or not _verify_hmac(
        body, x_radar_signature_256, settings.hmac_secret
    ):
        logger.warning(
            "Failure event rejected: bad or missing signature, client=%s",
            request.client.host if request.client else None,
        )
        raise HTTPException(status_code=401, detail="Invalid or missing signature")

    project = event.project

    # Every failure gets its own investigation and chat entry point unconditionally; there is
    # no batch suppression.

    investigation_id = str(uuid.uuid4())
    error_detail = (
        event.error_detail.model_dump(exclude_none=True) if event.error_detail else None
    )
    # A cancelled run isn't a real failure: stored, but no pattern, seed message or notification.
    cancelled = event.run_status in ("Cancelled", "Cancelling", "Canceling")
    sig = (
        None
        if cancelled
        else signature.parse(
            event.platform,
            (error_detail or {}).get("error_code"),
            (error_detail or {}).get("message") or event.last_error,
        )
    )

    async with request.app.state.db_factory() as db:
        await ensure_project_metadata(db, project, event.platform)
        credential = await get_adf_credential(db, project)
        pattern, matched_by = (
            await failure_patterns.match_or_create(
                db, project, sig, event.pipeline_name
            )
            if sig
            else (None, None)
        )
        db.add(
            FailureEvent(
                investigation_id=investigation_id,
                project=project,
                platform=event.platform,
                pipeline_name=event.pipeline_name,
                factory_name=credential.factory_name if credential else None,
                run_status=event.run_status,
                start_time=event.start_time,
                end_time=event.end_time,
                last_error=event.last_error,
                error_detail=error_detail,
                trigger_type=event.trigger_type,
                pattern_id=pattern.id if pattern else None,
                matched_by=matched_by,
                signature=asdict(sig) if sig else None,
                created_at=datetime.now(UTC),
            )
        )
        await db.commit()

    logger.info(
        "Failure received: project=%s pipeline=%s status=%s investigation=%s pattern=%s (%s)",
        project,
        event.pipeline_name,
        event.run_status,
        investigation_id,
        f"FP-{pattern.id}" if pattern else None,
        matched_by or "not matched",
    )
    if cancelled:
        return {"accepted": True, "investigation_id": investigation_id, "user_ids": []}

    recipient_user_ids = await prepare_notification(
        request.app.state.db_factory, investigation_id
    )

    return {
        "accepted": True,
        "investigation_id": investigation_id,
        "user_ids": recipient_user_ids,
    }
