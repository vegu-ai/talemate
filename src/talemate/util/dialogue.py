__all__ = [
    "handle_endofline_special_delimiter"
]

def handle_endofline_special_delimiter(content:str) -> str:
    # -- endofline -- is a custom delimter that can exist 0 to n times
    # it should split total_result on the last one, take the left side
    # then remove all remaining -- endofline -- from the left side
    # then remove all leading and trailing whitespace
    
    content = content.replace("--endofline--", "-- endofline --")
    content = content.rsplit("-- endofline --", 1)[0]
    content = content.replace("-- endofline --", "")
    content = content.strip()
    return content