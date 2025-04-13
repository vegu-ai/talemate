import re
import structlog

__all__ = [
    "handle_endofline_special_delimiter",
    "remove_trailing_markers",
    "parse_messages_from_str",
    "strip_partial_sentences",
    "clean_message",
    "clean_dialogue",
    "remove_extra_linebreaks",
    "replace_exposition_markers",
    "ensure_dialog_format",
    "ensure_dialog_line_format",
    "clean_uneven_markers",
    "split_anchor_text",
]

log = structlog.get_logger("talemate.util.dialogue")


def handle_endofline_special_delimiter(content: str) -> str:
    # END-OF-LINE is a custom delimter that can exist 0 to n times
    # it should split total_result on the last one, take the left side
    # then remove all remaining END-OF-LINE from the left side
    # then remove all leading and trailing whitespace

    # sometimes the AI will not generate END-OF-LINE exactly
    # but it will be missing one or more spaces, so we need to
    # to normalize to END-OF-LINE before we can split on it

    content = content.split("END-OF-LINE")[0].strip()

    return content


def remove_trailing_markers(content: str, pair_markers:list[str] = None, enclosure_markers:list[str] = None) -> str:
    """
    Will check for uneven balance in the specified markers
    and remove the trailing ones
    """
    
    if not pair_markers:
        pair_markers = ['"', '*']
        
    if not enclosure_markers:
        enclosure_markers = ['(', '[', '{']
    
    content = content.rstrip()
    
    for marker in pair_markers:
        if content.count(marker) % 2 == 1 and content.endswith(marker):
            content = content[:-1]
            content = content.rstrip()
            
    for marker in enclosure_markers:
        if content.endswith(marker):
            content = content[:-1]
            content = content.rstrip()
            
    return content.rstrip()

def parse_messages_from_str(string: str, names: list[str]) -> list[str]:
    """
    Given a big string containing raw chat history, this function attempts to
    parse it out into a list where each item is an individual message.
    """
    sanitized_names = [re.escape(name) for name in names]

    speaker_regex = re.compile(rf"^({'|'.join(sanitized_names)}): ?", re.MULTILINE)

    message_start_indexes = []
    for match in speaker_regex.finditer(string):
        message_start_indexes.append(match.start())

    if len(message_start_indexes) < 2:
        # Single message in the string.
        return [string.strip()]

    prev_start_idx = message_start_indexes[0]
    messages = []

    for start_idx in message_start_indexes[1:]:
        message = string[prev_start_idx:start_idx].strip()
        messages.append(message)
        prev_start_idx = start_idx

    # add the last message
    messages.append(string[prev_start_idx:].strip())

    return messages

def strip_partial_sentences(text: str) -> str:
    """
    Removes any unfinished sentences from the end of the input text.

    This new version works backwards and doesnt destroy string formatting (newlines etc.)

    Args:
        text (str): The input text to be cleaned.

    Returns:
        str: The cleaned text.
    """
    sentence_endings = [".", "!", "?", '"', "*"]

    # loop backwards through `text` until a sentence ending is found

    for i in range(len(text) - 1, -1, -1):
        if text[i] in sentence_endings:
            return remove_trailing_markers(text[: i + 1])

    return text

def clean_message(message: str) -> str:
    message = message.strip()
    message = re.sub(r" +", " ", message)
    return message


def clean_dialogue(dialogue: str, main_name: str) -> str:

    cleaned = []

    if not dialogue.startswith(main_name):
        dialogue = f"{main_name}: {dialogue}"

    for line in dialogue.split("\n"):

        if not cleaned:
            cleaned.append(line)
            continue

        if line.startswith(f"{main_name}: "):
            cleaned.append(line[len(main_name) + 2 :])
            continue

        # if line is all capitalized
        # this is likely a new speaker in movie script format, and we
        # bail
        if line.strip().isupper():
            break

        if ":" not in line:
            cleaned.append(line)
            continue

    return clean_message(strip_partial_sentences("\n".join(cleaned)))


