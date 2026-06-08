# mcp_server/server.py
"""
FastMCP Multi-Agent Enterprise AI 서버
- Orchestrator + 6 전문 Agent (Email, CRM, Calendar, CS, Helpdesk, Report)
- 포트: 9000 (MCP), 9001 (Log API)
- 기존 Single Agent(8000)와 동일 GCP VM에서 공존
"""
import sys
import os
import json
import logging
import asyncio
from pathlib import Path
from fastmcp import FastMCP, Context
from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.server.dependencies import get_http_request

# 프로젝트 루트를 Python path에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from mcp_server.config import (
    CONFIG, validate_config, print_config_summary,
    UserConfig, SUPPORTED_USERS,
    MCP_PORT, LOG_API_PORT, AGENT_LLM_CONFIG, AGENT_DEFINITIONS
)
from mcp_server.services.service_manager import (
    initialize_all_services, get_all_service_status,
    initialize_user_services, get_user_service_status,
    set_current_user, get_current_user
)
from mcp_server.logging_middleware import LoggingMiddleware
from mcp_server.log_receiver import router as log_api_router

# Agent imports
from mcp_server.agents.orchestrator import Orchestrator
from mcp_server.agents.email_agent import EmailAgent
from mcp_server.agents.crm_agent import CRMAgent
from mcp_server.agents.calendar_agent import CalendarAgent
from mcp_server.agents.cs_agent import CSAgent
from mcp_server.agents.helpdesk_agent import HelpdeskAgent
from mcp_server.agents.report_agent import ReportAgent

# 로깅 설정
log_handlers = [logging.StreamHandler()]
if os.getenv('MCP_MODE', 'stdio') == 'stdio':
    try:
        log_handlers.append(logging.FileHandler('mcp_server.log', encoding='utf-8'))
    except:
        pass

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=log_handlers
)
logger = logging.getLogger(__name__)

# ============================================================
# 사용자별 서비스 캐시
# ============================================================

_user_services_cache = {}


def get_or_create_user_services(user_id: str):
    """사용자별 서비스 인스턴스 생성/반환"""
    if user_id not in _user_services_cache:
        if not UserConfig.is_valid_user(user_id):
            logger.warning(f"⚠️ 알 수 없는 사용자: {user_id}, 기본값 'admin' 사용")
            user_id = 'admin'

        logger.info(f"🔄 사용자 '{user_id}' 서비스 초기화 중...")
        config = UserConfig.get_config(user_id)
        services = initialize_user_services(config)
        _user_services_cache[user_id] = {
            'config': config,
            'services': services
        }
        logger.info(f"✅ 사용자 '{user_id}' 서비스 초기화 완료")

    return _user_services_cache[user_id]


# ============================================================
# Orchestrator & Agent 인스턴스
# ============================================================

_orchestrator = None
_user_agents_cache = {}  # {user_id: {agent_id: agent}}


def get_or_create_orchestrator(user_id: str = 'admin') -> Orchestrator:
    """Orchestrator 및 Agent 인스턴스 생성/반환"""
    global _orchestrator

    if user_id not in _user_agents_cache:
        logger.info(f"🤖 Agent 시스템 초기화 (user: {user_id})...")

        # Orchestrator 생성 (공유)
        if _orchestrator is None:
            _orchestrator = Orchestrator(llm_config=AGENT_LLM_CONFIG)

        # 전문 Agent 생성 (사용자별)
        email_agent = EmailAgent(llm_config=AGENT_LLM_CONFIG)
        email_agent.register_tools_from_services(user_id=user_id)

        crm_agent = CRMAgent(llm_config=AGENT_LLM_CONFIG)
        crm_agent.register_tools_from_services(user_id=user_id)

        calendar_agent = CalendarAgent(llm_config=AGENT_LLM_CONFIG)
        calendar_agent.register_tools_from_services(user_id=user_id)

        cs_agent = CSAgent(llm_config=AGENT_LLM_CONFIG)
        cs_agent.register_tools_from_services(user_id=user_id)

        helpdesk_agent = HelpdeskAgent(llm_config=AGENT_LLM_CONFIG)
        helpdesk_agent.register_tools_from_services(user_id=user_id)

        report_agent = ReportAgent(llm_config=AGENT_LLM_CONFIG)
        report_agent.register_tools_from_services(user_id=user_id)

        # Orchestrator에 Agent 등록
        _orchestrator.register_agent('email_agent', email_agent)
        _orchestrator.register_agent('crm_agent', crm_agent)
        _orchestrator.register_agent('calendar_agent', calendar_agent)
        _orchestrator.register_agent('cs_agent', cs_agent)
        _orchestrator.register_agent('helpdesk_agent', helpdesk_agent)
        _orchestrator.register_agent('report_agent', report_agent)

        _user_agents_cache[user_id] = {
            'email_agent': email_agent,
            'crm_agent': crm_agent,
            'calendar_agent': calendar_agent,
            'cs_agent': cs_agent,
            'helpdesk_agent': helpdesk_agent,
            'report_agent': report_agent,
        }

        logger.info(f"✅ Agent 시스템 초기화 완료 (user: {user_id})")

    return _orchestrator


