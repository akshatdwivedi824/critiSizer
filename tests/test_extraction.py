from critisizer.evidence.text import clean_paragraph, make_excerpt
from critisizer.scoring.sentences import split_sentences


def test_a_caption_glued_to_a_sentence_is_separated():
    text = (
        "Queues formed again after the Prime Minister announced demonetisation."
        "People standing in long queues outside banks waited for hours."
    )
    excerpt = make_excerpt("Demonetisation queues", text, "demonetisation")
    assert "demonetisation. People standing" in excerpt
    sentences = split_sentences(excerpt)
    assert any(s.startswith("People standing") for s in sentences)


def test_a_closing_quote_before_the_next_sentence_is_separated():
    assert clean_paragraph('He said "it failed."The ministry disagreed.') == (
        'He said "it failed." The ministry disagreed.'
    )


def test_ordinary_text_is_left_alone():
    line = "Rs.500 notes and the U.S. dollar were discussed at length in Node.js talks."
    assert clean_paragraph(line) == line


def test_photo_credit_lines_and_tails_are_removed():
    text = (
        "Photo: Customers wait outside a bank branch in Mumbai during demonetisation.\n"
        "Demonetisation hurt small traders across the country very badly in 2016. "
        "Photo: PTI/Shahbaz Khan"
    )
    excerpt = make_excerpt("Demonetisation", text, "demonetisation")
    assert "Photo" not in excerpt
    assert "hurt small traders" in excerpt


def test_boilerplate_lines_are_dropped():
    for line in (
        "Please enable JavaScript and cookies in your browser to continue reading.",
        "Also read: how the scheme was announced in the last budget session.",
        "Subscribe to continue reading this article and all our premium reports.",
    ):
        assert clean_paragraph(line) is None


def test_a_page_that_only_shares_the_headline_is_not_an_excerpt():
    junk = "Please enable JavaScript and cookies in your browser to continue reading."
    assert make_excerpt("Demonetisation explained", junk, "demonetisation") is None


def test_a_title_match_still_needs_a_body_mention():
    text = "A long paragraph about something else entirely with no policy in it."
    assert make_excerpt("Agnipath explained", text, "Agnipath") is None


def test_initials_do_not_split_a_name_in_two():
    text = (
        "The bench of Justices J.B. Pardiwala and Manoj Misra dismissed the appeal "
        "on Monday."
    )
    assert split_sentences(text) == [text]


def test_titles_like_mr_do_not_end_a_sentence():
    text = "Mr. Sharma told the committee that the rollout had been rushed badly."
    assert split_sentences(text) == [text]


def test_real_sentence_ends_still_split():
    text = (
        "The court struck down the provision after a long hearing. "
        "The government said it would appeal the ruling within the month."
    )
    assert len(split_sentences(text)) == 2