def remove_extra_linebreaks(s: str) -> str:
    """
    Removes extra line breaks from a string.

    Parameters:
        s (str): The input string.

    Returns:
        str: The string with extra line breaks removed.
    """
    return re.sub(r"\n{3,}", "\n\n", s)


def replace_exposition_markers(s: str) -> str:
    s = s.replace("(", "*").replace(")", "*")
    s = s.replace("[", "*").replace("]", "*")
    return s


def ensure_dialog_format(line: str, talking_character: str = None, formatting:str = "md") -> str:
    # if "*" not in line and '"' not in line:
    #    if talking_character:
    #        line = line[len(talking_character)+1:].lstrip()
    #        return f"{talking_character}: \"{line}\""
    #    return f"\"{line}\""
    #


    if talking_character:
        line = line[len(talking_character) + 1 :].lstrip()
    eval_line = line.strip()
    
    if eval_line.startswith('*') and eval_line.endswith('*'):
        if line.count("*") == 2 and not line.count('"'):
            return f"{talking_character}: {line}" if talking_character else line

    if eval_line.startswith('"') and eval_line.endswith('"'):
        if line.count('"') == 2 and not line.count('*'):
            return f"{talking_character}: {line}" if talking_character else line

    lines = []

    has_asterisks = "*" in line
    has_quotes = '"' in line

    default_wrap = None
    if has_asterisks and not has_quotes:
        default_wrap = '"'
    elif not has_asterisks and has_quotes:
        default_wrap = "*"

    for _line in line.split("\n"):
        try:
            _line = ensure_dialog_line_format(_line, default_wrap=default_wrap)
        except Exception as exc:
            log.error(
                "ensure_dialog_format",
                msg="Error ensuring dialog line format",
                line=_line,
                exc_info=exc,
            )
            pass

        lines.append(_line)

    if len(lines) > 1:
        line = "\n".join(lines)
    else:
        line = lines[0]

    if talking_character:
        line = f"{talking_character}: {line}"

    if formatting != "md":
        line = line.replace("*", "")

    return line


