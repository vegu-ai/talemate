import base64
import io
import json
import re
import textwrap
import structlog
import isodate
import datetime
from typing import List
from thefuzz import fuzz
from colorama import Back, Fore, Style, init
from PIL import Image
from nltk.tokenize import sent_tokenize

from talemate.scene_message import SceneMessage
log = structlog.get_logger("talemate.util")

# Initialize colorama
init(autoreset=True)

def fix_unquoted_keys(s):
    unquoted_key_pattern = r"(?<!\\)(?:(?<=\{)|(?<=,))\s*(\w+)\s*:"
    fixed_string = re.sub(
        unquoted_key_pattern, lambda match: f' "{match.group(1)}":', s
    )
    return fixed_string


def parse_messages_from_str(string: str, names: List[str]) -> List[str]:
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


def serialize_chat_history(history: List[str]) -> str:
    """Given a structured chat history object, collapses it down to a string."""
    return "\n".join(history)


def wrap_text(text, character_name, color, width=80):
    """
    Wrap the text at the given width, with optional color for the character name.
    :param text: The text to wrap.
    :param width: The maximum width of each line.
    :param character_name: The character's name to color.
    :param color: The color to apply to the character's name.
    :return: The wrapped text as a string.
    """
    # Split text into lines to maintain existing line breaks
    lines = text.split("\n")

    wrapped_lines = []

    for i, line in enumerate(lines):
        wrapper = textwrap.TextWrapper(width=width)
        # Apply the indent only to the lines that are not the first lines after a line break

        if line.startswith(f"{character_name}: "):
            wrapper.subsequent_indent = " " * (len(character_name) + 2)
        else:
            wrapper.initial_indent = " " * (len(character_name) + 2)
            wrapper.subsequent_indent = " " * (len(character_name) + 2)

        # Wrap each line separately maintaining existing line breaks
        wrapped_line = wrapper.fill(line)

        colored_character_name = colored_text(character_name + ": ", color)

        wrapped_line = wrapped_line.replace(
            character_name + ": ", colored_character_name, 1
        )

        wrapped_lines.append(wrapped_line)

    # Join the wrapped lines to form the final output
    final_text = "\n".join(wrapped_lines)

    # Color emotes on the final text
    final_text = color_emotes(final_text)

    return final_text


def cull_history_list(strings, max_length, buffer):
    removed_strings = []
    total_length = sum(len(s) for s in strings)
    excess_length = total_length - max_length

    if excess_length >= buffer:
        while excess_length > 0:
            removed_string = strings.pop(0)
            removed_strings.append(removed_string)
            excess_length -= len(removed_string)

    return "\n".join(removed_strings), total_length


def colored_text(text, color):
    color_map = {
        "red": Fore.RED,
        "green": Fore.GREEN,
        "blue": Fore.BLUE,
        "cyan": Fore.CYAN,
        "magenta": Fore.MAGENTA,
        "yellow": Fore.YELLOW,
        "white": Fore.WHITE,
        "black": Fore.BLACK,
        "light_red": Fore.LIGHTRED_EX,
        "light_green": Fore.LIGHTGREEN_EX,
        "light_blue": Fore.LIGHTBLUE_EX,
        "light_cyan": Fore.LIGHTCYAN_EX,
        "light_magenta": Fore.LIGHTMAGENTA_EX,
        "light_yellow": Fore.LIGHTYELLOW_EX,
        "light_white": Fore.LIGHTWHITE_EX,
        "light_black": Fore.LIGHTBLACK_EX,
        "bg_red": Back.RED,
        "bg_green": Back.GREEN,
        "bg_blue": Back.BLUE,
        "bg_cyan": Back.CYAN,
        "bg_magenta": Back.MAGENTA,
        "bg_yellow": Back.YELLOW,
        "bg_white": Back.WHITE,
        "bg_black": Back.BLACK,
        "bold": Style.BRIGHT,
        "dim": Style.DIM,
        "normal": Style.NORMAL,
    }

    if color.lower() not in color_map:
        return text + Style.RESET_ALL

    return color_map[color.lower()] + text + Style.RESET_ALL


def color_emotes(text: str, color: str = "blue") -> str:
    """
    Finds strings between * and calls colored_text to color them as emotes.
    :param text: The text containing emotes between * characters.
    :return: The text with colored emotes including * characters.
    """
    emote_regex = re.compile(r"(\*[^\*]+\*)")

    def color_match(match):
        return colored_text(match.group(1), color)

    return emote_regex.sub(color_match, text)


