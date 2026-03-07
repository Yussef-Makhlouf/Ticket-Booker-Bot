class SessionManager:
    """
    Manages Playwright browser sessions for the bot
    """
    def __init__(self):
        self.automation = None

    async def get_automation(self):
        from services.webook_automation import WebookAutomation
        if not self.automation:
            self.automation = WebookAutomation(headless=True)
            await self.automation.start()
        return self.automation

    async def close_all(self):
        if self.automation:
            await self.automation.close()
            self.automation = None

session_manager = SessionManager()
