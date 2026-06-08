# mcp_server/agents/base_agent.py
"""
BaseAgent: 모든 전문 Agent의 기본 클래스
- LLM을 사용하여 자신의 도구(tools) 범위 내에서 판단/실행
- 실행 결과와 트레이싱 정보를 반환
"""
import time
import json
import sys
import asyncio
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime

# Agent 전체 실행 제한 (mcp-remote 60초 timeout 대비 여유)
AGENT_RUN_TIMEOUT = 45  # seconds


@dataclass
class AgentResult:
    """Agent 실행 결과"""
    agent_name: str
    success: bool
    result: Any = None
    error: Optional[str] = None
    steps: List[Dict] = field(default_factory=list)  # 실행 단계 추적
    duration_ms: float = 0
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return {
            'agent_name': self.agent_name,
            'success': self.success,
            'result': self.result,
            'error': self.error,
            'steps': self.steps,
            'duration_ms': self.duration_ms,
            'timestamp': self.timestamp,
        }


class BaseAgent:
    """전문 Agent 기본 클래스"""

    def __init__(self, name: str, description: str, llm_config: dict):
        self.name = name
        self.description = description
        self.llm_config = llm_config
        self._tools = {}  # {tool_name: callable}
        self._tool_descriptions = {}  # {tool_name: description}

    def register_tool(self, name: str, func: callable, description: str = ""):
        """Agent에 도구 등록"""
        self._tools[name] = func
        self._tool_descriptions[name] = description
        print(f"[{self.name}] Tool registered: {name}", file=sys.stderr)

    def get_available_tools(self) -> List[str]:
        """사용 가능한 도구 목록"""
        return list(self._tools.keys())

    def get_tools_description(self) -> str:
        """LLM에 전달할 도구 설명 문자열"""
        lines = []
        for name, desc in self._tool_descriptions.items():
            lines.append(f"- {name}: {desc}")
        return "\n".join(lines)

    async def execute_tool(self, tool_name: str, **kwargs) -> Dict:
        """도구 실행 (에러 핸들링 포함)"""
        if tool_name not in self._tools:
            return {
                'success': False,
                'error': f"Unknown tool: {tool_name}. Available: {list(self._tools.keys())}"
            }

        start_time = time.time()
        try:
            result = await self._tools[tool_name](**kwargs)
            duration_ms = (time.time() - start_time) * 1000
            return {
                'success': True,
                'tool': tool_name,
                'result': result,
                'duration_ms': round(duration_ms, 2),
            }
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            print(f"[{self.name}] Tool error ({tool_name}): {e}", file=sys.stderr)
            return {
                'success': False,
                'tool': tool_name,
                'error': str(e),
                'duration_ms': round(duration_ms, 2),
            }

    async def think(self, task: str, context: dict = None) -> dict:
        """
        LLM을 사용하여 작업 계획 수립
        - 어떤 도구를 어떤 순서로 실행할지 결정
        Returns: {'plan': [...], 'reasoning': '...'}
        """
        from ..services.openai_service import generate_text_with_system

        tools_desc = self.get_tools_description()
        system_prompt = f"""당신은 '{self.name}' 전문 에이전트입니다.
역할: {self.description}

사용 가능한 도구:
{tools_desc}

사용자의 요청을 분석하여, 어떤 도구를 어떤 순서로 실행해야 하는지 JSON으로 계획을 세우세요.

반드시 아래 형식으로만 응답하세요:
{{
  "reasoning": "작업 분석 설명",
  "plan": [
    {{"tool": "도구이름", "params": {{"param1": "value1"}}, "description": "이 단계의 목적"}}
  ]
}}

도구 실행이 필요 없는 경우:
{{
  "reasoning": "설명",
  "plan": [],
  "direct_answer": "직접 답변 내용"
}}"""

        user_prompt = f"요청: {task}"
        if context:
            user_prompt += f"\n추가 정보: {json.dumps(context, ensure_ascii=False)}"

        try:
            # generate_text_with_system은 동기 함수 → asyncio.to_thread로 비동기 실행
            response = await asyncio.to_thread(
                generate_text_with_system,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=self.llm_config.get('temperature', 0.3),
                max_tokens=self.llm_config.get('max_tokens', 2000),
            )

            # JSON 파싱 시도
            cleaned = response.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            if cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]

            plan = json.loads(cleaned.strip())
            return plan

        except json.JSONDecodeError as e:
            print(f"[{self.name}] LLM response parse error: {e}", file=sys.stderr)
            return {
                'reasoning': f'LLM 응답 파싱 실패: {response[:200]}',
                'plan': [],
                'direct_answer': response,
            }
        except Exception as e:
            print(f"[{self.name}] Think error: {e}", file=sys.stderr)
            return {
                'reasoning': f'오류 발생: {str(e)}',
                'plan': [],
            }

    async def run(self, task: str, context: dict = None) -> AgentResult:
        """
        Agent 메인 실행 루프:
        1. think() → 계획 수립
        2. 계획에 따라 도구 순차 실행
        3. 결과 종합하여 반환

        전체 실행은 AGENT_RUN_TIMEOUT(45초) 내에 완료되어야 함
        (mcp-remote 60초 timeout 대비)
        """
        start_time = time.time()

        try:
            return await asyncio.wait_for(
                self._run_internal(task, context, start_time),
                timeout=AGENT_RUN_TIMEOUT,
            )
        except asyncio.TimeoutError:
            duration_ms = (time.time() - start_time) * 1000
            print(f"[{self.name}] ⏰ TIMEOUT after {duration_ms:.0f}ms (limit: {AGENT_RUN_TIMEOUT}s)", file=sys.stderr)
            return AgentResult(
                agent_name=self.name,
                success=False,
                error=f"Agent 실행 시간 초과 ({AGENT_RUN_TIMEOUT}초). 작업을 더 작은 단위로 나눠주세요.",
                steps=[{'step': 'timeout', 'duration_ms': round(duration_ms, 2)}],
                duration_ms=round(duration_ms, 2),
            )
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            print(f"[{self.name}] ❌ Unexpected error: {e}", file=sys.stderr)
            return AgentResult(
                agent_name=self.name,
                success=False,
                error=f"Agent 실행 오류: {str(e)}",
                steps=[{'step': 'error', 'error': str(e)}],
                duration_ms=round(duration_ms, 2),
            )

    async def _run_internal(self, task: str, context: dict, start_time: float) -> AgentResult:
        """실제 실행 로직 (timeout으로 감싸짐)"""
        steps = []

        print(f"\n[{self.name}] === Task received: {task[:100]}... ===", file=sys.stderr)

        # Step 1: 계획 수립
        print(f"[{self.name}] 🧠 Planning...", file=sys.stderr)
        plan_result = await self.think(task, context)
        plan_elapsed = (time.time() - start_time) * 1000
        print(f"[{self.name}] 🧠 Planning done ({plan_elapsed:.0f}ms)", file=sys.stderr)

        steps.append({
            'step': 'planning',
            'reasoning': plan_result.get('reasoning', ''),
            'plan': plan_result.get('plan', []),
            'duration_ms': round(plan_elapsed, 2),
        })

        # 직접 답변인 경우
        if plan_result.get('direct_answer'):
            duration_ms = (time.time() - start_time) * 1000
            return AgentResult(
                agent_name=self.name,
                success=True,
                result=plan_result['direct_answer'],
                steps=steps,
                duration_ms=round(duration_ms, 2),
            )

        # Step 2: 계획에 따라 도구 실행
        tool_results = []
        plan = plan_result.get('plan', [])

        for i, step in enumerate(plan):
            tool_name = step.get('tool')
            params = step.get('params', {})
            description = step.get('description', '')

            remaining = AGENT_RUN_TIMEOUT - (time.time() - start_time)
            if remaining < 5:
                print(f"[{self.name}] ⚠️ Skipping step {i+1} - only {remaining:.1f}s remaining", file=sys.stderr)
                steps.append({
                    'step': f'skipped_{i+1}',
                    'tool': tool_name,
                    'reason': f'시간 부족 ({remaining:.1f}s 남음)',
                })
                break

            print(f"[{self.name}] Step {i+1}/{len(plan)}: {tool_name} - {description} (남은시간: {remaining:.1f}s)", file=sys.stderr)

            result = await self.execute_tool(tool_name, **params)
            tool_results.append(result)

            steps.append({
                'step': f'execute_{i+1}',
                'tool': tool_name,
                'params': params,
                'description': description,
                'success': result.get('success', False),
                'duration_ms': result.get('duration_ms', 0),
            })

            # 실패 시 중단 여부 판단
            if not result.get('success'):
                print(f"[{self.name}] Step {i+1} failed: {result.get('error')}", file=sys.stderr)

        # Step 3: 결과 종합
        duration_ms = (time.time() - start_time) * 1000
        all_success = all(r.get('success', False) for r in tool_results) if tool_results else True

        # 결과를 의미 있게 종합
        combined_result = {
            'tool_results': tool_results,
            'summary': f"{self.name}이(가) {len(plan)}개 작업 중 "
                      f"{sum(1 for r in tool_results if r.get('success'))}개 성공",
        }

        print(f"[{self.name}] ✅ Completed in {duration_ms:.0f}ms", file=sys.stderr)

        return AgentResult(
            agent_name=self.name,
            success=all_success,
            result=combined_result,
            steps=steps,
            duration_ms=round(duration_ms, 2),
        )

    def __repr__(self):
        return f"<{self.name} tools={self.get_available_tools()}>"