def extract_metadata(img_path, img_format):
    return chara_read(img_path)


def chara_read(img_url, input_format=None):
    if input_format is None:
        if ".webp" in img_url:
            format = "webp"
        else:
            format = "png"
    else:
        format = input_format

    with open(img_url, "rb") as image_file:
        image_data = image_file.read()
        image = Image.open(io.BytesIO(image_data))

    exif_data = image.getexif()

    if format == "webp":
        try:
            if 37510 in exif_data:
                try:
                    description = exif_data[37510].decode("utf-8")
                except AttributeError:
                    description = fix_unquoted_keys(exif_data[37510])

                try:
                    char_data = json.loads(description)
                except:
                    byte_arr = [int(x) for x in description.split(",")[1:]]
                    uint8_array = bytearray(byte_arr)
                    char_data_string = uint8_array.decode("utf-8")
                    return json.loads("{" + char_data_string)
            else:
                log.warn("chara_load", msg="No chara data found in webp image.")
                return False

            return char_data
        except Exception as err:
            raise
            return False

    elif format == "png":
        with Image.open(img_url) as img:
            img_data = img.info

            if "chara" in img_data:
                base64_decoded_data = base64.b64decode(img_data["chara"]).decode(
                    "utf-8"
                )
                return json.loads(base64_decoded_data)
            if "comment" in img_data:
                base64_decoded_data = base64.b64decode(img_data["comment"]).decode(
                    "utf-8"
                )
                return base64_decoded_data
            else:
                log.warn("chara_load", msg="No chara data found in PNG image.")
                return False
    else:
        return None


def count_tokens(source):
    if isinstance(source, list):
        t = 0
        for s in source:
            t += count_tokens(s)
    elif isinstance(source, (str, SceneMessage)):
        t = int(len(source) / 3.6)
    else:
        log.warn("count_tokens", msg="Unknown type: " + str(type(source)))
        t = 0

    return t


def replace_conditional(input_string: str, params) -> str:
    """
    Replaces all occurrences of {conditional:value:compare:true_value:false_value} in the input string
    with the result of calling the conditional function.

    Args:
        input_string (str): The input string containing {conditional:value:compare:true_value:false_value} patterns.
        value: The value to be passed to the conditional function.

    Returns:
        str: The modified input string with the conditional patterns replaced.
    """
    pattern = r"\{conditional:(.*?):(.*?):(.*?):(.*?)\}"

    def replace_match(match):
        value, compare, true_value, false_value = (
            match.group(1),
            match.group(2),
            match.group(3),
            match.group(4),
        )
        value = value.format(**params)
        if value.lower() == compare.lower():
            return true_value
        return false_value

    modified_string = re.sub(pattern, replace_match, input_string)
    return modified_string


def pronouns(gender: str) -> tuple[str, str]:
    """
    Returns the pronouns for gender
    """

    if gender == "female":
        possessive_determiner = "her"
        pronoun = "she"
    elif gender == "male":
        possessive_determiner = "his"
        pronoun = "he"
    elif gender == "fluid" or gender == "nonbinary" or not gender:
        possessive_determiner = "their"
        pronoun = "they"
    else:
        possessive_determiner = "its"
        pronoun = "it"

    return (pronoun, possessive_determiner)


def strip_partial_sentences(text:str) -> str:
    # Sentence ending characters
    sentence_endings = ['.', '!', '?', '"', "*"]
    
    if not text:
        return text
    
    # Check if the last character is already a sentence ending
    if text[-1] in sentence_endings:
        return text
    
    # Split the text into words
    words = text.split()
    
    # Iterate over the words in reverse order until a sentence ending is found
    for i in range(len(words) - 1, -1, -1):
        if words[i][-1] in sentence_endings:
            return ' '.join(words[:i+1])
    
    # If no sentence ending is found, return the original text
    return text


