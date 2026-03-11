from agents import Agent, RunContextWrapper
from models import UserAccountContext


def dynamic_complaints_agent_instructions(
    wrapper: RunContextWrapper[UserAccountContext],
    agent: Agent[UserAccountContext],
):
    return f"""
    당신은 아웃바운드 상담원입니다.
    
    당신의 역할: 사용자의 불편함을 세심하게 처리하고 해결책을 제시
    
    오더: {wrapper.context.order_content}

    """


complaints_agent = Agent(
    name="Complaints Agent",
    instructions=dynamic_complaints_agent_instructions,
)