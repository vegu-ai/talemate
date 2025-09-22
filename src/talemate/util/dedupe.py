from nltk.tokenize import sent_tokenize
from thefuzz import fuzz
import structlog
import pydantic
import re  # Add import for regex
from typing import Callable

__all__ = [
    "similarity_score",
    "similarity_matches",
    "dedupe_sentences",
    "dedupe_sentences_from_matches",
    "dedupe_string",
    "split_sentences_on_comma",
    "compile_sentences_to_length",
    "compile_text_to_sentences",
]

log = structlog.get_logger("talemate.util.dedupe")

SPECIAL_MARKERS = ["*", '"']


class SimilarityMatch(pydantic.BaseModel):
    original: str
    matched: str
    similarity: float
    left_neighbor: str | None = None
    right_neighbor: str | None = None

    def ln_startswith(self, marker: str) -> bool:
        return self.left_neighbor and self.left_neighbor.startswith(marker)

    def rn_startswith(self, marker: str) -> bool:
        return self.right_neighbor and self.right_neighbor.startswith(marker)

    def __hash__(self) -> int:
        return hash(self.original)

    def __eq__(self, other):
        if not isinstance(other, SimilarityMatch):
            return False
        return self.original == other.original


def similarity_score(
    line: str, lines: list[str], similarity_threshold: int = 95
) -> tuple[bool, int, str]:
    """
    Checks if a line is similar to any of the lines in the list of lines.

    Arguments:
        line (str): The line to check.
        lines (list): The list of lines to check against.
        threshold (int): The similarity threshold to use when comparing lines.

    Returns:
        bool: Whether a similar line was found.
        int: The similarity score of the line. If no similar line was found, the highest similarity score is returned.
        str: The similar line that was found. If no similar line was found, None is returned.
    """

    highest_similarity = 0

    for existing_line in lines:
        similarity = fuzz.ratio(line, existing_line)
        highest_similarity = max(highest_similarity, similarity)
        # print("SIMILARITY", similarity, existing_line[:32]+"...")
        if similarity >= similarity_threshold:
            return True, similarity, existing_line

    return False, highest_similarity, None


def compile_text_to_sentences(text: str) -> list[tuple[str, str]]:
    """
    Compile text into sentences.

    Returns a list of tuples were the first element is the original sentence and the second element is the prepared sentence that will be used for similarity comparison.
    """

    sentences = sent_tokenize(text)

    results = []

    for sentence in sentences:
        results.append((sentence, sentence.strip("".join(SPECIAL_MARKERS))))

    return results


def compile_sentences_to_length(sentences: list[str], length: int) -> list[str]:
    """Will join sentences to chunks of the given length

    Args:
        sentences (list[str]): The sentences to join
        length (int): The length of the chunks

    Returns:
        list[str]: The joined sentences
    """

    results = []
    current_chunk = ""
    for sentence in sentences:
        if len(current_chunk) + len(sentence) > length:
            results.append(current_chunk)
            current_chunk = ""
        current_chunk += sentence + " "
    if current_chunk:
        results.append(current_chunk)
    return results


def split_sentences_on_comma(sentences: list[str]) -> list[str]:
    """
    Split sentences on commas.
    """
    results = []
    for sentence in sentences:
        for part in sentence.split(","):
            results.append(part.strip())
    return results


