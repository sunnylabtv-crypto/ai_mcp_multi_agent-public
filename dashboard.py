# dashboard.py
"""
Multi-Agent MCP 통합 대시보드 (Streamlit)
- Agent별 상태 및 성능 모니터링
- Client Type 실행 이력
- 도구 호출 로그 조회
- 실시간 통계

실행: streamlit run dashboard.py --server.port 9501
"""
import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
import json

# ============================================================
# 설정
# ============================================================

PROJECT_ROOT = Path(__file__).parent
# Multi-Agent 전용 DB 경로
# 우선순위: Docker 내부 → VM 호스트 (Docker 볼륨 마운트) → 로컬 개발
if Path("/app/data/multi/db").exists():
    DB_DIR = Path("/app/data/multi/db")
elif Path.home().joinpath("mcp_data/multi/db").exists():
    DB_DIR = Path.home() / "mcp_data" / "multi" / "db"
else:
    DB_DIR = PROJECT_ROOT / "data" / "db"
DB_PATH = DB_DIR / "mcp_logs.db"

# Agent 정의
AGENTS = {
    "email_agent": {"name": "Email Agent", "icon": "📧", "desc": "Gmail 이메일 관리"},
    "crm_agent": {"name": "CRM Agent", "icon": "💼", "desc": "Salesforce CRM 관리"},
    "calendar_agent": {"name": "Calendar Agent", "icon": "📅", "desc": "Google Calendar 관리"},
    "cs_agent": {"name": "CS Agent", "icon": "🎧", "desc": "고객 서비스 (제품 문서)"},
    "helpdesk_agent": {"name": "Helpdesk Agent", "icon": "🏢", "desc": "내부 헬프데스크 (사내 문서)"},
    "report_agent": {"name": "Report Agent", "icon": "📊", "desc": "로그/통계 분석"},
}

# Agent → 도구 매핑
# MCP 도구명(run_*_agent) + 내부 서비스 도구명(local 로그 호환)
AGENT_TOOLS = {
    "email_agent": ["run_email_agent", "fetch_unread_emails", "send_email_reply", "get_gmail_status", "analyze_email_with_ai", "generate_email_reply"],
    "crm_agent": ["run_crm_agent", "create_salesforce_lead", "verify_salesforce_lead", "get_salesforce_status"],
    "calendar_agent": ["run_calendar_agent", "add_calendar_event", "get_calendar_events", "update_calendar_event", "delete_calendar_event", "search_calendar_events", "get_calendar_status"],
    "cs_agent": ["run_cs_agent", "upload_product_document", "search_product_documents", "answer_customer_inquiry", "list_product_documents"],
    "helpdesk_agent": ["run_helpdesk_agent", "upload_internal_document", "search_internal_documents", "ask_helpdesk", "list_internal_documents", "delete_internal_document"],
    "report_agent": ["run_report_agent", "query_logs", "get_stats", "get_errors", "get_slow_tools"],
}

# ============================================================
# 2축 분류 체계
# ============================================================
# source     = 도구 실행 위치     (remote: GCP 서버 / local: PC 로컬)
# client_type = 호출 진입점(클라이언트)  (claude_desktop / cursor / adk / mcp)

# client_type 정의
CLIENT_TYPES = {
    "claude_desktop": {"name": "Claude Desktop", "icon": "🟣", "color": "#7C3AED"},
    "cursor":         {"name": "Cursor IDE", "icon": "📝", "color": "#10B981"},
    "adk":            {"name": "Web/Mobile (ADK)", "icon": "🌐", "color": "#E74C3C"},
    "mcp":            {"name": "MCP (기본)", "icon": "🔌", "color": "#4A90D9"},
    "local":          {"name": "Local Agent", "icon": "💻", "color": "#2ECC71"},
}

# source 정의
SOURCE_TYPES = {
    "remote": {"name": "Remote (서버)", "icon": "☁️"},
    "local":  {"name": "Local (PC)", "icon": "💻"},
}