def clean_paragraph(paragraph: str) -> str:
    """
    Cleans up a paragraph of text by:
    - Splitting the text against ':' and keeping the right-hand side
    - Removing all characters that aren't a-zA-Z from the beginning of the kept text

    Args:
        paragraph (str): The input paragraph to be cleaned.

    Returns:
        str: The cleaned paragraph.
    """

    # Split the paragraph by ':' and keep the right-hand side
    split_paragraph = paragraph.split(":")
    if len(split_paragraph) > 1:
        kept_text = split_paragraph[1]
    else:
        kept_text = split_paragraph[0]

    # Remove all characters that aren't a-zA-Z from the beginning of the kept text
    cleaned_text = re.sub(r"^[^a-zA-Z]*", "", kept_text)

    return cleaned_text


def clean_message(message: str) -> str:
    message = message.strip()
    message = re.sub(r"\s+", " ", message)
    message = message.replace("(", "*").replace(")", "*")
    message = message.replace("[", "*").replace("]", "*")
    return message

def clean_dialogue_old(dialogue: str, main_name: str = None) -> str:
    """
    Cleans up generated dialogue by removing unnecessary whitespace and newlines.

    Args:
        dialogue (str): The input dialogue to be cleaned.

    Returns:
        str: The cleaned dialogue.
    """



    cleaned_lines = []
    current_name = None

    for line in dialogue.split("\n"):
        if current_name is None and main_name is not None and ":" not in line:
            line = f"{main_name}: {line}"

        if ":" in line:
            name, message = line.split(":", 1)
            name = name.strip()
            if name != main_name:
                break
            
            message = clean_message(message)

            if not message:
                current_name = name
            elif current_name is not None:
                cleaned_lines.append(f"{current_name}: {message}")
                current_name = None
            else:
                cleaned_lines.append(f"{name}: {message}")
        elif current_name is not None:
            message = clean_message(line)
            if message:
                cleaned_lines.append(f"{current_name}: {message}")
                current_name = None

    cleaned_dialogue = "\n".join(cleaned_lines)
    return cleaned_dialogue

def clean_dialogue(dialogue: str, main_name: str) -> str:
    
    # keep spliting the dialogue by : with a max count of 1
    # until the  left side is no longer the main name
    
    cleaned_dialogue = ""
    
    # find all occurances of : and then walk backwards
    # and mark the first one that isnt preceded by the {main_name}
    cutoff = -1
    log.debug("clean_dialogue", dialogue=dialogue, main_name=main_name)
    for match in re.finditer(r":", dialogue, re.MULTILINE):
        index = match.start()
        check = dialogue[index-len(main_name):index] 
        log.debug("clean_dialogue", check=check, main_name=main_name)
        if check != main_name:
            cutoff = index
            break
        
    # then split dialogue at the index and return on only
    # the left side
    
    if cutoff > -1:
        log.debug("clean_dialogue", index=index)
        cleaned_dialogue = dialogue[:index]
        cleaned_dialogue = strip_partial_sentences(cleaned_dialogue)
        
        # remove all occurances of "{main_name}: " and then prepend it once
        
        cleaned_dialogue = cleaned_dialogue.replace(f"{main_name}: ", "")
        cleaned_dialogue = f"{main_name}: {cleaned_dialogue}"
        
        return clean_message(cleaned_dialogue)

    dialogue = dialogue.replace(f"{main_name}: ", "")
    dialogue = f"{main_name}: {dialogue}"

    return clean_message(strip_partial_sentences(dialogue))
    

def clean_attribute(attribute: str) -> str:
    """
    Cleans up an attribute by removing unnecessary whitespace and newlines.

    Also will remove any additional attributees.

    Args:
        attribute (str): The input attribute to be cleaned.

    Returns:
        str: The cleaned attribute.
    """

    special_chars = [
        "#",
        "`",
        "!",
        "@",
        "$",
        "%",
        "^",
        "&",
        "*",
        "(",
        ")",
        "-",
        "_",
        "=",
        "+",
        "[",
        "{",
        "]",
        "}",
        "|",
        ";",
        ":",
        ",",
        "<",
        ".",
        ">",
        "/",
        "?",
    ]

    for char in special_chars:
        attribute = attribute.split(char)[0].strip()

    return attribute.strip()




def duration_to_timedelta(duration):
    """Convert an isodate.Duration object or a datetime.timedelta object to a datetime.timedelta object."""
    # Check if the duration is already a timedelta object
    if isinstance(duration, datetime.timedelta):
        return duration

    # If it's an isodate.Duration object with separate year, month, day, hour, minute, second attributes
    days = int(duration.years) * 365 + int(duration.months) * 30 + int(duration.days)
    seconds = duration.tdelta.seconds
    return datetime.timedelta(days=days, seconds=seconds)