def similarity_matches(
    text_a: str,
    text_b: str,
    similarity_threshold: int = 95,
    min_length: int | None = None,
    split_on_comma: bool = False,
) -> list[SimilarityMatch]:
    """
    Returns a list of similarity matches between two texts.

    Arguments:
        text_a (str): The first text.
        text_b (str): The second text.
        similarity_threshold (int): The similarity threshold to use when comparing sentences.
        min_length (int): The minimum length of a sentence to be considered for deduplication.
            Shorter sentences are skipped. If None, all sentences are considered.
        split_on_comma (bool): Whether to split sentences on commas. When true if the whole sentence does NOT trigger a similarity match,
            the sentence will be split on commas and each comma will be checked for similarity.

    Returns:
        list: A list of similarity matches.
    """

    sentences_a = compile_text_to_sentences(text_a)
    sentences_b = compile_text_to_sentences(text_b)

    matches = []
    left_neighbor = None
    right_neighbor = None
    for idx, (sentence_a, sentence_a_prepared) in enumerate(sentences_a):
        left_neighbor = sentences_a[idx - 1][0] if idx > 0 else None
        right_neighbor = sentences_a[idx + 1][0] if idx < len(sentences_a) - 1 else None
        if min_length and len(sentence_a) < min_length:
            continue
        for sentence_b, sentence_b_prepared in sentences_b:
            if min_length and len(sentence_b) < min_length:
                continue
            similarity = fuzz.ratio(sentence_a_prepared, sentence_b_prepared)
            if similarity >= similarity_threshold:
                matches.append(
                    SimilarityMatch(
                        original=sentence_a,
                        matched=sentence_b,
                        similarity=similarity,
                        left_neighbor=left_neighbor,
                        right_neighbor=right_neighbor,
                    )
                )
                break

            if split_on_comma:
                prev_comma_a = None
                parts_a = sentence_a.split(",")
                parts_b = sentence_b.split(",")
                for idx_a, comma_a in enumerate(parts_a):
                    if min_length and len(comma_a) < min_length:
                        continue
                    for comma_b in parts_b:
                        if min_length and len(comma_b) < min_length:
                            continue
                        similarity = fuzz.ratio(comma_a.strip(), comma_b.strip())
                        if similarity >= similarity_threshold:
                            matches.append(
                                SimilarityMatch(
                                    original=comma_a,
                                    matched=comma_b,
                                    similarity=similarity,
                                    left_neighbor=prev_comma_a,
                                    right_neighbor=parts_a[idx_a + 1]
                                    if idx_a < len(parts_a) - 1
                                    else None,
                                )
                            )
                            break

    return matches


def dedupe_sentences(
    text_a: str,
    text_b: str,
    similarity_threshold: int = 95,
    debug: bool = False,
    on_dedupe: Callable | None = None,
    min_length: int | None = None,
    split_on_comma: bool = False,
) -> str:
    """
    Will split both texts into sentences and then compare each sentence in text_a
    against similar sentences in text_b. If a similar sentence is found, it will be
    removed from text_a.

    The similarity threshold is used to determine if two sentences are similar.

    Arguments:
        text_a (str): The first text.
        text_b (str): The second text.
        similarity_threshold (int): The similarity threshold to use when comparing sentences.
        debug (bool): Whether to log debug messages.
        on_dedupe (Callable): A callback function that is called when a duplicate is found.
        split_on_comma (bool): Whether to split text_b sentences on commas as well.
        min_length (int): The minimum length of a sentence to be considered for deduplication. Shorter sentences are skipped. If None, all sentences are considered.
    Returns:
        str: the cleaned text_a.
    """

    # find similarity matches
    matches = similarity_matches(
        text_a, text_b, similarity_threshold, min_length, split_on_comma
    )

    return dedupe_sentences_from_matches(
        text_a, matches, on_dedupe=on_dedupe, debug=debug
    )


