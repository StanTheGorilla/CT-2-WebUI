import pytest
import asyncio
from ct1.memory.conversation_db import ConversationDB


@pytest.fixture
async def db(tmp_path):
    """Create a ConversationDB using a temp directory for isolation."""
    db_path = str(tmp_path / "test.db")
    cdb = ConversationDB(db_path=db_path)
    await cdb.init()
    yield cdb
    await cdb.close()


@pytest.mark.asyncio
async def test_init_creates_tables(db):
    """init DB, create conversation, list it."""
    conv_id = await db.create_conversation("Hello World", preset="default")
    assert isinstance(conv_id, str)
    assert len(conv_id) == 36  # UUID format

    convos = await db.list_conversations()
    assert len(convos) == 1
    assert convos[0]["id"] == conv_id
    assert convos[0]["title"] == "Hello World"
    assert convos[0]["preset"] == "default"


@pytest.mark.asyncio
async def test_add_and_get_messages(db):
    """Add user + assistant messages, verify ordering and fields."""
    conv_id = await db.create_conversation("Chat 1")

    msg1_id = await db.add_message(
        conv_id, "user", "Hello there", position=0
    )
    msg2_id = await db.add_message(
        conv_id,
        "assistant",
        "Hi! How can I help?",
        position=1,
        thinking="Let me think...",
        draft="Draft response",
        route="ROUTE_DIRECT",
        specialist_data='{"model": "gpt-4"}',
        reflection='{"score": 0.9}',
    )

    assert isinstance(msg1_id, str)
    assert len(msg1_id) == 36

    conv = await db.get_conversation(conv_id)
    assert conv is not None
    assert conv["title"] == "Chat 1"
    assert len(conv["messages"]) == 2

    m1 = conv["messages"][0]
    assert m1["role"] == "user"
    assert m1["content"] == "Hello there"
    assert m1["position"] == 0

    m2 = conv["messages"][1]
    assert m2["role"] == "assistant"
    assert m2["content"] == "Hi! How can I help?"
    assert m2["thinking"] == "Let me think..."
    assert m2["draft"] == "Draft response"
    assert m2["route"] == "ROUTE_DIRECT"
    assert m2["specialist_data"] == '{"model": "gpt-4"}'
    assert m2["reflection"] == '{"score": 0.9}'
    assert m2["position"] == 1


@pytest.mark.asyncio
async def test_delete_conversation(db):
    """Create then delete, verify gone."""
    conv_id = await db.create_conversation("To Delete")
    await db.add_message(conv_id, "user", "bye", position=0)

    result = await db.delete_conversation(conv_id)
    assert result is True

    conv = await db.get_conversation(conv_id)
    assert conv is None

    # Deleting again should return False
    result = await db.delete_conversation(conv_id)
    assert result is False


@pytest.mark.asyncio
async def test_rename_conversation(db):
    """Rename and verify."""
    conv_id = await db.create_conversation("Old Name")

    result = await db.rename_conversation(conv_id, "New Name")
    assert result is True

    conv = await db.get_conversation(conv_id)
    assert conv["title"] == "New Name"

    # Renaming non-existent should return False
    result = await db.rename_conversation("non-existent-id", "Nope")
    assert result is False


@pytest.mark.asyncio
async def test_set_feedback(db):
    """Set feedback on a message, verify."""
    conv_id = await db.create_conversation("Feedback Test")
    msg_id = await db.add_message(conv_id, "assistant", "response", position=0)

    # Initially no feedback
    conv = await db.get_conversation(conv_id)
    assert conv["messages"][0]["feedback"] is None

    # Set positive feedback
    result = await db.set_feedback(msg_id, 1)
    assert result is True
    conv = await db.get_conversation(conv_id)
    assert conv["messages"][0]["feedback"] == 1

    # Set negative feedback
    result = await db.set_feedback(msg_id, -1)
    assert result is True
    conv = await db.get_conversation(conv_id)
    assert conv["messages"][0]["feedback"] == -1

    # Clear feedback
    result = await db.set_feedback(msg_id, None)
    assert result is True
    conv = await db.get_conversation(conv_id)
    assert conv["messages"][0]["feedback"] is None

    # Non-existent message
    result = await db.set_feedback("non-existent-id", 1)
    assert result is False


