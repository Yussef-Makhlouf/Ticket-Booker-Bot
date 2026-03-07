# Booking handlers package
from aiogram import Router

from .flow import router as flow_router

router = Router()
router.include_router(flow_router)
