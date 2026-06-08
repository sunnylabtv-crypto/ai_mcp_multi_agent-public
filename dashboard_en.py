# dashboard_en.py
"""
Multi-Agent MCP Dashboard (English Version)
- Per-agent status & performance monitoring
- Client Type execution history
- Tool call log viewer
- Real-time statistics

Run: streamlit run dashboard_en.py --server.port 9502
"""
import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
import json

# ============================================================
# Configuration
# ============================================================

PROJECT_ROOT = Path(__file__).parent
# Multi-Agent DB path
# Priority: Docker → VM host (Docker volume mount) → Local dev
if Path("/app/data/multi/db").exists():
    DB_DIR = Path("/app/data/multi/db")
elif Path.home().joinpath("mcp_data/multi/db").exists():
    DB_DIR = Path.home() / "mcp_data" / "multi" / "db"
else:
    DB_DIR = PROJECT_ROOT / "data" / "db"
DB_PATH = DB_DIR / "mcp_logs.db"

# Agent definitions
AGENTS = {
    "email_agent": {"name": "Email Agent", "icon": "📧", "desc": "Gmail management"},
    "crm_agent": {"name": "CRM Agent", "icon": "💼", "desc": "Salesforce CRM"},
    "calendar_agent": {"name": "Calendar Agent", "icon": "📅", "desc": "Google Calendar"},
    "cs_agent": {"name": "CS Agent", "icon": "🎧", "desc": "Customer service (product docs)"},
    "helpdesk_agent": {"name": "Helpdesk Agent", "icon": "🏢", "desc": "Internal helpdesk (company docs)"},
    "report_agent": {"name": "Report Agent", "icon": "📊", "desc": "Log analytics & reporting"},
}

# Agent → Tool mapping
# MCP tool names (run_*_agent) + internal service tool names (local log compat)
AGENT_TOOLS = {
    "email_agent": ["run_email_agent", "fetch_unread_emails", "send_email_reply", "get_gmail_status", "analyze_email_with_ai", "generate_email_reply"],
    "crm_agent": ["run_crm_agent", "create_salesforce_lead", "verify_salesforce_lead", "get_salesforce_status"],
    "calendar_agent": ["run_calendar_agent", "add_calendar_event", "get_calendar_events", "update_calendar_event", "delete_calendar_event", "search_calendar_events", "get_calendar_status"],
    "cs_agent": ["run_cs_agent", "upload_product_document", "search_product_documents", "answer_customer_inquiry", "list_product_documents"],
    "helpdesk_agent": ["run_helpdesk_agent", "upload_internal_document", "search_internal_documents", "ask_helpdesk", "list_internal_documents", "delete_internal_document"],
    "report_agent": ["run_report_agent", "query_logs", "get_stats", "get_errors", "get_slow_tools"],
}

# ============================================================
# Two-axis classification
# ============================================================
# source      = Where the tool was executed     (remote: GCP server / local: PC)
# client_type = Client Type (entry point)      (claude_desktop / cursor / adk / mcp)

# client_type definitions
CLIENT_TYPES = {
    "claude_desktop": {"name": "Claude Desktop", "icon": "🟣", "color": "#7C3AED"},
    "cursor":         {"name": "Cursor IDE", "icon": "📝", "color": "#10B981"},
    "adk":            {"name": "Web/Mobile (ADK)", "icon": "🌐", "color": "#E74C3C"},
    "mcp":            {"name": "MCP (Default)", "icon": "🔌", "color": "#4A90D9"},
    "local":          {"name": "Local Agent", "icon": "💻", "color": "#2ECC71"},
}

# source definitions
SOURCE_TYPES = {
    "remote": {"name": "Remote (Server)", "icon": "☁️"},
    "local":  {"name": "Local (PC)", "icon": "💻"},
}