def dedupe_sentences_from_matches(
    text_a: str,
    matches: list[SimilarityMatch],
    on_dedupe: Callable | None = None,
    debug: bool = False,
) -> str:
    """
    Dedupe sentences using fuzzy matching.
    """
    # replace duplicates with empty strings
    # if the duplicate started or ended with a special marker, replace with
    # the marker (replace with both the start and end marker if both are present)
    for match in matches:
        replace = ""
        original = match.original

        # handle special markers (asterisks and quotes)
        for special_marker in SPECIAL_MARKERS:
            # we are looking for markers at the end or beginning of the sentence
            # at an odd number of occurences
            #
            # those mean the sentence is part of a markup and the symbol
            # must be carried over to the replacement so the markup remains
            # complete
            part_of_marker = original.startswith(special_marker) or original.endswith(
                special_marker
            )

            if not part_of_marker:
                continue

            # if not odd number of special markers, skip
            # an even number means the markup is fully contained within the sentence
            if original.count(special_marker) % 2 == 0:
                continue

            # if the sentence is part of a markup, we need to carry over the marker
            # to the replacement so the markup remains complete
            replace = special_marker

            # balancing logic - some edge cases to handle issues
            # with whitespace and special markers
            if original.startswith(special_marker):
                if match.ln_startswith(special_marker):
                    replace = f"{special_marker} "
                elif match.rn_startswith(special_marker):
                    replace = ""
                    original = f"{original}{special_marker}"
            elif original.endswith(special_marker):
                if match.rn_startswith(special_marker):
                    original = f"{original} "

        match_both = None
        match_left = None
        match_right = None

        # handle whitespace between neighbors
        if match.left_neighbor and match.right_neighbor:
            pattern_both = (
                re.escape(match.left_neighbor)
                + r"(\s+)"
                + re.escape(original)
                + r"(\s+)"
                + re.escape(match.right_neighbor)
            )
            match_both = re.search(pattern_both, text_a)
        if match.left_neighbor:
            pattern_left = (
                re.escape(match.left_neighbor) + r"(\s+)" + re.escape(original)
            )
            match_left = re.search(pattern_left, text_a)
        if match.right_neighbor:
            pattern_right = (
                re.escape(original) + r"(\s+)" + re.escape(match.right_neighbor)
            )
            match_right = re.search(pattern_right, text_a)

        if match.left_neighbor and match.right_neighbor and match_both:
            whitespace = match_both.group(1)
            original = f"{whitespace}{original}"
        elif match.left_neighbor and match_left:
            whitespace = match_left.group(1)
            original = f"{whitespace}{original}"
        elif match.right_neighbor and match_right:
            whitespace = match_right.group(1)
            original = f"{original}{whitespace}"

        # Dedupe the original sentence by replacing it with the replacement
        # which is either an empty string or a special marker (* or ")
        text_a = text_a.replace(original, replace)

        # call the on_dedupe callback if it is provided
        if on_dedupe:
            on_dedupe(match)
        if debug:
            log.debug(
                "DEDUPE",
                similarity=match.similarity,
                original=match.original,
                matched=match.matched,
            )

        # final clean up
        for special_marker in SPECIAL_MARKERS:
            # idential markers with a space between can just be joined.
            text_a = text_a.replace(f"{special_marker} {special_marker}", " ")

    return text_a.strip()


def dedupe_string(
    s: str, min_length: int = 32, similarity_threshold: int = 95, debug: bool = False
) -> str:
    """
    Removes duplicate lines from a string going from the bottom up, excluding content within code blocks.
    Code blocks are identified by lines starting with triple backticks.

    Arguments:
        s (str): The input string.
        min_length (int): The minimum length of a line to be checked for duplicates.
        similarity_threshold (int): The similarity threshold to use when comparing lines.
        debug (bool): Whether to log debug messages.

    Returns:
        str: The deduplicated string.
    """
    lines = s.split("\n")
    deduped = []
    current_in_codeblock = False
    existing_in_codeblock = False

    for line in reversed(lines):
        stripped_line = line.strip()

        # Check for code block markers in current line
        if stripped_line.startswith("```"):
            current_in_codeblock = not current_in_codeblock
            deduped.append(line)
            continue

        # Skip deduping for lines in code blocks
        if current_in_codeblock:
            deduped.append(line)
            continue

        if len(stripped_line) > min_length:
            similar_found = False
            existing_in_codeblock = False

            for existing_line in deduped:
                # Track code block state for existing lines
                if existing_line.strip().startswith("```"):
                    existing_in_codeblock = not existing_in_codeblock
                    continue

                # Skip comparing if either line is in a code block
                if existing_in_codeblock:
                    continue

                similarity = fuzz.ratio(stripped_line, existing_line.strip())
                if similarity >= similarity_threshold:
                    similar_found = True
                    if debug:
                        log.debug(
                            "DEDUPE",
                            similarity=similarity,
                            line=line,
                            existing_line=existing_line,
                        )
                    break
            if not similar_found:
                deduped.append(line)
        else:
            deduped.append(line)

    return "\n".join(reversed(deduped))