st.set_page_config(
    page_title="Multi-Agent 대시보드",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ============================================================
# 데이터베이스 함수
# ============================================================

@st.cache_resource
def get_connection():
    """SQLite 연결 (캐시)"""
    return sqlite3.connect(str(DB_PATH), check_same_thread=False)


def get_user_ids(conn):
    """DB에서 사용 가능한 user_id 목록 조회"""
    try:
        df = pd.read_sql_query("SELECT DISTINCT user_id FROM tool_logs WHERE user_id IS NOT NULL ORDER BY user_id", conn)
        return df['user_id'].tolist()
    except:
        return []


def query_logs(conn, start_time=None, end_time=None, tool_name=None,
               agent=None, user_id=None, success=None, keyword=None,
               source=None, client_type=None, limit=100):
    """로그 검색"""
    query = "SELECT * FROM tool_logs WHERE 1=1"
    params = []

    if start_time:
        query += " AND timestamp >= ?"
        params.append(start_time)
    if end_time:
        query += " AND timestamp <= ?"
        params.append(end_time)
    if tool_name:
        query += " AND tool_name LIKE ?"
        params.append(f"%{tool_name}%")
    if agent and agent != "전체":
        tools = AGENT_TOOLS.get(agent, [])
        if tools:
            placeholders = ",".join(["?"] * len(tools))
            query += f" AND tool_name IN ({placeholders})"
            params.extend(tools)
    if user_id and user_id != "전체":
        query += " AND user_id = ?"
        params.append(user_id)
    if success is not None and success != "전체":
        query += " AND success = ?"
        params.append(1 if success == "성공" else 0)
    if source and source != "전체":
        query += " AND source = ?"
        params.append(source)
    if client_type and client_type != "전체":
        query += " AND client_type = ?"
        params.append(client_type)
    if keyword:
        query += " AND (parameters LIKE ? OR error_message LIKE ?)"
        params.extend([f"%{keyword}%"] * 2)

    query += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)

    return pd.read_sql_query(query, conn, params=params)


def get_stats(conn, start_time=None, end_time=None, user_id=None, source=None, client_type=None):
    """통계 조회"""
    where_clause = "WHERE 1=1"
    params = []

    if start_time:
        where_clause += " AND timestamp >= ?"
        params.append(start_time)
    if end_time:
        where_clause += " AND timestamp <= ?"
        params.append(end_time)
    if user_id and user_id != "전체":
        where_clause += " AND user_id = ?"
        params.append(user_id)
    if source and source != "전체":
        where_clause += " AND source = ?"
        params.append(source)
    if client_type and client_type != "전체":
        where_clause += " AND client_type = ?"
        params.append(client_type)

    # 전체 통계
    query = f"""
        SELECT
            COUNT(*) as total_calls,
            SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as success_count,
            SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as error_count,
            AVG(duration_ms) as avg_duration_ms
        FROM tool_logs {where_clause}
    """
    overall = pd.read_sql_query(query, conn, params=params).iloc[0].to_dict()

    # 도구별 통계
    query = f"""
        SELECT
            tool_name,
            COUNT(*) as calls,
            SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as success,
            AVG(duration_ms) as avg_duration
        FROM tool_logs {where_clause}
        GROUP BY tool_name
        ORDER BY calls DESC
    """
    by_tool = pd.read_sql_query(query, conn, params=params)

    return overall, by_tool


def get_client_type_stats(conn, start_time=None, end_time=None, user_id=None):
    """클라이언트(client_type)별 통계 조회"""
    where_clause = "WHERE 1=1"
    params = []

    if start_time:
        where_clause += " AND timestamp >= ?"
        params.append(start_time)
    if end_time:
        where_clause += " AND timestamp <= ?"
        params.append(end_time)
    if user_id and user_id != "전체":
        where_clause += " AND user_id = ?"
        params.append(user_id)

    query = f"""
        SELECT
            COALESCE(client_type, 'mcp') as client_type,
            COUNT(*) as calls,
            SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as success,
            SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as errors,
            AVG(duration_ms) as avg_duration
        FROM tool_logs {where_clause}
        GROUP BY client_type
        ORDER BY calls DESC
    """
    return pd.read_sql_query(query, conn, params=params)


def get_hourly_calls(conn, start_time=None, end_time=None, user_id=None, source=None, client_type=None):
    """시간대별 호출 수"""
    where_clause = "WHERE 1=1"
    params = []

    if start_time:
        where_clause += " AND timestamp >= ?"
        params.append(start_time)
    if end_time:
        where_clause += " AND timestamp <= ?"
        params.append(end_time)
    if user_id and user_id != "전체":
        where_clause += " AND user_id = ?"
        params.append(user_id)
    if source and source != "전체":
        where_clause += " AND source = ?"
        params.append(source)
    if client_type and client_type != "전체":
        where_clause += " AND client_type = ?"
        params.append(client_type)

    query = f"""
        SELECT
            strftime('%Y-%m-%d %H:00', timestamp) as hour,
            COUNT(*) as calls,
            SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as success,
            SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as errors
        FROM tool_logs {where_clause}
        GROUP BY hour
        ORDER BY hour
    """
    return pd.read_sql_query(query, conn, params=params)


