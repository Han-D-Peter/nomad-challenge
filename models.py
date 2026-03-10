from pydantic import BaseModel
from typing import Optional

class UserAccountContext(BaseModel):
    customer_id: int
    name: str
    order_content: Optional[str] = None



class InputGuardRailOutput(BaseModel):
    is_off_topic: bool
    reason: str

class HandoffData(BaseModel):

    to_agent_name: str
    issue_type: str
    issue_description: str
    reason: str