@pytest.mark.asyncio
async def test_list_conversations_ordered(db):
    """Create two convos, add message to first, verify first comes first in list."""
    conv1_id = await db.create_conversation("First")
    conv2_id = await db.create_conversation("Second")

    # conv2 was created after conv1, so it should be first in list
    convos = await db.list_conversations()
    assert convos[0]["id"] == conv2_id
    assert convos[1]["id"] == conv1_id

    # Now add a message to conv1 — this bumps its updated_at
    await db.add_message(conv1_id, "user", "bump", position=0)

    # Now conv1 should come first (most recently updated)
    convos = await db.list_conversations()
    assert convos[0]["id"] == conv1_id
    assert convos[1]["id"] == conv2_id


@pytest.mark.asyncio
async def test_message_count_in_list(db):
    """Verify message_count field in list output."""
    conv1_id = await db.create_conversation("With Messages")
    conv2_id = await db.create_conversation("Empty")

    await db.add_message(conv1_id, "user", "hi", position=0)
    await db.add_message(conv1_id, "assistant", "hello", position=1)
    await db.add_message(conv1_id, "user", "how are you?", position=2)

    convos = await db.list_conversations()
    # Find each conversation in the list
    conv1_data = next(c for c in convos if c["id"] == conv1_id)
    conv2_data = next(c for c in convos if c["id"] == conv2_id)

    assert conv1_data["message_count"] == 3
    assert conv2_data["message_count"] == 0


@pytest.mark.asyncio
async def test_fork_conversation_copies_messages_up_to_position(db):
    """Forking should create a branch conversation trimmed to the selected turn."""
    conv_id = await db.create_conversation("Branch Me", preset="default")
    await db.add_message(conv_id, "user", "First", position=0)
    await db.add_message(
        conv_id,
        "assistant",
        "First reply",
        position=1,
        thinking="thinking-1",
        draft="draft-1",
        route="ROUTE_DIRECT",
        specialist_data='{"route":"direct"}',
        reflection='{"score": 0.8}',
        detected_lang="markdown",
    )
    await db.add_message(conv_id, "user", "Second", position=2)
    await db.add_message(conv_id, "assistant", "Second reply", position=3)

    forked = await db.fork_conversation(conv_id, upto_position=2)

    assert forked is not None
    assert forked["id"] != conv_id
    assert forked["title"] == "Branch Me (branch)"

    forked_conv = await db.get_conversation(forked["id"])
    assert forked_conv is not None
    assert forked_conv["preset"] == "default"
    assert [m["content"] for m in forked_conv["messages"]] == [
        "First",
        "First reply",
        "Second",
    ]
    assert [m["position"] for m in forked_conv["messages"]] == [0, 1, 2]
    assert forked_conv["messages"][1]["thinking"] == "thinking-1"
    assert forked_conv["messages"][1]["draft"] == "draft-1"
    assert forked_conv["messages"][1]["route"] == "ROUTE_DIRECT"
    assert forked_conv["messages"][1]["specialist_data"] == '{"route":"direct"}'
    assert forked_conv["messages"][1]["reflection"] == '{"score": 0.8}'
    assert forked_conv["messages"][1]["detected_lang"] == "markdown"


@pytest.mark.asyncio
async def test_fork_conversation_from_messages_uses_visible_history(db):
    """Forking from frontend-visible turns should preserve the trimmed branch state."""
    conv_id = await db.create_conversation("Visible History", preset="default")

    forked = await db.fork_conversation_from_messages(
        conv_id,
        [
            {"role": "assistant", "content": "Summary of older turns"},
            {
                "role": "user",
                "content": "Keep this request",
                "specialistData": {"mode": "design"},
            },
            {
                "role": "assistant",
                "content": "Keep this reply",
                "thinking": "kept-thinking",
                "reflection": {"score": 0.95},
                "detectedLang": "html",
            },
        ],
    )

    forked_conv = await db.get_conversation(forked["id"])
    assert forked_conv is not None
    assert forked_conv["title"] == "Visible History (branch)"
    assert [m["content"] for m in forked_conv["messages"]] == [
        "Summary of older turns",
        "Keep this request",
        "Keep this reply",
    ]
    assert forked_conv["messages"][1]["specialist_data"] == '{"mode": "design"}'
    assert forked_conv["messages"][2]["thinking"] == "kept-thinking"
    assert forked_conv["messages"][2]["reflection"] == '{"score": 0.95}'
    assert forked_conv["messages"][2]["detected_lang"] == "html"