# ============================================================
# MCP 인스턴스
# ============================================================

mcp = FastMCP("Enterprise AI Assistant")


# ============================================================
# 유저 식별 미들웨어
# ============================================================

class UserIdentificationMiddleware(Middleware):
    """URL 파라미터에서 user_id와 client_type을 추출하여 서비스 초기화"""

    # 지원하는 client_type 값
    VALID_CLIENT_TYPES = {
        "claude_desktop", "cursor", "adk", "mcp",
    }

    @staticmethod
    def _detect_client_from_ua(user_agent: str) -> str:
        """User-Agent 헤더로 클라이언트 자동 감지 (fallback)"""
        ua = (user_agent or "").lower()
        if "claude-desktop" in ua or "claude_desktop" in ua or "anthropic" in ua:
            return "claude_desktop"
        if "cursor" in ua:
            return "cursor"
        if "mcp-remote" in ua or "npx" in ua:
            return "claude_desktop"  # Cursor는 URL에 client_type=cursor가 있으므로 여기 안 옴
        return "mcp"  # 기본값

    async def _extract_and_set_user(self, context: MiddlewareContext):
        try:
            request = get_http_request()
            user_id = request.query_params.get("user_id", "admin")
            client_type = request.query_params.get("client_type", "")

            # client_type이 명시되지 않았으면 User-Agent로 자동 감지
            if not client_type or client_type not in self.VALID_CLIENT_TYPES:
                user_agent = request.headers.get("user-agent", "")
                client_type = self._detect_client_from_ua(user_agent)

            if user_id not in SUPPORTED_USERS:
                logger.warning(f"⚠️ 알 수 없는 사용자: {user_id}, 기본값 'admin' 사용")
                user_id = "admin"

            get_or_create_user_services(user_id)
            set_current_user(user_id)

            await context.fastmcp_context.set_state("user_id", user_id)
            await context.fastmcp_context.set_state("client_type", client_type)
            await context.fastmcp_context.set_state("user_config", _user_services_cache[user_id]['config'])

            logger.debug(f"🔗 요청 처리: user_id={user_id}, client_type={client_type}")

        except Exception as e:
            logger.warning(f"⚠️ 사용자 식별 실패, 기본값 사용: {e}")
            set_current_user("admin")
            await context.fastmcp_context.set_state("user_id", "admin")
            await context.fastmcp_context.set_state("client_type", "mcp")

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        await self._extract_and_set_user(context)
        return await call_next(context)

    async def on_read_resource(self, context: MiddlewareContext, call_next):
        await self._extract_and_set_user(context)
        return await call_next(context)

    async def on_list_tools(self, context: MiddlewareContext, call_next):
        await self._extract_and_set_user(context)
        return await call_next(context)


# 미들웨어 등록
mcp.add_middleware(UserIdentificationMiddleware())
mcp.add_middleware(LoggingMiddleware())


