# mcp_server/agents/__init__.py
"""
Enterprise AI Multi-Agent 시스템 (6개 전문 Agent)
- Orchestrator: 사용자 요청을 분석하여 적절한 Agent에게 위임
- Email Agent: Gmail + AI 분석 전담
- CRM Agent: Salesforce 전담
- Calendar Agent: Google Calendar 전담
- CS Agent: 고객 서비스 전담 (product_docs Collection)
- Helpdesk Agent: 내부 헬프데스크 전담 (internal_docs Collection)
- Report Agent: 로그 분석 + 시스템 모니터링 전담
"""

from .base_agent import BaseAgent
from .orchestrator import Orchestrator
from .email_agent import EmailAgent
from .crm_agent import CRMAgent
from .calendar_agent import CalendarAgent
from .cs_agent import CSAgent
from .helpdesk_agent import HelpdeskAgent
from .report_agent import ReportAgent

__all__ = [
    'BaseAgent',
    'Orchestrator',
    'EmailAgent',
    'CRMAgent',
    'CalendarAgent',
    'CSAgent',
    'HelpdeskAgent',
    'ReportAgent',
]
