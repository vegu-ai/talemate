import re

__all__ = [
    "extract_list",
]


def extract_list(response: str) -> list:
    """
    Response is generated response that may contain a numbered or bulleted list.

    - Start by locating the beginning of the list
    - then extract all items
    - return as list of items
    """

    items = []

    # Locate the beginning of the list
    lines = response.split("\n")

    # strip empty lines
    lines = [line for line in lines if line.strip() != ""]

    list_start = None

    for index in range(len(lines)):
        line = lines[index]

        if line.strip() == "":
            continue

        # match for numbered list or bulleted list (* or -)
        if (
            re.match(r"^\d+\.", line)
            or re.match(r"^\* ", line)
            or re.match(r"^- ", line)
        ):
            list_start = index
            break

    if index is None or list_start is None:
        # No list found
        return []

    # Extract all items
    for index in range(list_start, len(lines)):
        line = lines[index]

        # rematch items
        if (
            re.match(r"^\d+\.", line)
            or re.match(r"^\* ", line)
            or re.match(r"^- ", line)
        ):
            # strip the number or bullet
            line = re.sub(r"^(?:\d+\.|\*|-)", "", line).strip()

            if not line:
                continue

            items.append(line)
        else:
            # break if no more items
            break

    return items
