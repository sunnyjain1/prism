from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

import schemas
from api.jobs import serialize_job
from core.dependencies import get_current_user, get_db
from services.job_queue import job_queue
from services.report_service import ReportService, run_report_job
from user_models import User

router = APIRouter(prefix="/reports", tags=["reports"])
v1_router = APIRouter(prefix="/reports", tags=["reports"])


def _serialize_report_job(job) -> schemas.ReportJobResponse:
    download_url = None
    if job.status == "completed" and job.file_path:
        download_url = f"/api/v1/reports/{job.id}/download"

    return schemas.ReportJobResponse(
        id=job.id,
        report_type=job.report_type,
        period_start=job.period_start,
        period_end=job.period_end,
        format=job.format,
        status=job.status,
        error_message=job.error_message,
        created_at=job.created_at,
        completed_at=job.completed_at,
        download_url=download_url,
    )


def _download_report(report_id: str, db: Session, current_user: User):
    service = ReportService(db)
    report = service.get_report_job(current_user.id, report_id)
    path = service.resolve_report_path(report)
    download_name = service.build_download_name(report)
    media_type = service.get_media_type(report.format, path)
    return FileResponse(path=path, media_type=media_type, filename=download_name)


@v1_router.post("/generate", response_model=schemas.JobStatusResponse)
@router.post("/generate", response_model=schemas.JobStatusResponse)
def generate_report(
    request: schemas.ReportGenerateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ReportService(db)
    report = service.create_report_job(
        user_id=current_user.id,
        report_type=request.report_type.value,
        period_start=request.period_start,
        period_end=request.period_end,
        output_format=request.format.value,
    )
    job_id = job_queue.enqueue("generate_report", run_report_job, report.id, user_id=current_user.id)
    return serialize_job(job_queue.get_job(job_id))


@v1_router.get("", response_model=list[schemas.ReportJobResponse])
@router.get("", response_model=list[schemas.ReportJobResponse])
def list_reports(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ReportService(db)
    return [_serialize_report_job(job) for job in service.list_report_jobs(current_user.id)]


@v1_router.post("/export/csv")
@router.post("/export/csv")
def export_transactions_csv(
    request: schemas.ReportExportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ReportService(db)
    path = service.export_transactions_csv(
        user_id=current_user.id,
        start_date=request.start_date,
        end_date=request.end_date,
        filters=request.export_filters(),
    )
    return FileResponse(
        path=path,
        media_type="text/csv",
        filename=Path(path).name,
    )


@v1_router.post("/export/xlsx")
@router.post("/export/xlsx")
def export_transactions_xlsx(
    request: schemas.ReportExportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ReportService(db)
    path = service.export_transactions_xlsx(
        user_id=current_user.id,
        start_date=request.start_date,
        end_date=request.end_date,
        filters=request.export_filters(),
    )
    return FileResponse(
        path=path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=Path(path).name,
    )


@v1_router.get("/{report_id}/download")
@router.get("/{report_id}/download")
def download_report(
    report_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _download_report(report_id, db, current_user)
