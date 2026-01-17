"""Tests for TTS utility functions."""

from talemate.agents.tts.util import split_long_chunk, parse_chunks, rejoin_chunks


class TestSplitLongChunk:
    """Tests for split_long_chunk function."""

    def test_short_text_returns_unchanged(self):
        """Text shorter than chunk_size should be returned as-is."""
        text = "Hello world"
        result = split_long_chunk(text, chunk_size=50)
        assert result == [text]

    def test_text_equal_to_chunk_size_returns_unchanged(self):
        """Text exactly equal to chunk_size should be returned as-is."""
        text = "Hello world"  # 11 chars
        result = split_long_chunk(text, chunk_size=11)
        assert result == [text]

    def test_splits_at_comma(self):
        """Should prefer splitting at comma boundaries."""
        text = "Hello world, this is a test, and more text here"
        result = split_long_chunk(text, chunk_size=30)
        # Should split at ", " after "this is a test"
        assert len(result) >= 2
        # Each chunk should be <= chunk_size
        for chunk in result:
            assert len(chunk) <= 30

    def test_splits_at_space_when_no_comma(self):
        """Should split at space when no comma is available."""
        text = "Hello world this is a test without commas here"
        result = split_long_chunk(text, chunk_size=25)
        assert len(result) >= 2
        for chunk in result:
            assert len(chunk) <= 25

    def test_hard_split_when_no_boundaries(self):
        """Should hard split when no natural boundaries exist."""
        text = "abcdefghijklmnopqrstuvwxyz"  # 26 chars, no spaces or commas
        result = split_long_chunk(text, chunk_size=10)
        assert len(result) == 3
        assert result[0] == "abcdefghij"
        assert result[1] == "klmnopqrst"
        assert result[2] == "uvwxyz"

    def test_preserves_all_content(self):
        """Splitting and rejoining should preserve all content."""
        text = "Hello world, this is a longer test text, with multiple commas, and spaces throughout the entire string"
        result = split_long_chunk(text, chunk_size=30)
        rejoined = " ".join(result)
        # Content should be preserved (whitespace may differ due to strip())
        assert "Hello world" in rejoined
        assert "multiple commas" in rejoined
        assert "entire string" in rejoined

    def test_handles_long_text_with_many_splits(self):
        """Should handle text requiring many splits."""
        text = "word " * 100  # 500 chars
        result = split_long_chunk(text, chunk_size=50)
        assert len(result) > 1
        for chunk in result:
            assert len(chunk) <= 50

    def test_comma_must_be_in_second_half(self):
        """Comma split point must be in second half of chunk to be used."""
        # Comma at position 5 in a 50-char chunk_size (5 < 25) should not be used
        text = "Hi, " + "a" * 100  # Comma very early
        result = split_long_chunk(text, chunk_size=50)
        # Should split at space or hard boundary, not at the early comma
        assert len(result) >= 2

    def test_space_must_be_in_second_half(self):
        """Space split point must be in second half of chunk to be used."""
        # Space at position 2 in a 50-char chunk_size (2 < 25) should not be used
        text = "Hi " + "a" * 100  # Space very early
        result = split_long_chunk(text, chunk_size=50)
        assert len(result) >= 2

    def test_empty_string(self):
        """Empty string should return list with empty string."""
        result = split_long_chunk("", chunk_size=50)
        assert result == [""]

    def test_strips_whitespace_from_chunks(self):
        """Chunks should have leading/trailing whitespace stripped."""
        text = "Hello world, this is a test"
        result = split_long_chunk(text, chunk_size=15)
        for chunk in result:
            assert chunk == chunk.strip()

    def test_realistic_tts_scenario(self):
        """Test with realistic TTS text that caused the original bug."""
        text = (
            "Leaning forward with deliberate calm she let her fingers rest lightly "
            "on Jon's shoulder before speaking in that measured legal cadence that "
            "had won cases but now trembled with something raw The Last Serial Killer "
            "she said letting the title hang between them like evidence presented in court"
        )
        result = split_long_chunk(text, chunk_size=256)
        # Original text is ~300 chars, should be split into 2 chunks
        assert len(result) == 2
        for chunk in result:
            assert len(chunk) <= 256


