# mcp_server/agents/crm_agent.py
"""
CRM Agent: Salesforce CRM 전담
- Lead 생성, 조회, 관리
"""
import sys
from .base_agent import BaseAgent


class CRMAgent(BaseAgent):
    """Salesforce CRM 전문 Agent"""

    def __init__(self, llm_config: dict, service_manager=None):
        super().__init__(
            name="CRM Agent",
            description="Salesforce CRM에서 Lead 생성, 조회, 관리를 전담합니다. "
                       "고객 정보를 받아 Salesforce에 Lead를 등록하고, "
                       "기존 Lead를 조회/검증합니다.",
            llm_config=llm_config,
        )
        self.service_manager = service_manager

    def register_tools_from_services(self, user_id: str = None):
        """서비스에서 도구 함수를 가져와 등록"""
        from ..services import salesforce_service

        async def create_salesforce_lead(customer_name: str, customer_company: str,
                                          customer_email: str, customer_title: str = "",
                                          customer_phone: str = ""):
            customer_info = {
                'name': customer_name,
                'company': customer_company,
                'email': customer_email,
                'title': customer_title,
                'phone': customer_phone,
            }
            return salesforce_service.create_lead(customer_info, user_id=user_id)

        async def verify_salesforce_lead(lead_id: str):
            return salesforce_service.verify_lead(lead_id, user_id=user_id)

        async def get_salesforce_status():
            return salesforce_service.get_user_service_status(user_id) if user_id else salesforce_service.get_service_status()

        self.register_tool('create_salesforce_lead', create_salesforce_lead,
                          'Salesforce에 새 Lead를 생성합니다 (customer_name, customer_company, customer_email)')
        self.register_tool('verify_salesforce_lead', verify_salesforce_lead,
                          'Salesforce Lead 정보를 조회합니다 (lead_id)')
        self.register_tool('get_salesforce_status', get_salesforce_status,
                          'Salesforce 서비스 연결 상태를 확인합니다')

        print(f"[CRM Agent] {len(self._tools)} tools registered for user: {user_id}", file=sys.stderr)