# ============================================================
# Multi-Agent MCP 도구 등록
# ============================================================

# orchestrate_task 제거됨
# → Claude Desktop의 Claude AI가 직접 적절한 Agent를 선택합니다.
# → OpenAI 중복 호출(Orchestrator → Agent) 제거로 속도 2~3배 개선


async def _run_agent_safe(agent_key: str, agent_label: str, task: str) -> dict:
    """Agent 실행 공통 헬퍼 (에러 핸들링 + 로깅)"""
    import time as _time
    start = _time.time()
    user_id = get_current_user() or 'admin'

    try:
        get_or_create_user_services(user_id)
        get_or_create_orchestrator(user_id)

        agent = _user_agents_cache.get(user_id, {}).get(agent_key)
        if not agent:
            logger.error(f"❌ {agent_label} not initialized for user: {user_id}")
            return {'success': False, 'error': f'{agent_label} not initialized'}

        logger.info(f"🤖 {agent_label} 실행 시작: {task[:80]}...")
        result = await agent.run(task, {'user_id': user_id})
        duration = (_time.time() - start) * 1000
        logger.info(f"✅ {agent_label} 완료 ({duration:.0f}ms, success={result.success})")
        return result.to_dict()

    except Exception as e:
        duration = (_time.time() - start) * 1000
        logger.error(f"❌ {agent_label} 실행 실패 ({duration:.0f}ms): {e}", exc_info=True)
        return {
            'success': False,
            'error': f'{agent_label} 실행 오류: {str(e)}',
            'duration_ms': round(duration, 2),
        }


@mcp.tool()
async def run_email_agent(task: str) -> dict:
    """
    Email Agent에게 직접 작업을 요청합니다.
    이메일 조회, AI 분석, 답변 생성, 발송에 특화된 Agent입니다.

    Args:
        task: 이메일 관련 작업 설명 (예: "최근 30분간 이메일을 확인하고 고객 정보를 추출해줘")
    """
    return await _run_agent_safe('email_agent', 'Email Agent', task)


@mcp.tool()
async def run_crm_agent(task: str) -> dict:
    """
    CRM Agent에게 직접 작업을 요청합니다.
    Salesforce Lead 생성, 조회, 관리에 특화된 Agent입니다.

    Args:
        task: CRM 관련 작업 설명 (예: "홍길동(ABC회사) Lead를 생성해줘")
    """
    return await _run_agent_safe('crm_agent', 'CRM Agent', task)


@mcp.tool()
async def run_calendar_agent(task: str) -> dict:
    """
    Calendar Agent에게 직접 작업을 요청합니다.
    Google Calendar 일정 생성, 조회, 수정, 삭제에 특화된 Agent입니다.

    Args:
        task: 일정 관련 작업 설명 (예: "이번 주 일정을 확인해줘")
    """
    return await _run_agent_safe('calendar_agent', 'Calendar Agent', task)


@mcp.tool()
async def run_cs_agent(task: str) -> dict:
    """
    CS Agent에게 직접 작업을 요청합니다.
    고객 서비스 전문 Agent입니다. 제품 FAQ, 반품/교환 절차, 고객 문의 응대에 특화되어 있습니다.
    VectorDB의 product_docs 컬렉션에서 제품 관련 문서를 검색합니다.

    Args:
        task: 고객 서비스 관련 작업 설명 (예: "이 제품의 반품 절차를 안내해줘")
    """
    return await _run_agent_safe('cs_agent', 'CS Agent', task)


@mcp.tool()
async def run_helpdesk_agent(task: str) -> dict:
    """
    Helpdesk Agent에게 직접 작업을 요청합니다.
    내부 직원용 헬프데스크 Agent입니다. IT, HR, Finance 등 내부 정책/절차 문서를 기반으로 답변합니다.
    VectorDB의 internal_docs 컬렉션에서 내부 문서를 검색합니다.

    Args:
        task: 내부 헬프데스크 관련 작업 설명 (예: "연차 신청 방법을 알려줘", "VPN 설정 방법은?")
    """
    return await _run_agent_safe('helpdesk_agent', 'Helpdesk Agent', task)