def get_agent_stats(conn, start_time=None, end_time=None, user_id=None, source=None, client_type=None):
    """Agent별 통계"""
    where_clause = "WHERE 1=1"
    params = []

    if start_time:
        where_clause += " AND timestamp >= ?"
        params.append(start_time)
    if end_time:
        where_clause += " AND timestamp <= ?"
        params.append(end_time)
    if user_id and user_id != "전체":
        where_clause += " AND user_id = ?"
        params.append(user_id)
    if source and source != "전체":
        where_clause += " AND source = ?"
        params.append(source)
    if client_type and client_type != "전체":
        where_clause += " AND client_type = ?"
        params.append(client_type)

    results = {}
    for agent_key, tools in AGENT_TOOLS.items():
        if not tools:
            continue
        placeholders = ",".join(["?"] * len(tools))
        query = f"""
            SELECT
                COUNT(*) as calls,
                SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as success,
                SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as errors,
                AVG(duration_ms) as avg_duration
            FROM tool_logs
            {where_clause} AND tool_name IN ({placeholders})
        """
        agent_params = params + tools
        row = pd.read_sql_query(query, conn, params=agent_params).iloc[0].to_dict()
        results[agent_key] = row

    return results


# ============================================================
# UI 컴포넌트
# ============================================================

def render_summary_cards(overall):
    """상단 요약 카드"""
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            label="총 호출",
            value=f"{int(overall['total_calls'] or 0):,}"
        )

    with col2:
        success_rate = 0
        if overall['total_calls'] and overall['total_calls'] > 0:
            success_rate = (overall['success_count'] or 0) / overall['total_calls'] * 100
        st.metric(
            label="성공률",
            value=f"{success_rate:.1f}%"
        )

    with col3:
        avg_duration = overall['avg_duration_ms'] or 0
        st.metric(
            label="평균 응답",
            value=f"{avg_duration:.0f}ms"
        )

    with col4:
        st.metric(
            label="에러 수",
            value=f"{int(overall['error_count'] or 0):,}"
        )


def render_client_type_cards(client_stats):
    """클라이언트(client_type)별 트래픽 카드"""
    if client_stats.empty:
        st.info("클라이언트별 데이터가 없습니다.")
        return

    # DB에 실제 존재하는 client_type만 필터링
    active = []
    for _, row in client_stats.iterrows():
        ct = row['client_type'] or 'mcp'
        info = CLIENT_TYPES.get(ct, {"name": ct, "icon": "❓", "color": "#999"})
        active.append((ct, info, row))

    cols = st.columns(len(active))
    for i, (ct_key, ct_info, row) in enumerate(active):
        calls = int(row['calls'])
        errors = int(row['errors'])
        avg_dur = row['avg_duration'] or 0

        with cols[i]:
            st.markdown(f"""
            <div style="
                border: 1px solid #ddd;
                border-radius: 8px;
                padding: 14px;
                text-align: center;
                border-top: 4px solid {ct_info['color']};
                background: white;
            ">
                <div style="font-size: 22px;">{ct_info['icon']}</div>
                <div style="font-weight: bold; font-size: 13px;">{ct_info['name']}</div>
                <hr style="margin: 8px 0;">
                <div style="font-size: 20px; font-weight: bold; color: {ct_info['color']};">{calls:,}</div>
                <div style="font-size: 11px; color: gray;">호출 | 에러: {errors} | 평균: {avg_dur:.0f}ms</div>
            </div>
            """, unsafe_allow_html=True)