st.set_page_config(
    page_title="Multi-Agent Dashboard",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ============================================================
# Database functions
# ============================================================

@st.cache_resource
def get_connection():
    """SQLite connection (cached)"""
    return sqlite3.connect(str(DB_PATH), check_same_thread=False)


def get_user_ids(conn):
    """Get available user_id list from DB"""
    try:
        df = pd.read_sql_query("SELECT DISTINCT user_id FROM tool_logs WHERE user_id IS NOT NULL ORDER BY user_id", conn)
        return df['user_id'].tolist()
    except:
        return []


def query_logs(conn, start_time=None, end_time=None, tool_name=None,
               agent=None, user_id=None, success=None, keyword=None,
               source=None, client_type=None, limit=100):
    """Search logs"""
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
    if agent and agent != "All":
        tools = AGENT_TOOLS.get(agent, [])
        if tools:
            placeholders = ",".join(["?"] * len(tools))
            query += f" AND tool_name IN ({placeholders})"
            params.extend(tools)
    if user_id and user_id != "All":
        query += " AND user_id = ?"
        params.append(user_id)
    if success is not None and success != "All":
        query += " AND success = ?"
        params.append(1 if success == "Success" else 0)
    if source and source != "All":
        query += " AND source = ?"
        params.append(source)
    if client_type and client_type != "All":
        query += " AND client_type = ?"
        params.append(client_type)
    if keyword:
        query += " AND (parameters LIKE ? OR error_message LIKE ?)"
        params.extend([f"%{keyword}%"] * 2)

    query += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)

    return pd.read_sql_query(query, conn, params=params)


def get_stats(conn, start_time=None, end_time=None, user_id=None, source=None, client_type=None):
    """Get statistics"""
    where_clause = "WHERE 1=1"
    params = []

    if start_time:
        where_clause += " AND timestamp >= ?"
        params.append(start_time)
    if end_time:
        where_clause += " AND timestamp <= ?"
        params.append(end_time)
    if user_id and user_id != "All":
        where_clause += " AND user_id = ?"
        params.append(user_id)
    if source and source != "All":
        where_clause += " AND source = ?"
        params.append(source)
    if client_type and client_type != "All":
        where_clause += " AND client_type = ?"
        params.append(client_type)

    query = f"""
        SELECT
            COUNT(*) as total_calls,
            SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as success_count,
            SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as error_count,
            AVG(duration_ms) as avg_duration_ms
        FROM tool_logs {where_clause}
    """
    overall = pd.read_sql_query(query, conn, params=params).iloc[0].to_dict()

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
    """Get orchestrator (client_type) statistics"""
    where_clause = "WHERE 1=1"
    params = []

    if start_time:
        where_clause += " AND timestamp >= ?"
        params.append(start_time)
    if end_time:
        where_clause += " AND timestamp <= ?"
        params.append(end_time)
    if user_id and user_id != "All":
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
    """Get hourly call counts"""
    where_clause = "WHERE 1=1"
    params = []

    if start_time:
        where_clause += " AND timestamp >= ?"
        params.append(start_time)
    if end_time:
        where_clause += " AND timestamp <= ?"
        params.append(end_time)
    if user_id and user_id != "All":
        where_clause += " AND user_id = ?"
        params.append(user_id)
    if source and source != "All":
        where_clause += " AND source = ?"
        params.append(source)
    if client_type and client_type != "All":
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
    """Get per-agent statistics"""
    where_clause = "WHERE 1=1"
    params = []

    if start_time:
        where_clause += " AND timestamp >= ?"
        params.append(start_time)
    if end_time:
        where_clause += " AND timestamp <= ?"
        params.append(end_time)
    if user_id and user_id != "All":
        where_clause += " AND user_id = ?"
        params.append(user_id)
    if source and source != "All":
        where_clause += " AND source = ?"
        params.append(source)
    if client_type and client_type != "All":
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
# UI Components
# ============================================================

