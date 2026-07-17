import tempfile
import os
import pytest
from ct2.memory.conversation_db import ConversationDB


@pytest.fixture
async def db():
    with tempfile.TemporaryDirectory() as d:
        database = ConversationDB(os.path.join(d, "test.db"))
        await database.init()
        yield database
        await database.close()


@pytest.mark.asyncio
async def test_list_conversations_includes_last_route(db):
    cid = await db.create_conversation("Test")
    await db.add_message(cid, "user", "hello", 0)
    await db.add_message(cid, "assistant", "hi", 1, route="ROUTE_CODE")

    convs = await db.list_conversations()
    assert len(convs) == 1
    assert convs[0]["last_route"] == "ROUTE_CODE"


@pytest.mark.asyncio
async def test_list_conversations_last_route_none_when_no_messages(db):
    await db.create_conversation("Empty")
    convs = await db.list_conversations()
    assert convs[0]["last_route"] is None