@mcp.tool()
async def run_report_agent(task: str) -> dict:
    """
    Report Agent에게 직접 작업을 요청합니다.
    시스템 로그 분석, 사용 통계, 성능 모니터링에 특화된 Agent입니다.

    Args:
        task: 로그/통계 분석 관련 작업 설명 (예: "오늘 도구 사용 통계를 보여줘")
    """
    return await _run_agent_safe('report_agent', 'Report Agent', task)


# ============================================================
# 시스템 도구 (서비스 상태, Agent 정보 등)
# ============================================================

@mcp.tool()
def check_all_services_status() -> dict:
    """모든 서비스와 Agent의 현재 상태를 확인합니다."""
    current_user = get_current_user()
    logger.info(f"📊 서비스 상태 확인 요청 (user: {current_user})")

    try:
        if current_user:
            status = get_user_service_status(current_user)
        else:
            status = get_all_service_status()

        # Agent 정보 추가
        agents_info = {}
        if _orchestrator:
            agents_info = _orchestrator.get_registered_agents()

        summary = {
            "mode": "multi-agent",
            "current_user": current_user,
            "services": {
                "gmail": "✅ 인증됨" if status['gmail']['authenticated'] else "❌ 미인증",
                "gmail_account": status['gmail'].get('user_email', 'unknown'),
                "openai": "✅ 설정됨" if (status['openai']['initialized'] and status['openai']['api_key_configured']) else "❌ 미설정",
                "salesforce": "✅ 인증됨" if status['salesforce']['authenticated'] else "❌ 미인증",
                "vectordb": "✅ 초기화됨" if status['vectordb']['initialized'] else "❌ 미초기화",
                "calendar": "✅ 인증됨" if status['calendar']['authenticated'] else "❌ 미인증",
            },
            "agents": agents_info,
        }

        return {"status": "success", "summary": summary, "details": status}

    except Exception as e:
        logger.error(f"❌ 상태 확인 실패: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


@mcp.tool()
def get_current_user_info() -> dict:
    """현재 연결된 사용자 정보를 반환합니다."""
    current_user = get_current_user()
    if current_user and current_user in _user_services_cache:
        user_data = _user_services_cache[current_user]
        return {
            "user_id": current_user,
            "gmail_account": user_data['config'].get('gmail_account', 'unknown'),
            "sfdc_enabled": user_data['config'].get('sfdc_enabled', False),
            "mode": "multi-agent",
        }
    return {"user_id": current_user or "unknown", "status": "not_initialized"}


@mcp.tool()
def get_agent_info() -> dict:
    """등록된 Agent들의 상세 정보를 반환합니다."""
    if _orchestrator:
        return {
            "status": "success",
            "agents": _orchestrator.get_registered_agents(),
            "total_agents": len(_orchestrator.get_registered_agents()),
        }
    return {"status": "not_initialized", "agents": {}}


@mcp.tool()
def get_execution_history(limit: int = 10) -> dict:
    """최근 Multi-Agent 실행 이력을 반환합니다."""
    if _orchestrator:
        history = _orchestrator.get_execution_history(limit)
        return {
            "status": "success",
            "count": len(history),
            "history": history,
        }
    return {"status": "not_initialized", "history": []}


# ============================================================
# 시스템/로깅 도구만 직접 노출 (Agent를 거칠 필요 없는 것들)
# 비즈니스 도구(Gmail, CRM, Calendar, Helpdesk)는 Agent 경유 전용
# ============================================================

from mcp_server.tools import register_logging_tools

def register_system_tools(mcp_instance):
    """시스템/로깅 도구만 직접 등록"""
    logger.info("🔧 시스템 도구 등록 중...")
    register_logging_tools(mcp_instance)
    logger.info("✅ 시스템 도구 등록 완료!")

register_system_tools(mcp)


# ============================================================
# 서비스 초기화
# ============================================================

def initialize_default_services():
    """기본 서비스 초기화 (admin 사용자)"""
    logger.info("=" * 70)
    logger.info("🚀 Enterprise AI Multi-Agent Server 시작")
    logger.info("=" * 70)

    print_config_summary()

    if not validate_config():
        logger.warning("⚠️ 설정 검증 실패! 일부 기능이 제한될 수 있습니다.")

    logger.info("\n📡 기본 서비스 초기화 중 (admin)...")

    try:
        get_or_create_user_services('admin')
        set_current_user('admin')
        get_or_create_orchestrator('admin')
        logger.info("✅ 기본 서비스 + Agent 초기화 완료!")
    except Exception as e:
        logger.warning(f"⚠️ 서비스 초기화 중 오류: {e}")


# ============================================================
# 메인 함수
# ============================================================

def main():
    mode = os.getenv('MCP_MODE', 'stdio').lower()

    try:
        initialize_default_services()
    except Exception as e:
        logger.warning(f"⚠️ 서비스 초기화 중 오류: {e}")

    if mode == 'sse':
        host = os.getenv('HOST', '0.0.0.0')
        port = MCP_PORT  # 9000

        logger.info("\n" + "=" * 70)
        logger.info("✅ Enterprise AI Multi-Agent Server 준비 완료!")
        logger.info("=" * 70)
        logger.info("🌐 Streamable HTTP 모드로 서버 시작")
        logger.info(f"   Host: {host}")
        logger.info(f"   MCP Port: {port}")
        logger.info(f"   Log API Port: {LOG_API_PORT}")
        logger.info("")
        logger.info("   📌 엔드포인트:")
        logger.info(f"      http://{host}:{port}/mcp?user_id=admin")
        logger.info(f"      http://{host}:{port}/mcp?user_id=sales")
        logger.info(f"      http://{host}:{port}/mcp?user_id=finance")
        logger.info("")
        logger.info("   🤖 Agent 도구 (Claude AI가 직접 Agent 선택):")
        logger.info("      run_email_agent     - Email Agent (이메일 처리)")
        logger.info("      run_crm_agent       - CRM Agent (Salesforce)")
        logger.info("      run_calendar_agent  - Calendar Agent (일정 관리)")
        logger.info("      run_cs_agent        - CS Agent (고객 서비스)")
        logger.info("      run_helpdesk_agent  - Helpdesk Agent (내부 문서)")
        logger.info("      run_report_agent    - Report Agent (로그/통계)")
        logger.info("")
        logger.info(f"   지원 사용자: {', '.join(SUPPORTED_USERS)}")
        logger.info("=" * 70 + "\n")

        # 로그 API 서버 (별도 쓰레드)
        import threading

        def run_log_api():
            try:
                from fastapi import FastAPI
                from fastapi.middleware.cors import CORSMiddleware
                import uvicorn

                log_app = FastAPI(title="Multi-Agent MCP Log API")
                log_app.include_router(log_api_router, prefix="/api")
                log_app.add_middleware(
                    CORSMiddleware,
                    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
                )

                @log_app.get("/")
                async def root():
                    return {
                        "service": "Multi-Agent MCP Log API",
                        "mode": "multi-agent",
                        "status": "running"
                    }

                logger.info(f"📡 로그 API 서버 시작 (port {LOG_API_PORT})")
                uvicorn.run(log_app, host="0.0.0.0", port=LOG_API_PORT, log_level="warning")
            except Exception as e:
                logger.error(f"❌ 로그 API 서버 실패: {e}")

        log_thread = threading.Thread(target=run_log_api, daemon=True)
        log_thread.start()
        logger.info(f"📡 로그 API: http://0.0.0.0:{LOG_API_PORT}/api/logs/upload")

        # FastMCP 서버 실행
        mcp.run(transport="http", host=host, port=port)

    else:
        # stdio 모드
        logger.info("\n" + "=" * 70)
        logger.info("✅ Enterprise AI Multi-Agent Server 준비 완료!")
        logger.info("📟 stdio 모드로 서버 시작")
        logger.info("=" * 70 + "\n")
        mcp.run()


if __name__ == "__main__":
    main()
