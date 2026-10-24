"""approvals HTTP extension point; implement endpoints against Application interfaces."""

from fastapi import APIRouter

router = APIRouter(prefix="/approvals", tags=["approvals"])
