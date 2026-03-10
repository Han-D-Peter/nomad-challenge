import streamlit as st
from agents import (
    Agent,
    RunContextWrapper,
    input_guardrail,
    Runner,
    GuardrailFunctionOutput,
    handoff,
)
from agents.extensions.handoff_prompt import RECOMMENDED_PROMPT_PREFIX
from agents.extensions import handoff_filters
from models import UserAccountContext, InputGuardRailOutput, HandoffData
from my_agents.menu_agent import menu_agent
from my_agents.order_agent import order_agent
from my_agents.reservation_agent import reservation_agent


# ============================================================================
# Input Guardrail Agent
# ============================================================================
# 목적: 사용자 요청이 고객 지원 범위 내에 있는지 검증
# 허용 범위: 계정 관리, 결제, 주문, 기술 지원
# 범위 외 요청은 차단하고 이유를 반환
input_guardrail_agent = Agent(
    name="Input Guardrail Agent",
    instructions="""
    Ensure the user's request specifically pertains to restaurant-related topics such as:
    - 메뉴(요리, 음료)에 대한 질문
    - 테이블 예약, 인원, 시간 관련 문의
    - 매장 내 식사, 포장, 배달 주문 관련 문의
    - 알레르기/식단 제한과 메뉴 가능 여부

    If the request is clearly off-topic (예: 일반적인 개발 질문, 전혀 무관한 일상 대화, 다른 서비스/제품 문의 등),
    mark it as off-topic and return a clear reason for the tripwire.

    You can make small friendly conversation at the beginning (인사, 짧은 리액션 등)는 괜찮지만,
    레스토랑과 무관한 요청에 대해서는 실제 도움(설명, 해결 방법 제시 등)을 제공하지 마세요.
    """,
    output_type=InputGuardRailOutput,
)


# ============================================================================
# Off-Topic Guardrail Function
# ============================================================================
# 사용자 입력이 주제에서 벗어났는지 검사하는 가드레일 함수
# - input_guardrail_agent를 실행하여 요청 검증
# - is_off_topic이 True면 tripwire 발동 (요청 차단)
# - 대화 초반 간단한 인사말은 허용하되, 범위 외 요청은 차단
@input_guardrail
async def off_topic_guardrail(
    wrapper: RunContextWrapper[UserAccountContext],
    agent: Agent[UserAccountContext],
    input: str,
):
    # Input Guardrail Agent 실행하여 입력 검증
    result = await Runner.run(
        input_guardrail_agent,
        input,
        context=wrapper.context,
    )

    # 검증 결과 반환 (off-topic이면 tripwire 발동)
    return GuardrailFunctionOutput(
        output_info=result.final_output,
        tripwire_triggered=result.final_output.is_off_topic,
    )



def dynamic_triage_agent_instructions(
    wrapper: RunContextWrapper[UserAccountContext],
    agent: Agent[UserAccountContext],
):
    return f"""
    {RECOMMENDED_PROMPT_PREFIX}


    You are a restaurant customer support and concierge agent.
    You ONLY help customers with restaurant-related questions.
    You call customers politely by their name.
    
    The customer's name is {wrapper.context.name}.
    
    ORDER: {wrapper.context.order_content}
    
    YOUR MAIN JOB: 손님의 문의를 이해하고, 아래 세 가지 전문 에이전트 중 가장 알맞은 에이전트로 라우팅하는 것입니다.
    
    ISSUE CLASSIFICATION GUIDE (레스토랑 전용):
    
    🧾 메뉴/추천/알레르기 안내 - Route to MENU AGENT (menu_agent) for:
    - 메뉴 설명, 맛/양/구성에 대한 질문
    - 오늘의 스페셜, 시그니처 메뉴, 코스 안내
    - 매운 정도, 토핑/옵션 선택 방법
    - 알레르기(갑각류, 견과류 등)나 식단 제한(비건, 글루텐 프리 등)에 따른 메뉴 추천
    - "뭐가 맛있나요?", "비건 메뉴 있나요?", "매운 거 잘 못 먹는데 뭐가 좋을까요?"
    
    🍽 테이블 예약/좌석/인원 - Route to RESERVATION AGENT (reservation_agent) for:
    - 날짜/시간, 인원 수에 따른 테이블 예약 문의
    - 룸/홀/창가 등 좌석 위치 선호
    - 기념일, 프로포즈, 비즈니스 미팅 등 목적에 따른 좌석/시간 추천
    - 예약 변경/취소 가능 여부 문의 (정책 안내 수준)
    - "내일 7시에 4명 자리 있나요?", "룸 예약 가능할까요?", "예약 시간 조금 늦춰도 되나요?"
    
    🛍 매장 내 식사/포장/배달 주문 - Route to ORDER AGENT (order_agent) for:
    - 포장/배달 주문 구성 및 수량 확인
    - 희망 수령/배달 시간 확인
    - 기존에 논의된 주문 내용 재확인 및 최종 확정
    - 단체 주문/세트 구성 문의 (예약이 아닌, 주문 자체에 초점)
    - "포장 주문하고 싶어요", "배달로 2~3인 세트 주문할 수 있나요?", "아까 주문한 메뉴 다시 확인하고 싶어요"
    
    CLASSIFICATION PROCESS:
    1. 먼저 손님의 말을 끝까지 듣고, 어떤 의도(메뉴 질문/예약/주문)가 중심인지 파악합니다.
    2. 만약 애매하면 1~2개의 짧은 확인 질문만 해서 의도를 분명히 합니다.
    3. 위 세 가지 카테고리 중 하나를 선택해, 정확히 한 곳으로만 라우팅합니다.
    4. 왜 그 에이전트로 연결하는지 한 문장으로 설명합니다.
       예시: "메뉴 추천과 알레르기 관련 문의이기 때문에, 메뉴 안내 전문 에이전트에게 연결해 드릴게요."
    5. 선택한 전문 에이전트로 핸드오프합니다.
    
    SPECIAL HANDLING:
    - Premium/Enterprise(상위 등급) 고객: 라우팅 시 "우선적으로 도와드린다"는 표현을 덧붙입니다.
    - 문의가 여러 가지 섞여 있을 때:
      - 지금 가장 급하거나 중요한 것(예: 당일 예약/주문)을 먼저 라우팅하고,
        나머지는 추가로 이어서 도와드릴 수 있다고 짧게 언급합니다.
    - 여전히 카테고리가 애매하면:
      - 메뉴/예약/주문 중 손님이 가장 먼저 강조한 부분에 우선순위를 두고 라우팅합니다.
    """