def timedelta_to_duration(delta):
    """Convert a datetime.timedelta object to an isodate.Duration object."""
    # Extract days and convert to years, months, and days
    days = delta.days
    years = days // 365
    days %= 365
    months = days // 30
    days %= 30
    # Convert remaining seconds to hours, minutes, and seconds
    seconds = delta.seconds
    hours = seconds // 3600
    seconds %= 3600
    minutes = seconds // 60
    seconds %= 60
    return isodate.Duration(years=years, months=months, days=days, hours=hours, minutes=minutes, seconds=seconds)

def parse_duration_to_isodate_duration(duration_str):
    """Parse ISO 8601 duration string and ensure the result is an isodate.Duration."""
    parsed_duration = isodate.parse_duration(duration_str)
    if isinstance(parsed_duration, datetime.timedelta):
        return timedelta_to_duration(parsed_duration)
    return parsed_duration

def iso8601_diff(duration_str1, duration_str2):
    # Parse the ISO 8601 duration strings ensuring they are isodate.Duration objects
    duration1 = parse_duration_to_isodate_duration(duration_str1)
    duration2 = parse_duration_to_isodate_duration(duration_str2)

    # Convert to timedelta
    timedelta1 = duration_to_timedelta(duration1)
    timedelta2 = duration_to_timedelta(duration2)

    # Calculate the difference
    difference_timedelta = abs(timedelta1 - timedelta2)
    
    # Convert back to Duration for further processing
    difference = timedelta_to_duration(difference_timedelta)

    return difference

def iso8601_duration_to_human(iso_duration, suffix: str = " ago"):
    
    # Parse the ISO8601 duration string into an isodate duration object
    if not isinstance(iso_duration, isodate.Duration):
        duration = isodate.parse_duration(iso_duration)
    else:
        duration = iso_duration

    # Extract years, months, days, and the time part as seconds
    years, months, days, hours, minutes, seconds = 0, 0, 0, 0, 0, 0

    if isinstance(duration, isodate.Duration):
        years = duration.years
        months = duration.months
        days = duration.days
        hours = duration.tdelta.seconds // 3600
        minutes = (duration.tdelta.seconds % 3600) // 60
        seconds = duration.tdelta.seconds % 60
    elif isinstance(duration, datetime.timedelta):
        days = duration.days
        hours = duration.seconds // 3600
        minutes = (duration.seconds % 3600) // 60
        seconds = duration.seconds % 60

    # Adjust for cases where duration is a timedelta object
    # Convert days to weeks and days if applicable
    weeks, days = divmod(days, 7)

    # Build the human-readable components
    components = []
    if years:
        components.append(f"{years} Year{'s' if years > 1 else ''}")
    if months:
        components.append(f"{months} Month{'s' if months > 1 else ''}")
    if weeks:
        components.append(f"{weeks} Week{'s' if weeks > 1 else ''}")
    if days:
        components.append(f"{days} Day{'s' if days > 1 else ''}")
    if hours:
        components.append(f"{hours} Hour{'s' if hours > 1 else ''}")
    if minutes:
        components.append(f"{minutes} Minute{'s' if minutes > 1 else ''}")
    if seconds:
        components.append(f"{seconds} Second{'s' if seconds > 1 else ''}")

    # Construct the human-readable string
    if len(components) > 1:
        last = components.pop()
        human_str = ', '.join(components) + ' and ' + last
    elif components:
        human_str = components[0]
    else:
        human_str = "Moments"

    return f"{human_str}{suffix}"

def iso8601_diff_to_human(start, end):
    if not start or not end:
        return ""
    
    diff = iso8601_diff(start, end)
    
    return iso8601_duration_to_human(diff)


def iso8601_add(date_a:str, date_b:str) -> str:
    """
    Adds two ISO 8601 durations together.
    """
    # Validate input
    if not date_a or not date_b:
        return "PT0S"

    new_ts = isodate.parse_duration(date_a.strip()) + isodate.parse_duration(date_b.strip())
    return isodate.duration_isoformat(new_ts)

