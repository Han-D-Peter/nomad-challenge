# 환경 변수 로드를 위한 라이브러리
import dotenv

# .env 파일에서 환경 변수 로드 (API 키 등)
dotenv.load_dotenv()

# 비동기 처리를 위한 라이브러리
import asyncio
# Streamlit 웹 애플리케이션 프레임워크
import streamlit as st

# OpenAI Agents 라이브러리에서 필요한 클래스들 import
from agents.agent import Agent          # AI 에이전트 클래스
from agents.run import Runner           # 에이전트 실행 클래스
from agents.memory.sqlite_session import SQLiteSession  # SQLite 세션 관리 클래스
from agents.tool import WebSearchTool  # Web 검색 도구 클래스

# Streamlit 세션 상태에 에이전트가 없으면 새로 생성
if "agent" not in st.session_state:
    st.session_state["agent"] = Agent(
        name="ChatGPT Clone",           # 에이전트 이름
        instructions="""
        You are a helpful assistant.    # 에이전트의 기본 역할

        You have access to the followign tools:
            - Web Search Tool: Use this when the user asks a questions that isn't in your training data. Use this tool when the users asks about current or future events, when you think you don't know the answer, try searching for it in the web first.
        """,                            # 웹 검색 도구 사용 지침
        tools=[
            WebSearchTool(),            # 웹 검색 도구 추가
        ],
    )
# 세션 상태에서 에이전트 가져오기
agent = st.session_state["agent"]

# Streamlit 세션 상태에 SQLite 세션이 없으면 새로 생성
if "session" not in st.session_state:
    st.session_state["session"] = SQLiteSession(
        "chat-history",                 # 세션 이름
        "chat-gpt-clone-memory.db",     # SQLite 데이터베이스 파일명
    )
# 세션 상태에서 SQLite 세션 가져오기
session = st.session_state["session"]


# 대화 기록을 화면에 표시하는 비동기 함수
async def paint_history():
    # 세션에서 모든 메시지 가져오기
    messages = await session.get_items()

    # 각 메시지를 순회하면서 화면에 표시
    for message in messages:
        # 메시지에 역할(role)이 있는 경우
        if "role" in message:
            with st.chat_message(message["role"]):  # 사용자 또는 AI 메시지로 표시
                if message["role"] == "user":
                    st.write(message["content"])     # 사용자 메시지 내용 표시
                else:
                    if message["type"] == "message":
                        st.write(message["content"][0]["text"])  # AI 메시지 텍스트 표시
        # 웹 검색 호출 메시지인 경우: 에이전트(assistant) 롤로 검색어를 화면에 남김
        if "type" in message and message["type"] == "web_search_call":
            with st.chat_message("ai"):
                action = message.get("action") if isinstance(message, dict) else None
                st.write(f"🔍 Agent searched: {action}")  # 웹 검색 표시


# 상태 컨테이너를 업데이트하는 함수
def update_status(status_container, event_type, event=None):
    
    # 이벤트 타입별 상태 메시지 정의
    status_messages = {
        "response.web_search_call.completed": ("✅ Web search completed.", "complete"),
        "response.web_search_call.in_progress": (
            "🔍 Starting web search...",
            "running",
        ),
        "response.web_search_call.searching": (
            "🔍 Web search in progress...",
            "running",
        ),
        "response.completed": (" ", "complete"),
    }

    # 해당 이벤트에 대한 상태 메시지가 있으면 업데이트
    if event_type in status_messages:
        label, state = status_messages[event_type]
        status_container.update(label=label, state=state)


# 페이지 로드 시 대화 기록 표시
asyncio.run(paint_history())


# 에이전트를 실행하고 스트리밍 응답을 처리하는 비동기 함수
async def run_agent(message):
    with st.chat_message("ai"):                    # AI 메시지 컨테이너 생성
        status_container = st.status("⏳", expanded=False)  # 상태 표시기 생성
        text_placeholder = st.empty()              # 텍스트 표시용 빈 컨테이너
        response = ""                              # 응답 텍스트 누적용 변수

        # 에이전트를 스트리밍 모드로 실행
        stream = Runner.run_streamed(
            agent,      # 사용할 에이전트
            message,    # 사용자 메시지
            session=session,  # 대화 기록을 저장할 세션
        )

        # 스트림 이벤트를 비동기적으로 처리
        async for event in stream.stream_events():
            if event.type == "raw_response_event":
                # 상태 업데이트
                update_status(status_container, event.data.type, event)

                # 스트리밍 중 웹 검색 호출 이벤트가 발생하면 즉시 에이전트 롤로 검색어를 화면에 표시
                try:
                    evt_type = event.data.type
                except Exception:
                    evt_type = None

                if evt_type and "web_search_call" in evt_type:
                    # 이벤트 데이터에서 action(검색어)을 추출
                    action = None
                    try:
                        action = getattr(event.data, "action", None)
                    except Exception:
                        action = None
                    # event.data가 dict인 경우에도 안전하게 가져오기
                    if not action and isinstance(event.data, dict):
                        action = event.data.get("action")

                    if action:
                        with st.chat_message("ai"):
                            st.write(f"🔍 Agent searched: {action}")

                # 응답 텍스트 델타(부분)인 경우
                if event.data.type == "response.output_text.delta":
                    response += event.data.delta   # 응답 텍스트 누적
                    text_placeholder.write(response)  # 누적된 텍스트 표시


# 사용자 입력을 받는 채팅 입력 필드 생성
prompt = st.chat_input("Write a message for your assistant")

# 사용자가 메시지를 입력한 경우
if prompt:
    with st.chat_message("human"):                # 사용자 메시지로 표시
        st.write(prompt)
    asyncio.run(run_agent(prompt))               # 에이전트 실행


# 사이드바에 추가 기능들 배치
with st.sidebar:
    # 메모리 초기화 버튼
    reset = st.button("Reset memory")
    # 버튼이 클릭되면 세션 데이터 초기화
    if reset:
        asyncio.run(session.clear_session())
    # 현재 세션의 모든 아이템(대화 기록) 표시
    st.write(asyncio.run(session.get_items()))