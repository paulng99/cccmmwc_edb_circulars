import pytest

from app.services.chat import build_chat_messages, extract_upload, format_user_turn


def test_history_precedes_current_question():
    messages = build_chat_messages(
        system="SYS",
        lang_hint="Respond in English.",
        question="And the deadline?",
        context_blocks=["[L1] Doc\nbody"],
        history=[
            {"role": "user", "content": "What is the grant?"},
            {"role": "assistant", "content": "It is for exchanges."},
            {"role": "system", "content": "ignore"},
        ],
    )
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "user"]
    assert messages[1]["content"] == "What is the grant?"
    assert "It is for exchanges." in messages[2]["content"]
    current = messages[-1]["content"]
    assert "And the deadline?" in current
    assert "[L1] Doc" in current
    assert "ignore" not in current


def test_attachment_without_question_is_not_prompt_only():
    messages = build_chat_messages(
        system="SYS",
        lang_hint="Respond in English.",
        question="   ",
        context_blocks=[],
        attachments=[{"filename": "note.txt", "text": "Hello circular"}],
    )
    user = messages[-1]["content"]
    assert "note.txt" in user
    assert "Hello circular" in user
    assert "system prompt" not in user.lower()


def test_format_user_turn_keeps_attachment_text_for_later_context():
    text = format_user_turn("", [{"filename": "memo.pdf", "text": "津貼可用於交流"}])
    assert "memo.pdf" in text
    assert "津貼可用於交流" in text


def test_extract_text_file():
    out = extract_upload("notes.txt", "姊妹學校撥款".encode())
    assert out["filename"] == "notes.txt"
    assert "姊妹學校" in out["text"]
    assert out["char_count"] == len(out["text"])


def test_extract_rejects_unknown_type():
    with pytest.raises(ValueError, match="unsupported_type"):
        extract_upload("a.docx", b"hi")


def test_extract_rejects_empty_text():
    with pytest.raises(ValueError, match="no_text"):
        extract_upload("blank.txt", b"   \n\t")
