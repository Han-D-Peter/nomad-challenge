# 환경 변수 로드를 위한 라이브러리
import dotenv

# .env 파일에서 환경 변수 로드 (API 키 등)
dotenv.load_dotenv()

# 비동기 처리를 위한 라이브러리
import asyncio
# Streamlit 웹 애플리케이션 프레임워크
import streamlit as st

# OpenAI 클라이언트 (파일 업로드 및 벡터 스토어 관리용)
from openai import OpenAI

# OpenAI Agents 라이브러리에서 필요한 클래스들 import
from agents.agent import Agent          # AI 에이전트 클래스
from agents.run import Runner           # 에이전트 실행 클래스
from agents.memory.sqlite_session import SQLiteSession  # SQLite 세션 관리 클래스
from agents.tool import WebSearchTool, FileSearchTool  # 웹 검색 및 파일 검색 도구 클래스


# OpenAI 클라이언트 초기화 (파일 업로드 및 벡터 스토어 관리에 사용)
client = OpenAI()

# 벡터 스토어 ID (업로드된 파일들을 저장하고 검색하는 데이터베이스)
VECTOR_STORE_ID = "vs_69a8424658f8819181a1de35b44a910d"

# Streamlit 세션 상태에 에이전트가 없으면 새로 생성
if "agent" not in st.session_state:
    st.session_state["agent"] = Agent(
        name="ChatGPT Clone",           # 에이전트 이름
        instructions="""
        You are a helpful assistant.    # 에이전트의 기본 역할

        You have access to the followign tools:
            - Web Search Tool: Use this when the user asks a questions that isn't in your training data. Use this tool when the users asks about current or future events, when you think you don't know the answer, try searching for it in the web first.
            - File Search Tool: Use this tool when the user asks a question about facts related to themselves. Or when they ask questions about specific files.
        """,                            # 도구 사용 지침
        tools=[
            WebSearchTool(),            # 웹 검색 도구 추가
            FileSearchTool(
                vector_store_ids=[VECTOR_STORE_ID],  # 검색할 벡터 스토어 지정
                max_num_results=3,      # 최대 검색 결과 개수
            ),
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
                        # AI 메시지 텍스트 표시 ($ 기호 이스케이프 처리)
                        st.write(message["content"][0]["text"].replace("$", "\$"))
        # 메시지 타입 확인
        if "type" in message:
            if message["type"] == "web_search_call":
                with st.chat_message("ai"):
                    st.write("🔍 Searched the web...")  # 웹 검색 표시
            elif message["type"] == "file_search_call":
                with st.chat_message("ai"):
                    st.write("🗂️ Searched your files...")  # 파일 검색 표시


# 페이지 로드 시 대화 기록 표시
asyncio.run(paint_history())


# 상태 컨테이너를 업데이트하는 함수
def update_status(status_container, event):
    # 이벤트 타입별 상태 메시지 정의
    status_messages = {
        # 웹 검색 관련 상태
        "response.web_search_call.completed": ("✅ Web search completed.", "complete"),
        "response.web_search_call.in_progress": (
            "🔍 Starting web search...",
            "running",
        ),
        "response.web_search_call.searching": (
            "🔍 Web search in progress...",
            "running",
        ),
        # 파일 검색 관련 상태
        "response.file_search_call.completed": (
            "✅ File search completed.",
            "complete",
        ),
        "response.file_search_call.in_progress": (
            "🗂️ Starting file search...",
            "running",
        ),
        "response.file_search_call.searching": (
            "🗂️ File search in progress...",
            "running",
        ),
        # 응답 완료 상태
        "response.completed": (" ", "complete"),
    }

    # 해당 이벤트에 대한 상태 메시지가 있으면 업데이트
    if event in status_messages:
        label, state = status_messages[event]
        status_container.update(label=label, state=state)


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
                update_status(status_container, event.data.type)

                # 응답 텍스트 델타(부분)인 경우
                if event.data.type == "response.output_text.delta":
                    response += event.data.delta   # 응답 텍스트 누적
                    # $ 기호를 이스케이프 처리하여 표시
                    text_placeholder.write(response.replace("$", "\$"))


# 사용자 입력을 받는 채팅 입력 필드 생성 (파일 업로드 지원)
prompt = st.chat_input(
    "Write a message for your assistant",
    accept_file=True,                   # 파일 업로드 허용
    file_type=["txt"],                  # 텍스트 파일만 허용
)

# 사용자가 입력하거나 파일을 업로드한 경우
if prompt:
    # 업로드된 파일들을 처리
    for file in prompt.files:
        # 텍스트 파일인 경우에만 처리
        if file.type.startswith("text/"):
            with st.chat_message("ai"):
                # 파일 업로드 진행 상황 표시
                with st.status("⏳ Uploading file...") as status:
                    # OpenAI에 파일 업로드
                    uploaded_file = client.files.create(
                        file=(file.name, file.getvalue()),  # 파일명과 내용
                        purpose="user_data",    # 파일 용도
                    )
                    status.update(label="⏳ Attaching file...")
                    # 업로드된 파일을 벡터 스토어에 추가
                    client.vector_stores.files.create(
                        vector_store_id=VECTOR_STORE_ID,  # 벡터 스토어 ID
                        file_id=uploaded_file.id,  # 업로드된 파일 ID
                    )
                    status.update(label="✅ File uploaded", state="complete")

    # 텍스트 메시지가 있는 경우
    if prompt.text:
        with st.chat_message("human"):            # 사용자 메시지로 표시
            st.write(prompt.text)
        asyncio.run(run_agent(prompt.text))       # 에이전트 실행


# 사이드바에 추가 기능들 배치
with st.sidebar:
    # 메모리 초기화 버튼
    reset = st.button("Reset memory")
    # 버튼이 클릭되면 세션 데이터 초기화
    if reset:
        asyncio.run(session.clear_session())
    # 현재 세션의 모든 아이템(대화 기록) 표시
    st.write(asyncio.run(session.get_items()))