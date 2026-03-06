# 환경 변수 로드를 위한 라이브러리
import dotenv

# .env 파일에서 환경 변수 로드 (API 키 등)
dotenv.load_dotenv()

# 비동기 처리를 위한 라이브러리
import asyncio

# Base64 인코딩 라이브러리 (이미지를 문자열로 변환하기 위해 사용)
import base64
# 타입 힌트 호환성(파이썬 3.9 이하)용
from typing import Optional
# Streamlit 웹 애플리케이션 프레임워크
import streamlit as st

# OpenAI 클라이언트 (파일 업로드 및 벡터 스토어 관리용)
from openai import OpenAI

# OpenAI Agents 라이브러리에서 필요한 클래스들 import
from agents.agent import Agent          # AI 에이전트 클래스
from agents.run import Runner           # 에이전트 실행 클래스
from agents.memory.sqlite_session import SQLiteSession  # SQLite 세션 관리 클래스
from agents.tool import WebSearchTool, FileSearchTool, ImageGenerationTool  # 도구 클래스들

# OpenAI 클라이언트 초기화 (파일 업로드 및 벡터 스토어 관리에 사용)
client = OpenAI()

# 벡터 스토어 ID (업로드된 파일들을 저장하고 검색하는 데이터베이스)
VECTOR_STORE_ID = "vs_69aa602e827c81919496c9ae40bf0135"

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
            WebSearchTool(),            # 웹 검색 도구
            FileSearchTool(
                vector_store_ids=[VECTOR_STORE_ID],  # 검색할 벡터 스토어 지정
                max_num_results=3,      # 최대 검색 결과 개수
            ),
            ImageGenerationTool(        # 이미지 생성 도구 (DALL-E)
                tool_config={
                    "type": "image_generation",     # 도구 타입
                    "quality": "high",              # 고품질 이미지 생성
                    "output_format": "jpeg",        # JPEG 형식으로 출력
                    "partial_images": 1,            # 생성 중간 과정 이미지 표시
                }
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

class RunnerSessionProxy:
    """
    SQLiteSession에는 UI 렌더링용으로 tool-call 이벤트(예: web_search_call, image_generation_call)가 함께 저장됩니다.
    하지만 OpenAI Responses API의 다음 요청 input에는 'role' 기반 메시지만 넣어야 하므로,
    Runner에는 정제된 히스토리만 제공하는 프록시를 사용합니다.
    """

    def __init__(self, base_session: SQLiteSession):
        self._base_session = base_session

    async def get_items(self):
        items = await self._base_session.get_items()
        sanitized = []
        for item in items:
            if not isinstance(item, dict) or "role" not in item:
                # tool-call 결과/이벤트는 모델 input으로 재사용하지 않음
                continue

            role = item.get("role")
            content = item.get("content")

            if role == "assistant" and isinstance(content, list):
                # 저장된 assistant 메시지는 output_text 객체 배열 형태일 수 있어,
                # 모델 input에는 plain text로 정규화합니다.
                texts = []
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "output_text" and isinstance(part.get("text"), str):
                        texts.append(part["text"])
                content = "\n".join(texts) if texts else ""

            sanitized.append({"role": role, "content": content})

        return sanitized

    async def add_items(self, items):
        return await self._base_session.add_items(items)

    async def clear_session(self):
        return await self._base_session.clear_session()


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
                    content = message["content"]
                    # 문자열 타입인 경우 (일반 텍스트 메시지)
                    if isinstance(content, str):
                        st.write(content)
                    # 리스트 타입인 경우 (이미지가 포함된 메시지)
                    elif isinstance(content, list):
                        for part in content:
                            # 이미지 URL이 있으면 이미지 표시
                            if "image_url" in part:
                                st.image(part["image_url"])

                else:
                    if message["type"] == "message":
                        # AI 메시지 텍스트 표시 ($ 기호 이스케이프 처리)
                        st.write(message["content"][0]["text"].replace("$", "\\$"))
        # 메시지 타입 확인 (도구 사용 여부)
        if "type" in message:
            message_type = message["type"]
            if message_type == "web_search_call":
                with st.chat_message("ai"):
                    st.write("🔍 Searched the web...")  # 웹 검색 표시
            elif message_type == "file_search_call":
                with st.chat_message("ai"):
                    st.write("🗂️ Searched your files...")  # 파일 검색 표시
            elif message_type == "image_generation_call":
                # Base64로 인코딩된 이미지를 디코딩
                image = base64.b64decode(message["result"])
                with st.chat_message("ai"):
                    st.image(image)     # 생성된 이미지 표시


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
        # 이미지 생성 관련 상태
        "response.image_generation_call.generating": (
            "🎨 Drawing image...",
            "running",
        ),
        "response.image_generation_call.in_progress": (
            "🎨 Drawing image...",
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
    # 스트리밍 시작 전 아이템 길이를 기억해두면,
    # 스트리밍 종료 후 "이번 턴에서 새로 추가된" 도구 결과(이미지 등)만 골라낼 수 있습니다.
    pre_items = await session.get_items()
    pre_items_len = len(pre_items)

    with st.chat_message("ai"):                    # AI 메시지 컨테이너 생성
        status_container = st.status("⏳", expanded=False)  # 상태 표시기 생성
        text_placeholder = st.empty()              # 텍스트 표시용 빈 컨테이너
        image_placeholder = st.empty()             # 이미지 표시용 빈 컨테이너
        response = ""                              # 응답 텍스트 누적용 변수
        last_partial_image: Optional[bytes] = None  # 마지막 중간 이미지(있으면 유지)

        # 에이전트를 스트리밍 모드로 실행
        runner_session = RunnerSessionProxy(session)
        stream = Runner.run_streamed(
            agent,      # 사용할 에이전트
            message,    # 사용자 메시지
            session=runner_session,  # Runner에는 정제된 히스토리만 제공
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
                    text_placeholder.write(response.replace("$", "\\$"))

                # 이미지 생성 중간 과정 이미지인 경우
                elif event.data.type == "response.image_generation_call.partial_image":
                    # Base64로 인코딩된 중간 이미지 디코딩
                    image = base64.b64decode(event.data.partial_image_b64)
                    last_partial_image = image
                    image_placeholder.image(image)  # 중간 과정 이미지 표시

        # 스트리밍이 끝난 뒤, 이번 턴에 새로 저장된 최종 이미지 결과가 있으면 바로 렌더합니다.
        # (중간 이미지(partial)만 보여주고 사라지는 문제를 방지)
        post_items = await session.get_items()
        new_items = post_items[pre_items_len:]
        final_image_b64: Optional[str] = None
        for item in reversed(new_items):
            if isinstance(item, dict) and item.get("type") == "image_generation_call" and item.get("result"):
                final_image_b64 = item["result"]
                break

        if final_image_b64:
            image_placeholder.image(base64.b64decode(final_image_b64))
        elif last_partial_image:
            # 최종 결과를 못 찾았더라도 마지막 partial 이미지는 유지합니다.
            image_placeholder.image(last_partial_image)

        # 텍스트도 최종 상태로 한번 더 확정 렌더합니다.
        if response:
            text_placeholder.write(response.replace("$", "\\$"))


# 사용자 입력을 받는 채팅 입력 필드 생성 (파일 업로드 지원)
prompt = st.chat_input(
    "Write a message for your assistant",
    accept_file=True,                   # 파일 업로드 허용
    file_type=[
        "txt",                          # 텍스트 파일
        "jpg",                          # JPEG 이미지
        "jpeg",                         # JPEG 이미지
        "png",                          # PNG 이미지
    ],
)

# 사용자가 입력하거나 파일을 업로드한 경우
if prompt:
    # 업로드된 파일들을 처리
    for file in prompt.files:
        # 텍스트 파일인 경우 (벡터 스토어에 저장)
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
        # 이미지 파일인 경우 (비전 기능 사용)
        elif file.type.startswith("image/"):
            with st.status("⏳ Uploading image...") as status:
                # 이미지 파일을 바이트로 읽기
                file_bytes = file.getvalue()
                # Base64로 인코딩 (이미지를 텍스트로 변환)
                base64_data = base64.b64encode(file_bytes).decode("utf-8")
                # Data URI 형식으로 변환 (브라우저에서 표시 가능한 형식)
                data_uri = f"data:{file.type};base64,{base64_data}"
                # 세션에 이미지 메시지 추가
                asyncio.run(
                    session.add_items(
                        [
                            {
                                "role": "user",     # 사용자 메시지
                                "content": [
                                    {
                                        "type": "input_image",  # 이미지 타입
                                        "detail": "auto",       # 자동 해상도
                                        "image_url": data_uri,  # 이미지 데이터
                                    }
                                ],
                            }
                        ]
                    )
                )
                status.update(label="✅ Image uploaded", state="complete")
            # 업로드된 이미지를 화면에 표시
            with st.chat_message("human"):
                st.image(data_uri)

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
    # 현재 세션의 모든 아이템(대화 기록) 표시 (JSON 형태)
    st.write(asyncio.run(session.get_items()))