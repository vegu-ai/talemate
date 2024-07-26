import re

__all__ = ["handle_endofline_special_delimiter"]


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
