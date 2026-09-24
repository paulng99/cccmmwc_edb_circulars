from app.services.chat import build_chat_messages, is_prompt_only


def test_is_prompt_only_when_blank():
    assert is_prompt_only("") is True
    assert is_prompt_only("   ") is True
    assert is_prompt_only("姊妹學校") is False


def test_prompt_only_messages_skip_context_and_retrieval_hints():
    messages = build_chat_messages(
        system="SYS",
        lang_hint="Respond in Traditional Chinese (Hong Kong).",
        question="",
        context_blocks=[],
    )
    assert messages[0]["role"] == "system"
    assert "SYS" in messages[0]["content"]
    user = messages[1]["content"]
    assert "Context:" not in user
    assert "no matching circular" not in user.lower()
    assert "system prompt" in user.lower() or "system instructions" in user.lower()


def test_normal_messages_include_context_and_question():
    messages = build_chat_messages(
        system="SYS",
        lang_hint="Respond in English.",
        question="How to use the grant?",
        context_blocks=["[L1] Doc\nbody"],
    )
    user = messages[1]["content"]
    assert "Context:" in user
    assert "[L1] Doc" in user
    assert "How to use the grant?" in user
