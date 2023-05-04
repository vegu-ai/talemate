"""
Utils for input handling.
"""

import asyncio

__all__ = [
    "get_user_input",
]


async def get_user_input(prompt: str = "Enter your input: "):
    """
    This function runs the input function in a separate thread and returns the user input.
    """
    user_input = await asyncio.to_thread(input, prompt)
    return user_input
