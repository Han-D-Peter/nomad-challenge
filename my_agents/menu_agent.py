from agents import Agent, RunContextWrapper
from models import UserAccountContext


def dynamic_menu_agent_instructions(
    wrapper: RunContextWrapper[UserAccountContext],
    agent: Agent[UserAccountContext],
):
    return f"""
    당신은 식당 메뉴 관리자입니다. {wrapper.context.name} 님의 메뉴 안내 요청을 돕습니다.
    
    당신의 역할: 메뉴에 대한 설명을 안내합니다.
    
    오더: {wrapper.context.order_content}
    
    메뉴 재료 식별:
    1. 오더 내용을 확인하세요
    2. 오더안에 메뉴에 대한 정보처리 식별을 해주세요
    3. 메뉴를 알레르기 유발 가능성을 염두하고 들어갈 수 있는 모든 식재료를 식별해주세요
    4. 그리고 오더 내용에 따라 답변을 만들어주세요

    """


menu_agent = Agent(
    name="Menu Agent",
    instructions=dynamic_menu_agent_instructions,
)