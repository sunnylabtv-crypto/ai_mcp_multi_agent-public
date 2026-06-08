# mcp_server/agents/email_agent.py
"""
Email Agent: 이메일 조회, AI 분석, 답변 생성 및 발송 전담
- Gmail MCP 도구 + OpenAI 분석 도구
"""
import sys
import asyncio
from .base_agent import BaseAgent


class EmailAgent(BaseAgent):
    """이메일 전문 Agent"""

    def __init__(self, llm_config: dict, service_manager=None):
        super().__init__(
            name="Email Agent",
            description="이메일 조회, AI 분석, 답변 생성 및 발송을 전담합니다. "
                       "Gmail에서 이메일을 가져오고, AI로 고객 정보를 추출하며, "
                       "맞춤형 답변을 생성하여 발송합니다.",
            llm_config=llm_config,
        )
        self.service_manager = service_manager

    def register_tools_from_services(self, user_id: str = None):
        """서비스에서 도구 함수를 가져와 등록"""
        from ..services import gmail_service, openai_service

        # Gmail 도구
        async def fetch_unread_emails(minutes_ago: int = 60, max_results: int = 5):
            return gmail_service.get_recent_emails(
                minutes_ago=minutes_ago, max_results=max_results, user_id=user_id
            )

        async def send_email_reply(to_email: str, subject: str, body: str,
                                    attachment_base64: str = None,
                                    attachment_filename: str = None):
            if attachment_base64:
                return gmail_service.send_reply_with_base64_attachment(
                    to_email=to_email, subject=subject, content=body,
                    attachment_base64=attachment_base64,
                    attachment_filename=attachment_filename,
                    user_id=user_id,
                )
            return gmail_service.send_reply(
                to_email=to_email, subject=subject, content=body, user_id=user_id
            )

        async def get_gmail_status():
            return gmail_service.get_user_service_status(user_id) if user_id else gmail_service.get_service_status()

        # OpenAI 분석 도구 (동기 함수 → asyncio.to_thread)
        async def analyze_email_with_ai(email_content: str, sender_email: str = ""):
            return await asyncio.to_thread(openai_service.extract_customer_info, email_content, sender_email)

        async def generate_email_reply(customer_name: str, company: str = "",
                                        title: str = "", phone: str = "",
                                        email: str = "", original_subject: str = "",
                                        has_all_info: bool = True):
            customer_info = {
                'name': customer_name,
                'company': company,
                'title': title,
                'phone': phone,
                'email': email,
            }
            return await asyncio.to_thread(
                openai_service.generate_reply,
                customer_info=customer_info,
                original_subject=original_subject,
                has_all_info=has_all_info,
            )

        # 도구 등록
        self.register_tool('fetch_unread_emails', fetch_unread_emails,
                          '최근 이메일을 가져옵니다 (minutes_ago: 분, max_results: 최대 건수)')
        self.register_tool('send_email_reply', send_email_reply,
                          '이메일을 발송합니다 (to_email, subject, body)')
        self.register_tool('get_gmail_status', get_gmail_status,
                          'Gmail 서비스 연결 상태를 확인합니다')
        self.register_tool('analyze_email_with_ai', analyze_email_with_ai,
                          'AI로 이메일에서 고객 정보를 추출합니다 (email_content, sender_email)')
        self.register_tool('generate_email_reply', generate_email_reply,
                          'AI로 맞춤형 이메일 답변을 생성합니다')

        print(f"[Email Agent] {len(self._tools)} tools registered for user: {user_id}", file=sys.stderr)
