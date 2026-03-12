from ct1.core.message_bus import MessageBus, Message, MessageType

def test_create_message():
    bus = MessageBus()
    msg = bus.create("brain", "all", MessageType.TASK, "solve X", confidence=0.0)
    assert msg.from_role == "brain"
    assert msg.to == "all"
    assert msg.type == MessageType.TASK
    assert msg.payload == "solve X"

def test_bus_stores_messages():
    bus = MessageBus()
    bus.post("brain", "all", MessageType.TASK, "test", confidence=0.0)
    bus.post("mind-alpha", "brain", MessageType.RESPONSE, "answer", confidence=0.7)
    assert len(bus.history) == 2

def test_get_mind_responses():
    bus = MessageBus()
    bus.post("brain", "all", MessageType.TASK, "q", round_num=1, confidence=0.0)
    bus.post("mind-alpha", "brain", MessageType.RESPONSE, "a1", round_num=1, confidence=0.8)
    bus.post("mind-beta", "brain", MessageType.RESPONSE, "a2", round_num=1, confidence=0.6)
    bus.post("mind-gamma", "brain", MessageType.RESPONSE, "a3", round_num=1, confidence=0.9)
    responses = bus.get_mind_responses(round_num=1)
    assert len(responses) == 3

def test_clear_resets_history():
    bus = MessageBus()
    bus.post("brain", "all", MessageType.TASK, "test", confidence=0.0)
    bus.clear()
    assert len(bus.history) == 0