def ensure_dialog_line_format(line: str, default_wrap: str = None) -> str:
    """
    a Python function that standardizes the formatting of dialogue and action/thought
    descriptions in text strings. This function is intended for use in a text-based
    game where spoken dialogue is encased in double quotes (" ") and actions/thoughts are
    encased in asterisks (* *). The function must correctly format strings, ensuring that
    each spoken sentence and action/thought is properly encased
    """

    i = 0

    segments = []
    segment = None
    segment_open = None
    last_classifier = None

    line = line.strip()

    line = line.replace('"*', '"').replace('*"', '"')

    line = line.replace('*, "', '* "')
    line = line.replace('*. "', '* "')
    line = line.replace("*.", ".*")

    # if the line ends with a whitespace followed by a classifier, strip both from the end
    # as this indicates the remnants of a partial segment that was removed.

    if line.endswith(" *") or line.endswith(' "'):
        line = line[:-2]

    if "*" not in line and '"' not in line and default_wrap and line:
        # if the line is not wrapped in either asterisks or quotes, wrap it in the default
        # wrap, if specified - when it's specialized it means the line was split and we
        # found the other wrap in one of the segments.
        return f"{default_wrap}{line}{default_wrap}"

    for i in range(len(line)):
        c = line[i]

        # print("segment_open", segment_open)
        # print("segment", segment)

        if c in ['"', "*"]:
            if segment_open == c:
                # open segment is the same as the current character
                # closing
                segment_open = None
                segment += c
                segments += [segment.strip()]
                segment = None
                last_classifier = c
            elif segment_open is not None and segment_open != c:
                # open segment is not the same as the current character
                # opening - close the current segment and open a new one

                # if we are at the last character we append the segment
                if i == len(line) - 1 and segment.strip():
                    segment += c
                    segments += [segment.strip()]
                    segment_open = None
                    segment = None
                    last_classifier = c
                    continue

                segments += [segment.strip()]
                segment_open = c
                segment = c
                last_classifier = c
            elif segment_open is None:
                # we're opening a segment
                segment_open = c
                segment = c
                last_classifier = c
        else:
            if segment_open is None and c and c != " ":
                if last_classifier == '"':
                    segment_open = "*"
                    segment = f"{segment_open}{c}"
                elif last_classifier == "*":
                    segment_open = '"'
                    segment = f"{segment_open}{c}"
                else:
                    segment_open = "unclassified"
                    segment = c
            elif segment:
                segment += c

    if segment is not None:
        if segment.strip().strip("*").strip('"'):
            segments += [segment.strip()]

    for i in range(len(segments)):
        segment = segments[i]
        if segment in ['"', "*"]:
            if i > 0:
                prev_segment = segments[i - 1]
                if prev_segment and prev_segment[-1] not in ['"', "*"]:
                    segments[i - 1] = f"{prev_segment}{segment}"
                    segments[i] = ""
                    continue

    for i in range(len(segments)):
        segment = segments[i]

        if not segment:
            continue

        if segment[0] == "*" and segment[-1] != "*":
            segment += "*"
        elif segment[-1] == "*" and segment[0] != "*":
            segment = "*" + segment
        elif segment[0] == '"' and segment[-1] != '"':
            segment += '"'
        elif segment[-1] == '"' and segment[0] != '"':
            segment = '"' + segment
        elif segment[0] in ['"', "*"] and segment[-1] == segment[0]:
            continue

        segments[i] = segment

    for i in range(len(segments)):
        segment = segments[i]
        if not segment or segment[0] in ['"', "*"]:
            continue

        prev_segment = segments[i - 1] if i > 0 else None
        next_segment = segments[i + 1] if i < len(segments) - 1 else None

        if prev_segment and prev_segment[-1] == '"':
            segments[i] = f"*{segment}*"
        elif prev_segment and prev_segment[-1] == "*":
            segments[i] = f'"{segment}"'
        elif next_segment and next_segment[0] == '"':
            segments[i] = f"*{segment}*"
        elif next_segment and next_segment[0] == "*":
            segments[i] = f'"{segment}"'

    for i in range(len(segments)):
        segments[i] = clean_uneven_markers(segments[i], '"')
        segments[i] = clean_uneven_markers(segments[i], "*")

    final = " ".join(segment for segment in segments if segment).strip()
    final = final.replace('","', "").replace('"."', "")
    return final


def clean_uneven_markers(chunk: str, marker: str):
    # if there is an uneven number of quotes, remove the last one if its
    # at the end of the chunk. If its in the middle, add a quote to the endc
    count = chunk.count(marker)

    if count % 2 == 1:
        if chunk.endswith(marker):
            chunk = chunk[:-1]
        elif chunk.startswith(marker):
            chunk = chunk[1:]
        elif count == 1:
            chunk = chunk.replace(marker, "")
        else:
            chunk += marker

    return chunk


def split_anchor_text(text: str, anchor_length: int = 10) -> tuple[str, str]:
    """
    Splits input text into two parts: non-anchor and anchor.
    The anchor is the last `anchor_length` words of the text.
    
    Args:
        text (str): The input text to be split
        anchor_length (int): Number of words to use as anchor
        
    Returns:
        tuple[str, str]: A tuple containing (non_anchor, anchor)
    """
    if not text:
        return "", ""
        
    # Split the input into words
    words = text.split()
    
    # If it's just one word, put it in the anchor
    if len(words) == 1:
        return "", text
    
    # Get the anchor (last anchor_length words)
    if len(words) > anchor_length:
        anchor = ' '.join(words[-anchor_length:])
        non_anchor = ' '.join(words[:-anchor_length])
    else:
        # For text with words <= anchor_length (but more than 1 word), split evenly
        mid_point = len(words) // 2
        non_anchor = ' '.join(words[:mid_point])
        anchor = ' '.join(words[mid_point:])
        
    return non_anchor, anchor