def render_summary_cards(overall):
    """Top summary metric cards"""
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            label="Total Calls",
            value=f"{int(overall['total_calls'] or 0):,}"
        )

    with col2:
        success_rate = 0
        if overall['total_calls'] and overall['total_calls'] > 0:
            success_rate = (overall['success_count'] or 0) / overall['total_calls'] * 100
        st.metric(
            label="Success Rate",
            value=f"{success_rate:.1f}%"
        )

    with col3:
        avg_duration = overall['avg_duration_ms'] or 0
        st.metric(
            label="Avg Response",
            value=f"{avg_duration:.0f}ms"
        )

    with col4:
        st.metric(
            label="Errors",
            value=f"{int(overall['error_count'] or 0):,}"
        )


def render_client_type_cards(client_stats):
    """Client Type (client_type) traffic cards"""
    if client_stats.empty:
        st.info("No orchestrator data available.")
        return

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
                <div style="font-size: 11px; color: gray;">Calls | Errors: {errors} | Avg: {avg_dur:.0f}ms</div>
            </div>
            """, unsafe_allow_html=True)


def render_agent_status(agent_stats):
    """Per-agent status cards"""
    cols = st.columns(len(AGENTS))

    for i, (agent_key, agent_info) in enumerate(AGENTS.items()):
        stats = agent_stats.get(agent_key, {"calls": 0, "success": 0, "errors": 0, "avg_duration": 0})
        calls = int(stats.get("calls") or 0)
        errors = int(stats.get("errors") or 0)
        avg_dur = stats.get("avg_duration") or 0

        with cols[i]:
            if calls == 0:
                status_color = "gray"
                status_text = "Idle"
            elif errors > 0:
                status_color = "orange"
                status_text = "Warning"
            else:
                status_color = "green"
                status_text = "Active"

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
                <div style="font-size: 12px;">Calls: <b>{calls}</b> | Errors: <b>{errors}</b></div>
                <div style="font-size: 11px; color: gray;">Avg: {avg_dur:.0f}ms</div>
            </div>
            """, unsafe_allow_html=True)


def render_chart(hourly_data):
    """Hourly call chart"""
    if hourly_data.empty:
        st.info("No data available.")
        return

    chart_data = hourly_data.set_index('hour')[['success', 'errors']]
    chart_data.columns = ['Success', 'Errors']
    st.bar_chart(chart_data)


def render_log_table(logs):
    """Log list table"""
    if logs.empty:
        st.info("No results found.")
        return

    display_df = logs.copy()

    # Status
    display_df['Status'] = display_df['success'].apply(lambda x: '✅' if x else '❌')

    # Agent mapping (run_*_agent → Agent name)
    _MCP_TO_AGENT = {}
    for agent_key in AGENTS:
        _MCP_TO_AGENT[f"run_{agent_key}"] = agent_key

    def get_agent_for_tool(tool_name):
        if tool_name in _MCP_TO_AGENT:
            info = AGENTS[_MCP_TO_AGENT[tool_name]]
            return f"{info['icon']} {info['name']}"
        for agent_key, tools in AGENT_TOOLS.items():
            if tool_name in tools:
                info = AGENTS[agent_key]
                return f"{info['icon']} {info['name']}"
        return "⚙️ System"

    display_df['Agent'] = display_df['tool_name'].apply(get_agent_for_tool)

    # Task summary (extract task param from run_*_agent calls)
    def get_task_summary(row):
        tool_name = row['tool_name']
        params_raw = row.get('parameters', '{}')

        if tool_name in _MCP_TO_AGENT:
            try:
                params = json.loads(params_raw) if isinstance(params_raw, str) else params_raw
                task = params.get('task', '') if isinstance(params, dict) else ''
                return task[:60] + '...' if len(task) > 60 else task if task else tool_name
            except Exception:
                return tool_name
        return tool_name

    display_df['Request'] = display_df.apply(get_task_summary, axis=1)

    # Client Type (client_type)
    def get_client_label(ct):
        info = CLIENT_TYPES.get(ct, {"icon": "❓", "name": ct or "N/A"})
        return f"{info['icon']} {info['name']}"

    if 'client_type' in display_df.columns:
        display_df['Client Type'] = display_df['client_type'].apply(get_client_label)
    else:
        display_df['Client Type'] = 'N/A'

    # User ID
    display_df['User'] = display_df['user_id'].fillna('N/A')

    # Time format
    display_df['Time'] = pd.to_datetime(display_df['timestamp']).dt.strftime('%m-%d %H:%M:%S')

    # Response time format
    display_df['Latency'] = display_df['duration_ms'].apply(
        lambda x: f"{x:.0f}ms" if pd.notna(x) else "-"
    )

    columns = ['Time', 'Client Type', 'User', 'Agent', 'Request', 'Status', 'Latency', 'error_message']

    st.dataframe(
        display_df[columns],
        use_container_width=True,
        height=400
    )


