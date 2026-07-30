"""GST returns snapshot (module: gst)."""

from datetime import date

from fastapi import APIRouter, Depends, Query

from api.auth import require_permission
from services.gst_report_service import GstReportService
from services.permissions import MODULE_GST

router = APIRouter(prefix="/api/gst", tags=["gst"])


@router.get("/gstr3b", dependencies=[Depends(require_permission(MODULE_GST))])
def gstr3b(date_from: date = Query(...), date_to: date = Query(...)):
    return GstReportService.get_gstr3b_summary(date_from, date_to)
