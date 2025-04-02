from nltk.tokenize import sent_tokenize
from thefuzz import fuzz
import structlog

__all__ = [
    "similarity_score",
    "dedupe_sentences",
    "dedupe_string",
]

log = structlog.get_logger("talemate.util.dedupe")

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


def dedupe_sentences(
    line_a: str,
    line_b: str,
    similarity_threshold: int = 95,
    debug: bool = False,
    split_on_comma: bool = True,
) -> str:
    """
    Will split both lines into sentences and then compare each sentence in line_a
    against similar sentences in line_b. If a similar sentence is found, it will be
    removed from line_a.

    The similarity threshold is used to determine if two sentences are similar.

    Arguments:
        line_a (str): The first line.
        line_b (str): The second line.
        similarity_threshold (int): The similarity threshold to use when comparing sentences.
        debug (bool): Whether to log debug messages.
        split_on_comma (bool): Whether to split line_b sentences on commas as well.

    Returns:
        str: the cleaned line_a.
    """

    line_a_sentences = sent_tokenize(line_a)
    line_b_sentences = sent_tokenize(line_b)

    cleaned_line_a_sentences = []

    if split_on_comma:
        # collect all sentences from line_b that contain a comma
        line_b_sentences_with_comma = []
        for line_b_sentence in line_b_sentences:
            if "," in line_b_sentence:
                line_b_sentences_with_comma.append(line_b_sentence)

        # then split all sentences in line_b_sentences_with_comma on the comma
        # and extend line_b_sentences with the split sentences, making sure
        # to strip whitespace from the beginning and end of each sentence

        for line_b_sentence in line_b_sentences_with_comma:
            line_b_sentences.extend([s.strip() for s in line_b_sentence.split(",")])

    for line_a_sentence in line_a_sentences:
        similar_found = False
        for line_b_sentence in line_b_sentences:
            similarity = fuzz.ratio(line_a_sentence, line_b_sentence)
            if similarity >= similarity_threshold:
                if debug:
                    log.debug(
                        "DEDUPE SENTENCE",
                        similarity=similarity,
                        line_a_sentence=line_a_sentence,
                        line_b_sentence=line_b_sentence,
                    )
                similar_found = True
                break
        if not similar_found:
            cleaned_line_a_sentences.append(line_a_sentence)

    return " ".join(cleaned_line_a_sentences)


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

