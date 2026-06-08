# mcp_server/agents/calendar_agent.py
"""
Calendar Agent: Google Calendar 전담
- 일정 생성, 조회, 수정, 삭제, 검색
"""
import sys
from .base_agent import BaseAgent


class CalendarAgent(BaseAgent):
    """Google Calendar 전문 Agent"""

    def __init__(self, llm_config: dict, service_manager=None):
        super().__init__(
            name="Calendar Agent",
            description="Google Calendar에서 일정 생성, 조회, 수정, 삭제를 전담합니다. "
                       "미팅 일정을 잡거나, 앞으로의 일정을 확인하고, "
                       "일정을 검색합니다.",
            llm_config=llm_config,
        )
        self.service_manager = service_manager

    def register_tools_from_services(self, user_id: str = None):
        """서비스에서 도구 함수를 가져와 등록"""
        from ..services import calendar_service

        async def add_calendar_event(title: str, start_datetime: str, end_datetime: str,
                                      description: str = "", location: str = ""):
            return calendar_service.create_event(
                title=title, start_datetime=start_datetime,
                end_datetime=end_datetime, description=description,
                location=location, user_id=user_id,
            )

        async def get_calendar_events(days: int = 7, max_results: int = 10):
            return calendar_service.get_events(
                days=days, max_results=max_results, user_id=user_id
            )

        async def update_calendar_event(event_id: str, title: str = None,
                                         start_datetime: str = None,
                                         end_datetime: str = None,
                                         description: str = None,
                                         location: str = None):
            return calendar_service.update_event(
                event_id=event_id, title=title,
                start_datetime=start_datetime, end_datetime=end_datetime,
                description=description, location=location, user_id=user_id,
            )

        async def delete_calendar_event(event_id: str):
            return calendar_service.delete_event(event_id=event_id, user_id=user_id)

        async def search_calendar_events(query: str, days: int = 30):
            return calendar_service.search_events(
                query=query, days=days, user_id=user_id
            )

        async def get_calendar_status():
            return calendar_service.get_user_service_status(user_id) if user_id else calendar_service.get_service_status()

        self.register_tool('add_calendar_event', add_calendar_event,
                          '새 일정을 생성합니다 (title, start_datetime, end_datetime)')
        self.register_tool('get_calendar_events', get_calendar_events,
                          '앞으로의 일정을 조회합니다 (days: 일수, max_results: 최대 건수)')
        self.register_tool('update_calendar_event', update_calendar_event,
                          '기존 일정을 수정합니다 (event_id 필수)')
        self.register_tool('delete_calendar_event', delete_calendar_event,
                          '일정을 삭제합니다 (event_id)')
        self.register_tool('search_calendar_events', search_calendar_events,
                          '키워드로 일정을 검색합니다 (query, days)')
        self.register_tool('get_calendar_status', get_calendar_status,
                          'Google Calendar 서비스 연결 상태를 확인합니다')

        print(f"[Calendar Agent] {len(self._tools)} tools registered for user: {user_id}", file=sys.stderr)
