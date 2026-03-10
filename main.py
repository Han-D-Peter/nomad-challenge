"""
고객 지원 에이전트 Streamlit 애플리케이션

이 애플리케이션은 멀티 에이전트 고객 지원 시스템의 메인 인터페이스입니다.
- Triage Agent로 시작하여 고객 문의를 분류
- 필요시 전문가 에이전트로 자동 전환
- 대화 히스토리를 SQLite에 저장하여 컨텍스트 유지
- 스트리밍 방식으로 실시간 응답 표시
"""

import dotenv

dotenv.load_dotenv()  # .env 파일에서 환경 변수 로드 (OPENAI_API_KEY 등)
from openai import OpenAI
import asyncio
import streamlit as st
from agents import Runner, SQLiteSession, InputGuardrailTripwireTriggered
from models import UserAccountContext
from my_agents.triage_agent import triage_agent

# ============================================================================
# 클라이언트 및 컨텍스트 초기화
# ============================================================================
client = OpenAI()  # OpenAI API 클라이언트 생성

# 고객 계정 정보 컨텍스트 (실제로는 로그인 시스템에서 가져와야 함)
user_account_ctx = UserAccountContext(
    customer_id=1, 
    name="peter",
)


# ============================================================================
# Streamlit 세션 상태 관리
# ============================================================================
# SQLite 세션: 대화 히스토리를 영구적으로 저장
# - 페이지 새로고침 시에도 대화 내용 유지
# - 각 고객별로 독립적인 세션 관리 가능
if "session" not in st.session_state:
    st.session_state["session"] = SQLiteSession(
        "chat-history",  # 세션 ID (고객별로 다르게 설정 가능)
        "customer-support-memory.db",  # SQLite 데이터베이스 파일명
    )
session = st.session_state["session"]

# 현재 활성 에이전트 상태 관리
# - 처음에는 Triage Agent로 시작
# - 핸드오프 발생 시 전문가 에이전트로 전환
if "agent" not in st.session_state:
    st.session_state["agent"] = triage_agent


# ============================================================================
# 대화 히스토리 렌더링 함수
# ============================================================================
# SQLite 세션에 저장된 이전 대화 내역을 화면에 표시
# - 사용자 메시지와 AI 응답을 구분하여 렌더링
# - Markdown의 수식 표현($)이 깨지지 않도록 이스케이프 처리
async def paint_history():
    messages = await session.get_items()  # 세션에서 모든 메시지 가져오기
    for message in messages:
        if "role" in message:
            # 메시지 역할(user/assistant)에 따라 채팅 UI 표시
            with st.chat_message(message["role"]):
                if message["role"] == "user":
                    # 사용자 메시지는 단순 텍스트
                    st.write(message["content"])
                else:
                    # AI 응답은 구조화된 형식으로 저장되어 있음
                    if message["type"] == "message":
                        # $ 기호를 이스케이프하여 Markdown 수식 오류 방지
                        st.write(message["content"][0]["text"].replace("$", "\$"))


# 페이지 로드 시 이전 대화 히스토리 표시
asyncio.run(paint_history())


# ============================================================================
# 에이전트 실행 함수
# ============================================================================
# 사용자 메시지를 받아 에이전트를 실행하고 스트리밍 응답을 표시
# 
# 주요 기능:
# 1. 스트리밍 방식으로 실시간 응답 표시
# 2. 에이전트 전환(핸드오프) 감지 및 처리
# 3. Input Guardrail 위반 시 오류 처리
async def run_agent(message):
    with st.chat_message("ai"):
        # 응답을 표시할 플레이스홀더 생성
        text_placeholder = st.empty()
        response = ""  # 누적 응답 텍스트

        # 세션 상태에 저장하여 에이전트 전환 시에도 접근 가능하도록
        st.session_state["text_placeholder"] = text_placeholder

        try:
            # 에이전트를 스트리밍 모드로 실행
            stream = Runner.run_streamed(
                st.session_state["agent"],  # 현재 활성 에이전트
                message,  # 사용자 메시지
                session=session,  # 대화 히스토리 세션
                context=user_account_ctx,  # 고객 컨텍스트 정보
            )

            # 스트림에서 이벤트를 하나씩 처리
            async for event in stream.stream_events():
                # ========================================================
                # 텍스트 응답 이벤트: AI가 생성한 텍스트의 일부(delta)
                # ========================================================
                if event.type == "raw_response_event":
                    if event.data.type == "response.output_text.delta":
                        # 델타를 누적하여 전체 응답 구성
                        response += event.data.delta
                        # 플레이스홀더에 업데이트 (실시간 타이핑 효과)
                        text_placeholder.write(response.replace("$", "\$"))

                # ========================================================
                # 에이전트 전환 이벤트: 핸드오프 발생
                # ========================================================
                elif event.type == "agent_updated_stream_event":
                    # 에이전트가 실제로 변경되었는지 확인
                    if st.session_state["agent"].name != event.new_agent.name:
                        # 전환 메시지 표시
                        st.write(f"🤖 Transfered from {st.session_state["agent"].name} to {event.new_agent.name}")

                        # 세션 상태의 에이전트를 새 에이전트로 업데이트
                        st.session_state["agent"] = event.new_agent

                        # 새 에이전트의 응답을 위한 새 플레이스홀더 생성
                        text_placeholder = st.empty()
                        st.session_state["text_placeholder"] = text_placeholder
                        response = ""  # 응답 초기화

        # ========================================================
        # Input Guardrail 위반: 주제 이탈 요청 차단
        # ========================================================
        except InputGuardrailTripwireTriggered:
            st.write("I can't help you with that.")


# ============================================================================
# 채팅 입력 인터페이스
# ============================================================================
# Streamlit의 채팅 입력 위젯으로 사용자 메시지 수신
message = st.chat_input(
    "Write a message for your assistant",
)

# 메시지가 입력되면 처리
if message:
    # 사용자 메시지를 화면에 표시
    with st.chat_message("human"):
        st.write(message)
    # 에이전트 실행하여 응답 생성
    asyncio.run(run_agent(message))


# ============================================================================
# 사이드바: 디버깅 및 관리 도구
# ============================================================================
with st.sidebar:
    # 메모리 리셋 버튼: 대화 히스토리 전체 삭제
    reset = st.button("Reset memory")
    if reset:
        asyncio.run(session.clear_session())
    
    # 현재 세션의 모든 메시지 표시 (디버깅용)
    # 실제 프로덕션에서는 제거하거나 개발자 모드에서만 표시
    st.write(asyncio.run(session.get_items()))