def render_tool_stats(by_tool):
    """Tool statistics table"""
    if by_tool.empty:
        st.info("No data available.")
        return

    by_tool['success_rate'] = (by_tool['success'] / by_tool['calls'] * 100).round(1)
    by_tool['avg_duration'] = by_tool['avg_duration'].round(0)

    display_df = by_tool.rename(columns={
        'tool_name': 'Tool',
        'calls': 'Calls',
        'success': 'Success',
        'success_rate': 'Rate (%)',
        'avg_duration': 'Avg (ms)'
    })

    st.dataframe(display_df, use_container_width=True)


# ============================================================
# Main App
# ============================================================

def main():
    st.title("Multi-Agent MCP Dashboard")
    st.markdown("Enterprise AI Assistant — Agent Monitoring & Log Analytics")

    # DB connection check
    if not DB_PATH.exists():
        st.warning(f"Log database not found: {DB_PATH}")
        st.info("Start the Multi-Agent server and make tool calls to generate logs.")

        st.subheader("Agent Configuration")
        for agent_key, agent_info in AGENTS.items():
            tools = AGENT_TOOLS.get(agent_key, [])
            st.markdown(f"**{agent_info['icon']} {agent_info['name']}** — {agent_info['desc']}  \nTools: `{'`, `'.join(tools)}`")
        return

    conn = get_connection()

    # ── Sidebar: Filters ──
    st.sidebar.header("Filters")

    # Time range
    time_range = st.sidebar.selectbox(
        "Time Range",
        ["Last 1 Hour", "Today", "Last 7 Days", "Last 30 Days", "All Time"]
    )

    now = datetime.utcnow()
    if time_range == "Last 1 Hour":
        start_time = (now - timedelta(hours=1)).isoformat() + "Z"
    elif time_range == "Today":
        start_time = now.replace(hour=0, minute=0, second=0).isoformat() + "Z"
    elif time_range == "Last 7 Days":
        start_time = (now - timedelta(days=7)).isoformat() + "Z"
    elif time_range == "Last 30 Days":
        start_time = (now - timedelta(days=30)).isoformat() + "Z"
    else:
        start_time = None

    end_time = None

    # User ID filter
    user_ids = get_user_ids(conn)
    user_id_options = ["All"] + user_ids
    user_id_filter = st.sidebar.selectbox("User ID", user_id_options)

    # Agent filter
    agent_options = ["All"] + list(AGENTS.keys())
    agent_filter = st.sidebar.selectbox(
        "Agent",
        agent_options,
        format_func=lambda x: "All" if x == "All" else f"{AGENTS[x]['icon']} {AGENTS[x]['name']}"
    )

    # Client Type (client_type) filter
    try:
        existing_clients = pd.read_sql_query(
            "SELECT DISTINCT COALESCE(client_type, 'mcp') as ct FROM tool_logs ORDER BY ct", conn
        )['ct'].tolist()
    except Exception:
        existing_clients = []

    client_type_filter = st.sidebar.selectbox(
        "Client Type",
        ["All"] + existing_clients,
        format_func=lambda x: "All" if x == "All" else (
            f"{CLIENT_TYPES[x]['icon']} {CLIENT_TYPES[x]['name']}"
            if x in CLIENT_TYPES
            else f"❓ {x}"
        )
    )

    # Source filter
    source_filter = st.sidebar.selectbox(
        "Execution Source",
        ["All", "remote", "local"],
        format_func=lambda x: "All" if x == "All" else f"{SOURCE_TYPES.get(x, {}).get('icon', '❓')} {SOURCE_TYPES.get(x, {}).get('name', x)}"
    )

    # Status filter
    success_filter = st.sidebar.selectbox(
        "Status",
        ["All", "Success", "Failed"]
    )

    # Tool name filter
    tool_name = st.sidebar.text_input("Tool Name (partial match)")

    # Keyword search
    keyword = st.sidebar.text_input("Keyword Search")

    # Result limit
    limit = st.sidebar.slider("Display Limit", 10, 500, 100)

    # ── Main: Dashboard ──

    tab1, tab2, tab3 = st.tabs(["Overview", "Agent Status", "Log Details"])

    with tab1:
        overall, by_tool = get_stats(conn, start_time, end_time, user_id_filter, source_filter, client_type_filter)

        st.subheader("Summary")
        render_summary_cards(overall)

        # Client Type traffic (only when client_type filter is "All")
        if client_type_filter == "All":
            st.divider()
            st.subheader("Traffic by Client Type")
            client_stats = get_client_type_stats(conn, start_time, end_time, user_id_filter)
            render_client_type_cards(client_stats)

        st.divider()

        col1, col2 = st.columns([2, 1])

        with col1:
            st.subheader("Hourly Calls")
            hourly_data = get_hourly_calls(conn, start_time, end_time, user_id_filter, source_filter, client_type_filter)
            render_chart(hourly_data)

        with col2:
            st.subheader("Tool Statistics")
            render_tool_stats(by_tool)

    with tab2:
        st.subheader("Agent Status")
        agent_stats = get_agent_stats(conn, start_time, end_time, user_id_filter, source_filter, client_type_filter)
        render_agent_status(agent_stats)

        st.divider()

        st.subheader("Agent Tool Call Breakdown")
        for agent_key, agent_info in AGENTS.items():
            stats = agent_stats.get(agent_key, {"calls": 0, "success": 0, "errors": 0})
            calls = int(stats.get("calls") or 0)
            if calls > 0:
                with st.expander(f"{agent_info['icon']} {agent_info['name']} — {calls} calls"):
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
                            'tool_name': 'Tool', 'calls': 'Calls', 'success': 'Success', 'avg_ms': 'Avg (ms)'
                        }), use_container_width=True)

    with tab3:
        st.subheader("Log List")

        logs = query_logs(
            conn,
            start_time=start_time,
            end_time=end_time,
            tool_name=tool_name if tool_name else None,
            agent=agent_filter if agent_filter != "All" else None,
            user_id=user_id_filter if user_id_filter != "All" else None,
            success=success_filter if success_filter != "All" else None,
            source=source_filter if source_filter != "All" else None,
            client_type=client_type_filter if client_type_filter != "All" else None,
            keyword=keyword if keyword else None,
            limit=limit
        )

        render_log_table(logs)

        # Log detail view
        if not logs.empty:
            st.subheader("Detail View")
            selected_id = st.selectbox(
                "Select Log",
                logs['id'].tolist(),
                format_func=lambda x: f"#{x} — {logs[logs['id']==x]['tool_name'].values[0]} ({logs[logs['id']==x]['timestamp'].values[0][:19]})"
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
                    st.write("**Parameters:**")
                    try:
                        params = json.loads(selected_log['parameters']) if selected_log['parameters'] else {}
                        st.json(params)
                    except:
                        st.code(selected_log['parameters'])

                    if selected_log['error_message']:
                        st.error(f"**Error:** {selected_log['error_message']}")

                    if selected_log['result_summary']:
                        st.info(f"**Result:** {selected_log['result_summary']}")

    # Footer
    st.divider()
    st.caption(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | Multi-Agent MCP (:9000) + ADK (:7001) + Log API (:9001)")

    # Auto-refresh
    if st.sidebar.checkbox("Auto-refresh (30s)", value=False):
        import time
        time.sleep(30)
        st.rerun()


if __name__ == "__main__":
    main()