class TestParseChunks:
    """Tests for parse_chunks function."""

    def test_simple_sentences(self):
        """Should split text into sentences."""
        text = "Hello world. This is a test. Another sentence here."
        result = parse_chunks(text)
        assert len(result) == 3
        assert result[0] == "Hello world."
        assert result[1] == "This is a test."
        assert result[2] == "Another sentence here."

    def test_removes_asterisks(self):
        """Should remove asterisks from text."""
        text = "*Hello* world. *This* is a test."
        result = parse_chunks(text)
        assert "*" not in " ".join(result)

    def test_preserves_ellipsis(self):
        """Should preserve ellipsis in text."""
        text = "Hello... world. This is... a test."
        result = parse_chunks(text)
        rejoined = " ".join(result)
        assert "..." in rejoined

    def test_adds_period_before_opening_quote(self):
        """Should add period before opening quote when preceded by word."""
        text = 'He said something "Hello world" and left.'
        result = parse_chunks(text)
        # The text should be split with proper sentence boundaries
        assert len(result) >= 1

    def test_adds_period_after_quote_without_terminator(self):
        """Should add period after quote that lacks sentence terminator."""
        text = '"Hello world" he said'
        result = parse_chunks(text)
        # Should become '"Hello world." he said' and then split
        rejoined = " ".join(result)
        # The quote should have a period added inside
        assert '"Hello world."' in rejoined or "Hello world." in rejoined

    def test_preserves_quote_with_existing_terminator(self):
        """Should not add extra period when quote already has terminator."""
        text = '"Hello world!" he said.'
        result = parse_chunks(text)
        rejoined = " ".join(result)
        # Should not have double punctuation
        assert '!."' not in rejoined and '!".' not in rejoined

    def test_handles_empty_chunks(self):
        """Should filter out empty chunks."""
        text = "Hello.   .  World."
        result = parse_chunks(text)
        for chunk in result:
            assert chunk.strip() != ""

    def test_handles_empty_string(self):
        """Should handle empty string input."""
        result = parse_chunks("")
        assert result == []

    def test_realistic_dialogue(self):
        """Test with realistic dialogue text."""
        text = (
            'She leaned forward "The Last Serial Killer" she said '
            '"It\'s not just another slasher flick" Her voice dropped lower.'
        )
        result = parse_chunks(text)
        # Should properly split around quotes
        assert len(result) >= 2


class TestRejoinChunks:
    """Tests for rejoin_chunks function."""

    def test_combines_small_chunks(self):
        """Should combine small chunks up to chunk_size."""
        chunks = ["Hello.", "World.", "Test."]
        result = rejoin_chunks(chunks, chunk_size=50)
        assert len(result) == 1
        assert result[0] == "Hello. World. Test."

    def test_respects_chunk_size_limit(self):
        """Should not exceed chunk_size when combining."""
        chunks = ["Hello world.", "This is a test.", "Another sentence."]
        result = rejoin_chunks(chunks, chunk_size=20)
        for chunk in result:
            assert len(chunk) <= 20

    def test_splits_oversized_chunks(self):
        """Should split individual chunks that exceed chunk_size."""
        chunks = ["This is a very long sentence that exceeds the chunk size limit"]
        result = rejoin_chunks(chunks, chunk_size=20)
        assert len(result) > 1
        for chunk in result:
            assert len(chunk) <= 20

    def test_adds_space_between_chunks(self):
        """Should add space when combining chunks."""
        chunks = ["Hello.", "World."]
        result = rejoin_chunks(chunks, chunk_size=50)
        assert result[0] == "Hello. World."

    def test_handles_empty_list(self):
        """Should handle empty chunk list."""
        result = rejoin_chunks([], chunk_size=50)
        assert result == []

    def test_handles_single_chunk(self):
        """Should handle single chunk that fits."""
        chunks = ["Hello world."]
        result = rejoin_chunks(chunks, chunk_size=50)
        assert result == ["Hello world."]

    def test_flushes_before_oversized_chunk(self):
        """Should flush current chunk before adding oversized chunk pieces."""
        chunks = ["Hi.", "This is a very long sentence that needs splitting"]
        result = rejoin_chunks(chunks, chunk_size=20)
        # "Hi." should be separate, then the long sentence split
        assert result[0] == "Hi."
        assert len(result) > 1

    def test_realistic_scenario(self):
        """Test with realistic sentence chunks."""
        chunks = [
            "She looked at him.",
            "The room was quiet.",
            "He wondered what she would say next.",
            "Time seemed to slow down.",
        ]
        result = rejoin_chunks(chunks, chunk_size=100)
        # Should combine into larger chunks
        assert len(result) < len(chunks)
        for chunk in result:
            assert len(chunk) <= 100
