"""任務模組 API Router 聚合入口。

此模組負責匯總並曝露任務管理、結果查詢與報表匯出等 API 路由子模組。
"""

from fastapi import APIRouter

from backend.jobs.routers.export import router as export_router
from backend.jobs.routers.management import router as management_router
from backend.jobs.routers.results import router as results_router

router: APIRouter = APIRouter()

router.include_router(management_router)
router.include_router(results_router)
router.include_router(export_router)
