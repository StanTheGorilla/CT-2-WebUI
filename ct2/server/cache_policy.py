def should_clear_kv_cache(
    cached_conversation_id: str | None,
    incoming_conversation_id: str | None,
    conversation: list[dict] | None,
) -> bool:
    """Decide when the shared llama-server slot should be cleared.

    We keep KV state across turns inside the same conversation so llama-server
    can reuse the prompt prefix. We only clear when switching to a different
    saved conversation, or when starting a brand-new empty conversation after
    another conversation had already occupied the slot.
    """
    if not cached_conversation_id:
        return False

    if incoming_conversation_id:
        return incoming_conversation_id != cached_conversation_id

    return not conversation
