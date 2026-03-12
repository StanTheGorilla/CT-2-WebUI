import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

class MessageType(str, Enum):
    TASK = "task"
    RESPONSE = "response"
    TENSION = "tension"
    RESOLUTION = "resolution"
    REFLECTION = "reflection"

@dataclass
class Message:
    id: str
    from_role: str
    to: str
    type: MessageType
    payload: str
    confidence: float
    round: int
    timestamp: float = field(default_factory=time.time)

class MessageBus:
    def __init__(self):
        self.history: list[Message] = []

    def create(self, from_role: str, to: str, type: MessageType,
               payload: str, confidence: float = 0.0, round_num: int = 0) -> Message:
        return Message(
            id=f"msg-{uuid.uuid4().hex[:8]}",
            from_role=from_role,
            to=to,
            type=type,
            payload=payload,
            confidence=confidence,
            round=round_num,
        )

    def post(self, from_role: str, to: str, type: MessageType,
             payload: str, confidence: float = 0.0, round_num: int = 0) -> Message:
        msg = self.create(from_role, to, type, payload, confidence, round_num)
        self.history.append(msg)
        return msg

    def get_mind_responses(self, round_num: int) -> list[Message]:
        return [
            m for m in self.history
            if m.round == round_num
            and m.type == MessageType.RESPONSE
            and m.from_role.startswith("mind-")
        ]

    def clear(self):
        self.history = []

    def to_dict_list(self) -> list[dict]:
        return [
            {
                "id": m.id, "from": m.from_role, "to": m.to,
                "type": m.type, "payload": m.payload,
                "confidence": m.confidence, "round": m.round,
                "timestamp": m.timestamp
            }
            for m in self.history
        ]
