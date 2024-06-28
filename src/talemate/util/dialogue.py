import re

__all__ = ["handle_endofline_special_delimiter"]

def handle_endofline_special_delimiter(content: str) -> str:
    # -- endofline -- is a custom delimter that can exist 0 to n times
    # it should split total_result on the last one, take the left side
    # then remove all remaining -- endofline -- from the left side
    # then remove all leading and trailing whitespace

    # sometimes the AI will not generate -- endofline -- exactly
    # but it will be missing one or more spaces, so we need to
    # to normalize to -- endofline -- before we can split on it
    
    content = re.sub(r"--\s*end\s*of\s*line\s*--", "-- endofline --", content)
    content = content.replace("—endofline—", "-- endofline --")
    content = content.rsplit("-- endofline --", 1)[0]
    content = content.replace("-- endofline --", "")
    content = content.strip()
    content = content.replace("--", "*")
    return content