def render_agent_status(agent_stats):
    """Agent별 상태 카드"""
    cols = st.columns(len(AGENTS))

    for i, (agent_key, agent_info) in enumerate(AGENTS.items()):
        stats = agent_stats.get(agent_key, {"calls": 0, "success": 0, "errors": 0, "avg_duration": 0})
        calls = int(stats.get("calls") or 0)
        errors = int(stats.get("errors") or 0)
        avg_dur = stats.get("avg_duration") or 0

        with cols[i]:
            # 상태 색상
            if calls == 0:
                status_color = "gray"
                status_text = "대기"
            elif errors > 0:
                status_color = "orange"
                status_text = "경고"
            else:
                status_color = "green"
                status_text = "정상"

            st.markdown(f"""
            <div style="
                border: 1px solid #ddd;
                border-radius: 8px;
                padding: 12px;
                text-align: center;
                border-left: 4px solid {status_color};
            ">
                <div style="font-size: 24px;">{agent_info['icon']}</div>
                <div style="font-weight: bold; font-size: 13px;">{agent_info['name']}</div>
                <div style="color: gray; font-size: 11px;">{agent_info['desc']}</div>
                <hr style="margin: 8px 0;">
                <div style="font-size: 12px;">호출: <b>{calls}</b> | 에러: <b>{errors}</b></div>
                <div style="font-size: 11px; color: gray;">평균: {avg_dur:.0f}ms</div>
            </div>
            """, unsafe_allow_html=True)


def render_chart(hourly_data):
    """시간대별 호출 차트"""
    if hourly_data.empty:
        st.info("데이터가 없습니다.")
        return

    chart_data = hourly_data.set_index('hour')[['success', 'errors']]
    chart_data.columns = ['성공', '에러']
    st.bar_chart(chart_data)


def render_log_table(logs):
    """로그 테이블"""
    if logs.empty:
        st.info("검색 결과가 없습니다.")
        return

    display_df = logs.copy()

    # 상태 표시
    display_df['상태'] = display_df['success'].apply(lambda x: '✅' if x else '❌')

    # Agent 매핑 (run_*_agent → Agent명)
    # MCP 도구명 → Agent 키 역매핑
    _MCP_TO_AGENT = {}
    for agent_key in AGENTS:
        _MCP_TO_AGENT[f"run_{agent_key}"] = agent_key

    def get_agent_for_tool(tool_name):
        # 1) run_*_agent 직접 매핑
        if tool_name in _MCP_TO_AGENT:
            info = AGENTS[_MCP_TO_AGENT[tool_name]]
            return f"{info['icon']} {info['name']}"
        # 2) 내부 도구명으로 매핑 (local 로그 호환)
        for agent_key, tools in AGENT_TOOLS.items():
            if tool_name in tools:
                info = AGENTS[agent_key]
                return f"{info['icon']} {info['name']}"
        return "⚙️ 시스템"

    display_df['Agent'] = display_df['tool_name'].apply(get_agent_for_tool)

    # 요청 내용 (run_*_agent의 task 파라미터 추출, 내부 도구는 도구명 표시)
    def get_task_summary(row):
        tool_name = row['tool_name']
        params_raw = row.get('parameters', '{}')

        # run_*_agent인 경우 → task 파라미터에서 요청 내용 추출
        if tool_name in _MCP_TO_AGENT:
            try:
                params = json.loads(params_raw) if isinstance(params_raw, str) else params_raw
                task = params.get('task', '') if isinstance(params, dict) else ''
                return task[:60] + '...' if len(task) > 60 else task if task else tool_name
            except Exception:
                return tool_name
        # 시스템 도구 또는 내부 도구 → 도구명 그대로
        return tool_name

    display_df['요청내용'] = display_df.apply(get_task_summary, axis=1)

    # 클라이언트 (client_type)
    def get_client_label(ct):
        info = CLIENT_TYPES.get(ct, {"icon": "❓", "name": ct or "N/A"})
        return f"{info['icon']} {info['name']}"

    if 'client_type' in display_df.columns:
        display_df['클라이언트'] = display_df['client_type'].apply(get_client_label)
    else:
        display_df['클라이언트'] = 'N/A'

    # User ID
    display_df['User'] = display_df['user_id'].fillna('N/A')

    # 시간 포맷
    display_df['시간'] = pd.to_datetime(display_df['timestamp']).dt.strftime('%m-%d %H:%M:%S')

    # 응답시간 포맷
    display_df['응답시간'] = display_df['duration_ms'].apply(
        lambda x: f"{x:.0f}ms" if pd.notna(x) else "-"
    )

    # 표시할 컬럼
    columns = ['시간', '클라이언트', 'User', 'Agent', '요청내용', '상태', '응답시간', 'error_message']

    st.dataframe(
        display_df[columns],
        use_container_width=True,
        height=400
    )


