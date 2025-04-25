from diff_match_patch import diff_match_patch

__all__ = ["dmp_inline_diff"]

def dmp_inline_diff(text1:str, text2:str) -> str:
    dmp = diff_match_patch()
    diffs = dmp.diff_main(text1, text2)
    dmp.diff_cleanupSemantic(diffs)
    
    delete_class = "diff-delete"
    insert_class = "diff-insert"
    
    html = []
    for op, text in diffs:
        text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        if op == 0:  # Equal
            html.append(text)
        elif op == -1:  # Delete
            html.append(f'<span class="{delete_class}">{text}</span>')
        elif op == 1:  # Insert
            html.append(f'<span class="{insert_class}">{text}</span>')
    
    return ''.join(html)