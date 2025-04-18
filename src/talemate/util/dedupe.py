from nltk.tokenize import sent_tokenize
from thefuzz import fuzz
import structlog
import re # Add import for regex

__all__ = [
    "similarity_score",
    "dedupe_sentences",
    "dedupe_string",
]

log = structlog.get_logger("talemate.util.dedupe")

def _get_core_sentence(sentence: str) -> str:
    """Helper to strip quotes and whitespace."""
    core = sentence.strip().strip('"\'*')
    # Removed regex for speaker prefix handling
    return core

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

def _extract_special_texts(text: str) -> tuple[str, list, list, list]:
    """
    Extract quoted and asterisk-enclosed text, replacing with placeholders.
    
    Arguments:
        text (str): The text to process.
        
    Returns:
        tuple: (text with placeholders, special texts, delimiters, positions)
    """
    special_texts = []
    special_delimiters = []
    special_positions = [] 
    text_with_placeholders = text
    
    patterns = [
        (r'"([^"]*)"', '"'),  # Double quotes
        (r'\*([^*]*)\*', '*')  # Asterisks
    ]
    
    # Locate all matches and record positions
    for pattern, delimiter in patterns:
        matches = list(re.finditer(pattern, text_with_placeholders))
        for match in matches:
            special_text = match.group(0)
            special_texts.append(special_text)
            special_delimiters.append(delimiter)
            special_positions.append((match.start(), match.end()))
    
    # Sort by position for proper replacement
    sorted_indices = sorted(range(len(special_positions)), key=lambda i: special_positions[i][0])
    special_texts = [special_texts[i] for i in sorted_indices]
    special_delimiters = [special_delimiters[i] for i in sorted_indices]
    special_positions = [special_positions[i] for i in sorted_indices]
    
    # Replace with placeholders in reverse order to preserve positions
    for i in range(len(special_texts) - 1, -1, -1):
        placeholder = f"__SPECIAL_TEXT_{i}__"
        start, end = special_positions[i]
        text_with_placeholders = (
            text_with_placeholders[:start] + 
            placeholder + 
            text_with_placeholders[end:]
        )
    
    return text_with_placeholders, special_texts, special_delimiters, special_positions

def _is_sentence_similar(sentence_a: str, candidates: list[str], similarity_threshold: int) -> bool:
    """
    Check if a sentence is similar to any sentence in the candidates list.
    
    Arguments:
        sentence_a (str): The sentence to check.
        candidates (list[str]): List of sentences to compare against.
        similarity_threshold (int): The similarity threshold to use.
        
    Returns:
        bool: True if a similar sentence was found, False otherwise.
    """
    core_a = _get_core_sentence(sentence_a)
    
    for candidate in candidates:
        core_b = _get_core_sentence(candidate)
        similarity = fuzz.ratio(core_a, core_b)
        if similarity >= similarity_threshold:
            return True
    
    return False

def dedupe_sentences(
    text_a: str,
    text_b: str,
    similarity_threshold: int = 95,
    debug: bool = False,
    split_on_comma: bool = True,
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
        split_on_comma (bool): Whether to split text_b sentences on commas as well.

    Returns:
        str: the cleaned text_a.
    """
    # Handle empty inputs early
    if not text_a or not text_b:
        return text_a
        
    # Extract special delimited text and replace with placeholders
    text_a_with_placeholders, special_texts, special_delimiters, _ = _extract_special_texts(text_a)
    
    # Split texts into sentences
    text_a_sentences = sent_tokenize(text_a_with_placeholders)
    text_b_sentences = sent_tokenize(text_b)

    # Process comma-separated phrases in text_b if needed
    if split_on_comma:
        # Add comma-separated phrases to candidates
        comma_phrases = []
        for sentence in text_b_sentences:
            if "," in sentence:
                comma_phrases.extend([s.strip() for s in sentence.split(",")])
        text_b_sentences.extend(comma_phrases)

    # Filter out sentences from text_a that are similar to any in text_b
    kept_sentences = []
    for sentence in text_a_sentences:
        # Keep placeholder sentences for later processing
        if "__SPECIAL_TEXT_" in sentence:
            kept_sentences.append(sentence)
            continue
            
        # Check for similarity with text_b sentences
        if not _is_sentence_similar(sentence, text_b_sentences, similarity_threshold):
            kept_sentences.append(sentence)
        elif debug:
            log.debug("DEDUPE SENTENCE (FOUND)", text_a_sentence=sentence)

    # Join the sentences back
    result = " ".join(kept_sentences)
    
    # Process special texts (quoted or asterisk-enclosed)
    for i, special_text in enumerate(special_texts):
        placeholder = f"__SPECIAL_TEXT_{i}__"
        if placeholder in result:
            delimiter = special_delimiters[i]
            
            # Get inner content without delimiters
            inner_text = special_text[1:-1]
            
            # Recursively dedupe the inner text
            deduped_inner = dedupe_sentences(
                inner_text, 
                text_b, 
                similarity_threshold=similarity_threshold,
                debug=debug,
                split_on_comma=split_on_comma
            )
            
            # Replace placeholder with properly enclosed deduped text
            if deduped_inner:
                result = result.replace(placeholder, f'{delimiter}{deduped_inner}{delimiter}')
            else:
                # If everything was removed, remove the placeholder entirely
                result = result.replace(placeholder, "")
    
    # Clean up the result
    result = re.sub(r' {2,}', ' ', result)  # Normalize whitespace
    result = result.replace('" "', ' ')     # Replace consecutive empty quotes
    result = result.replace('* *', ' ')     # Replace consecutive empty asterisks
    
    return result


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

