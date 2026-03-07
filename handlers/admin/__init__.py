# Admin handlers package
from aiogram import Router
from .dashboard import router as dashboard_router

router = Router()
router.include_router(dashboard_router)