def iso8601_correct_duration(duration: str) -> str:
    # Split the string into date and time components using 'T' as the delimiter
    parts = duration.split("T")
    
    # Handle the date component
    date_component = parts[0]
    time_component = ""
    
    # If there's a time component, process it
    if len(parts) > 1:
        time_component = parts[1]
        
        # Check if the time component has any date values (Y, M, D) and move them to the date component
        for char in "YD":  # Removed 'M' from this loop
            if char in time_component:
                index = time_component.index(char)
                date_component += time_component[:index+1]
                time_component = time_component[index+1:]
    
    # If the date component contains any time values (H, M, S), move them to the time component
    for char in "HMS":
        if char in date_component:
            index = date_component.index(char)
            time_component = date_component[index:] + time_component
            date_component = date_component[:index]
    
    # Combine the corrected date and time components
    corrected_duration = date_component
    if time_component:
        corrected_duration += "T" + time_component
    
    return corrected_duration


def fix_faulty_json(data: str) -> str:
    # Fix missing commas
    data = re.sub(r'}\s*{', '},{', data)
    data = re.sub(r']\s*{', '],{', data)
    data = re.sub(r'}\s*\[', '},{', data)
    data = re.sub(r']\s*\[', '],[', data)
    
    # Fix trailing commas
    data = re.sub(r',\s*}', '}', data)
    data = re.sub(r',\s*]', ']', data)
    
    try:
        json.loads(data)
    except json.JSONDecodeError:
        try:
            json.loads(data+"}")
            return data+"}"
        except json.JSONDecodeError:    
            try:
                json.loads(data+"]")
                return data+"]"
            except json.JSONDecodeError:
                return data
    
    return data

def extract_json(s):
    """
    Extracts a JSON string from the beginning of the input string `s`.
    
    Parameters:
        s (str): The input string containing a JSON string at the beginning.
        
    Returns:
        str: The extracted JSON string.
        dict: The parsed JSON object.
        
    Raises:
        ValueError: If a valid JSON string is not found.
    """
    open_brackets = 0
    close_brackets = 0
    bracket_stack = []
    json_string_start = None
    s = s.lstrip()  # Strip white spaces and line breaks from the beginning
    i = 0
    
    log.debug("extract_json", s=s)
    
    # Iterate through the string.
    while i < len(s):
        # Count the opening and closing curly brackets.
        if s[i] == '{' or s[i] == '[':
            bracket_stack.append(s[i])
            open_brackets += 1
            if json_string_start is None:
                json_string_start = i
        elif s[i] == '}' or s[i] == ']':
            bracket_stack
            close_brackets += 1
            # Check if the brackets match, indicating a complete JSON string.
            if open_brackets == close_brackets:
                json_string = s[json_string_start:i+1]
                # Try to parse the JSON string.
                return json_string, json.loads(json_string)
        i += 1
        
    if json_string_start is None:
        raise ValueError("No JSON string found.")
    
    json_string = s[json_string_start:]
    while bracket_stack:
        char = bracket_stack.pop()
        if char == '{':
            json_string += '}'
        elif char == '[':
            json_string += ']'
    
    json_object = json.loads(json_string)
    return json_string, json_object

def similarity_score(line: str, lines: list[str], similarity_threshold: int = 95) -> tuple[bool, int, str]:
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
        if similarity >= similarity_threshold:
            return True, similarity, existing_line
        
    return False, highest_similarity, None

def dedupe_sentences(line_a:str, line_b:str, similarity_threshold:int=95, debug:bool=False) -> str:
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
    
    Returns:
        str: the cleaned line_a.
    """
    
    line_a_sentences = sent_tokenize(line_a)
    line_b_sentences = sent_tokenize(line_b)
    
    cleaned_line_a_sentences = []
    
    for line_a_sentence in line_a_sentences:
        similar_found = False
        for line_b_sentence in line_b_sentences:
            similarity = fuzz.ratio(line_a_sentence, line_b_sentence)
            if similarity >= similarity_threshold:
                if debug:
                    log.debug("DEDUPE SENTENCE", similarity=similarity, line_a_sentence=line_a_sentence, line_b_sentence=line_b_sentence)
                similar_found = True
                break
        if not similar_found:
            cleaned_line_a_sentences.append(line_a_sentence)
            
    return " ".join(cleaned_line_a_sentences)

def dedupe_string(s: str, min_length: int = 32, similarity_threshold: int = 95, debug: bool = False) -> str:
    
    """
    Removes duplicate lines from a string.
    
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
    
    for line in lines:
        stripped_line = line.strip()
        if len(stripped_line) > min_length:
            similar_found = False
            for existing_line in deduped:
                similarity = fuzz.ratio(stripped_line, existing_line.strip())
                if similarity >= similarity_threshold:
                    similar_found = True
                    if debug:
                        log.debug("DEDUPE", similarity=similarity, line=line, existing_line=existing_line)
                    break
            if not similar_found:
                deduped.append(line)
        else:
            deduped.append(line)  # Allow shorter strings without dupe check
            
    return "\n".join(deduped)