# ============================================================================
# Handoff Handler
# ============================================================================
# 전문가 에이전트로 핸드오프할 때 호출되는 콜백 함수
# - Streamlit 사이드바에 핸드오프 정보 표시
# - 대상 에이전트, 이유, 문의 유형, 설명 출력
def handle_handoff(
    wrapper: RunContextWrapper[UserAccountContext],
    input_data: HandoffData,
):
    # 사이드바에 핸드오프 정보 표시
    with st.sidebar:
        st.write(
            f"""
            Handing off to {input_data.to_agent_name}
            Reason: {input_data.reason}
            Issue Type: {input_data.issue_type}
            Description: {input_data.issue_description}
        """
        )


# ============================================================================
# Handoff Factory Function
# ============================================================================
# 에이전트에 대한 핸드오프 설정을 생성하는 헬퍼 함수
# - 핸드오프 시 handle_handoff 콜백 실행
# - HandoffData 타입으로 데이터 전달
# - 핸드오프 후 모든 도구 제거 (전문가 에이전트가 자체 도구 사용)
def make_handoff(agent):
    return handoff(
        agent=agent,
        on_handoff=handle_handoff,  # 핸드오프 발생 시 실행할 콜백
        input_type=HandoffData,  # 핸드오프 데이터 타입
        input_filter=handoff_filters.remove_all_tools,  # 도구 제거 필터
    )


# ============================================================================
# Triage Agent Definition
# ============================================================================
# 고객 문의를 분류하고 라우팅하는 메인 트리아지 에이전트
# 
# 주요 기능:
# 1. Input Guardrail로 주제 이탈 요청 필터링
# 2. 고객 정보 기반 동적 지시사항 생성
# 3. 4개 전문가 에이전트로 핸드오프:
#    - Technical Agent: 기술 지원 (버그, 오류, 사용법)
#    - Billing Agent: 결제 관련 (환불, 구독, 인보이스)
#    - Account Agent: 계정 관리 (로그인, 비밀번호, 설정)
#    - Order Agent: 주문 관리 (배송, 반품, 주문 상태)
triage_agent = Agent(
    name="Triage Agent",
    instructions=dynamic_triage_agent_instructions,  # 동적 지시사항 함수
    input_guardrails=[
        off_topic_guardrail,  # 주제 이탈 검사 가드레일
    ],
    # tools=[
    #     # 도구 대신 핸드오프를 사용하여 전문가 에이전트로 완전히 전환
    #     technical_agent.as_tool(
    #         tool_name="Technical Help Tool",
    #         tool_description="Use this when the user needs tech support."
    #     )
    # ]
    handoffs=[
        make_handoff(menu_agent),  
        make_handoff(reservation_agent),    
        make_handoff(order_agent),     
    ],
)