from app.db.repository import TITLE_MAX_CHARS, make_title


def test_a_short_question_is_kept_as_it_is():
    assert make_title("What was revenue?") == "What was revenue?"


def test_whitespace_and_newlines_are_collapsed():
    assert make_title("  hello\n\n   world  ") == "hello world"


def test_a_long_question_is_cut_at_a_word_with_an_ellipsis():
    question = "word " * 30
    title = make_title(question)
    assert title.endswith("…")
    assert len(title) <= TITLE_MAX_CHARS + 1
    assert question.startswith(title[:-1])  # nothing was changed except the cut


def test_a_long_text_without_spaces_is_cut_hard():
    assert make_title("x" * 100) == "x" * TITLE_MAX_CHARS + "…"


def test_a_blank_question_gives_an_empty_title():
    assert make_title("   ") == ""