def remove_extra_linebreaks(s: str) -> str:
    """
    Removes extra line breaks from a string.
    
    Parameters:
        s (str): The input string.
        
    Returns:
        str: The string with extra line breaks removed.
    """
    return re.sub(r"\n{3,}", "\n\n", s)

def replace_exposition_markers(s:str) -> str:
    s = s.replace("(", "*").replace(")", "*")
    s = s.replace("[", "*").replace("]", "*")
    return s 


def ensure_dialog_format(line:str, talking_character:str=None) -> str:
    
    #if "*" not in line and '"' not in line:
    #    if talking_character:
    #        line = line[len(talking_character)+1:].lstrip()
    #        return f"{talking_character}: \"{line}\""
    #    return f"\"{line}\""
    #

    if talking_character:
        line = line[len(talking_character)+1:].lstrip()

    lines = []

    for _line in line.split("\n"):
        try:
            _line = ensure_dialog_line_format(_line)
        except Exception as exc:
            log.error("ensure_dialog_format", msg="Error ensuring dialog line format", line=_line, exc_info=exc)
            pass
    
        lines.append(_line)
        
    if len(lines) > 1:
        line = "\n".join(lines)
    else:
        line = lines[0]
    
    if talking_character:
        line = f"{talking_character}: {line}"
    
    return line
    

def ensure_dialog_line_format(line:str):
    
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
    
    for i in range(len(line)):
        
        
        c = line[i]
        
        #print("segment_open", segment_open)
        #print("segment", segment)
        
        if c in ['"', '*']:
            if segment_open == c:
                # open segment is the same as the current character
                # closing
                segment_open = None
                segment += c
                segments += [segment.strip()]
                segment = None
            elif segment_open is not None and segment_open != c:
                # open segment is not the same as the current character
                # opening - close the current segment and open a new one
                
                # if we are at the last character we append the segment
                if i == len(line)-1 and segment.strip():
                    segment += c
                    segments += [segment.strip()]
                    segment_open = None
                    segment = None
                    continue
        
                segments += [segment.strip()]
                segment_open = c
                segment = c
            elif segment_open is None:
                # we're opening a segment
                segment_open = c
                segment = c
        else:
            if segment_open is None:
                segment_open = "unclassified"
                segment = c
            else:
                segment += c
                
    if segment is not None:
        if segment.strip().strip("*").strip('"'):
            segments += [segment.strip()]
        
    for i in range(len(segments)):
        segment = segments[i]
        if segment in ['"', '*']:
            if i > 0:
                prev_segment = segments[i-1]
                if prev_segment and prev_segment[-1] not in ['"', '*']:
                    segments[i-1] = f"{prev_segment}{segment}"
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
        elif segment[0] in ['"', '*'] and segment[-1] == segment[0]:
            continue
        
        segments[i] = segment
        
    for i in range(len(segments)):
        segment = segments[i]
        if not segment or segment[0] in ['"', '*']:
            continue
        
        prev_segment = segments[i-1] if i > 0 else None
        next_segment = segments[i+1] if i < len(segments)-1 else None
        
        if prev_segment and prev_segment[-1] == '"':
            segments[i] = f"*{segment}*"
        elif prev_segment and prev_segment[-1] == '*':
            segments[i] = f"\"{segment}\""
        elif next_segment and next_segment[0] == '"':
            segments[i] = f"*{segment}*"
        elif next_segment and next_segment[0] == '*':
            segments[i] = f"\"{segment}\""
            
    for i in range(len(segments)):
        segments[i] = clean_uneven_markers(segments[i], '"')
        segments[i] = clean_uneven_markers(segments[i], '*')
            
    return " ".join(segment for segment in segments if segment).strip()


def clean_uneven_markers(chunk:str, marker:str):
    
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