def render_tool_stats(by_tool):
    """도구별 통계"""
    if by_tool.empty:
        st.info("데이터가 없습니다.")
        return

    by_tool['success_rate'] = (by_tool['success'] / by_tool['calls'] * 100).round(1)
    by_tool['avg_duration'] = by_tool['avg_duration'].round(0)

    display_df = by_tool.rename(columns={
        'tool_name': '도구',
        'calls': '호출 수',
        'success': '성공',
        'success_rate': '성공률(%)',
        'avg_duration': '평균 응답(ms)'
    })

    st.dataframe(display_df, use_container_width=True)


# ============================================================
# 메인 앱
# ============================================================

def main():
    st.title("Multi-Agent MCP 대시보드")
    st.markdown("Enterprise AI Assistant - Agent별 모니터링 및 로그 분석")

    # DB 연결 확인
    if not DB_PATH.exists():
        st.warning(f"로그 데이터베이스를 찾을 수 없습니다: {DB_PATH}")
        st.info("Multi-Agent 서버를 실행하고 도구를 호출하면 로그가 생성됩니다.")

        # Agent 구성도만 표시
        st.subheader("Agent 구성")
        for agent_key, agent_info in AGENTS.items():
            tools = AGENT_TOOLS.get(agent_key, [])
            st.markdown(f"**{agent_info['icon']} {agent_info['name']}** - {agent_info['desc']}  \n도구: `{'`, `'.join(tools)}`")
        return

    conn = get_connection()

    # ── 사이드바: 필터 ──
    st.sidebar.header("필터")

    # 시간 범위
    time_range = st.sidebar.selectbox(
        "시간 범위",
        ["최근 1시간", "오늘", "최근 7일", "최근 30일", "전체"]
    )

    now = datetime.utcnow()
    if time_range == "최근 1시간":
        start_time = (now - timedelta(hours=1)).isoformat() + "Z"
    elif time_range == "오늘":
        start_time = now.replace(hour=0, minute=0, second=0).isoformat() + "Z"
    elif time_range == "최근 7일":
        start_time = (now - timedelta(days=7)).isoformat() + "Z"
    elif time_range == "최근 30일":
        start_time = (now - timedelta(days=30)).isoformat() + "Z"
    else:
        start_time = None

    end_time = None

    # User ID 필터
    user_ids = get_user_ids(conn)
    user_id_options = ["전체"] + user_ids
    user_id_filter = st.sidebar.selectbox("User ID", user_id_options)

    # Agent 필터
    agent_options = ["전체"] + list(AGENTS.keys())
    agent_filter = st.sidebar.selectbox(
        "Agent",
        agent_options,
        format_func=lambda x: "전체" if x == "전체" else f"{AGENTS[x]['icon']} {AGENTS[x]['name']}"
    )

    # 클라이언트(client_type) 필터
    try:
        existing_clients = pd.read_sql_query(
            "SELECT DISTINCT COALESCE(client_type, 'mcp') as ct FROM tool_logs ORDER BY ct", conn
        )['ct'].tolist()
    except Exception:
        existing_clients = []

    client_type_filter = st.sidebar.selectbox(
        "클라이언트",
        ["전체"] + existing_clients,
        format_func=lambda x: "전체" if x == "전체" else (
            f"{CLIENT_TYPES[x]['icon']} {CLIENT_TYPES[x]['name']}"
            if x in CLIENT_TYPES
            else f"❓ {x}"
        )
    )

    # 실행 위치(source) 필터
    source_filter = st.sidebar.selectbox(
        "실행 위치",
        ["전체", "remote", "local"],
        format_func=lambda x: "전체" if x == "전체" else f"{SOURCE_TYPES.get(x, {}).get('icon', '❓')} {SOURCE_TYPES.get(x, {}).get('name', x)}"
    )

    # 상태 필터
    success_filter = st.sidebar.selectbox(
        "상태",
        ["전체", "성공", "실패"]
    )

    # 도구 필터
    tool_name = st.sidebar.text_input("도구 이름 (부분 일치)")

    # 키워드 검색
    keyword = st.sidebar.text_input("키워드 검색")

    # 결과 수
    limit = st.sidebar.slider("표시 개수", 10, 500, 100)

    # ── 메인: 대시보드 ──

    # 탭
    tab1, tab2, tab3 = st.tabs(["개요", "Agent 상태", "로그 상세"])

    with tab1:
        # 통계
        overall, by_tool = get_stats(conn, start_time, end_time, user_id_filter, source_filter, client_type_filter)

        st.subheader("요약")
        render_summary_cards(overall)

        # 클라이언트별 트래픽 (client_type 필터가 "전체"일 때만 표시)
        if client_type_filter == "전체":
            st.divider()
            st.subheader("클라이언트별 트래픽")
            client_stats = get_client_type_stats(conn, start_time, end_time, user_id_filter)
            render_client_type_cards(client_stats)

        st.divider()

        col1, col2 = st.columns([2, 1])

        with col1:
            st.subheader("시간대별 호출")
            hourly_data = get_hourly_calls(conn, start_time, end_time, user_id_filter, source_filter, client_type_filter)
            render_chart(hourly_data)

        with col2:
            st.subheader("도구별 통계")
            render_tool_stats(by_tool)

    with tab2:
        st.subheader("Agent별 상태")
        agent_stats = get_agent_stats(conn, start_time, end_time, user_id_filter, source_filter, client_type_filter)
        render_agent_status(agent_stats)

        st.divider()

        # Agent별 상세 통계
        st.subheader("Agent별 도구 호출 현황")
        for agent_key, agent_info in AGENTS.items():
            stats = agent_stats.get(agent_key, {"calls": 0, "success": 0, "errors": 0})
            calls = int(stats.get("calls") or 0)
            if calls > 0:
                with st.expander(f"{agent_info['icon']} {agent_info['name']} - {calls}건"):
                    tools = AGENT_TOOLS.get(agent_key, [])
                    placeholders = ",".join(["?"] * len(tools))
                    where = f"WHERE tool_name IN ({placeholders})"
                    if start_time:
                        where += " AND timestamp >= ?"
                        tool_params = tools + [start_time]
                    else:
                        tool_params = tools

                    query = f"""
                        SELECT tool_name, COUNT(*) as calls,
                               SUM(CASE WHEN success=1 THEN 1 ELSE 0 END) as success,
                               AVG(duration_ms) as avg_ms
                        FROM tool_logs {where}
                        GROUP BY tool_name ORDER BY calls DESC
                    """
                    df = pd.read_sql_query(query, conn, params=tool_params)
                    if not df.empty:
                        df['avg_ms'] = df['avg_ms'].round(0)
                        st.dataframe(df.rename(columns={
                            'tool_name': '도구', 'calls': '호출', 'success': '성공', 'avg_ms': '평균(ms)'
                        }), use_container_width=True)

    with tab3:
        st.subheader("로그 목록")

        logs = query_logs(
            conn,
            start_time=start_time,
            end_time=end_time,
            tool_name=tool_name if tool_name else None,
            agent=agent_filter if agent_filter != "전체" else None,
            user_id=user_id_filter if user_id_filter != "전체" else None,
            success=success_filter if success_filter != "전체" else None,
            source=source_filter if source_filter != "전체" else None,
            client_type=client_type_filter if client_type_filter != "전체" else None,
            keyword=keyword if keyword else None,
            limit=limit
        )

        render_log_table(logs)

        # 로그 상세
        if not logs.empty:
            st.subheader("상세 보기")
            selected_id = st.selectbox(
                "로그 선택",
                logs['id'].tolist(),
                format_func=lambda x: f"#{x} - {logs[logs['id']==x]['tool_name'].values[0]} ({logs[logs['id']==x]['timestamp'].values[0][:19]})"
            )

            if selected_id:
                selected_log = logs[logs['id'] == selected_id].iloc[0]

                col1, col2 = st.columns(2)

                with col1:
                    st.json({
                        "id": int(selected_log['id']),
                        "timestamp": selected_log['timestamp'],
                        "user_id": selected_log.get('user_id', 'N/A'),
                        "tool_name": selected_log['tool_name'],
                        "success": bool(selected_log['success']),
                        "duration_ms": selected_log['duration_ms']
                    })

                with col2:
                    st.write("**파라미터:**")
                    try:
                        params = json.loads(selected_log['parameters']) if selected_log['parameters'] else {}
                        st.json(params)
                    except:
                        st.code(selected_log['parameters'])

                    if selected_log['error_message']:
                        st.error(f"**에러:** {selected_log['error_message']}")

                    if selected_log['result_summary']:
                        st.info(f"**결과:** {selected_log['result_summary']}")

    # Footer
    st.divider()
    st.caption(f"마지막 업데이트: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | Multi-Agent MCP (:9000) + ADK (:7001) + Log API (:9001)")

    # 자동 새로고침
    if st.sidebar.checkbox("자동 새로고침 (30초)", value=False):
        import time
        time.sleep(30)
        st.rerun()


if __name__ == "__main__":
    main()
