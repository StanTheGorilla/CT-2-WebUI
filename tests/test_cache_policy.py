from ct1.server.cache_policy import should_clear_kv_cache


def test_should_not_clear_when_slot_is_empty():
    assert should_clear_kv_cache(None, None, []) is False


def test_should_not_clear_within_same_saved_conversation():
    assert should_clear_kv_cache("conv-1", "conv-1", [{"role": "user", "content": "hi"}]) is False


def test_should_clear_when_switching_saved_conversations():
    assert should_clear_kv_cache("conv-1", "conv-2", [{"role": "user", "content": "hi"}]) is True


def test_should_clear_when_starting_brand_new_conversation_after_existing_one():
    assert should_clear_kv_cache("conv-1", None, []) is True
