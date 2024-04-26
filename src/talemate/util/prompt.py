__all__ = ["replace_special_tokens"]


def replace_special_tokens(prompt: str):
    """
    Replaces the following special tokens

    <|TRAILING_NEW_LINE|> -> \n
    <|TRAILING_SPACE|> -> " "
    """

    return prompt.replace("<|TRAILING_NEW_LINE|>", "\n").replace(
        "<|TRAILING_SPACE|>", " "
    )
