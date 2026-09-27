import json


def exclude_passage(response, passage: str):
    """Give ready views without exclusions a span that covers the whole passage.

    Mocked views carry invented text; excluding the whole passage makes any
    such text a valid local edit for the host check.
    """
    try:
        data = json.loads(response)
    except (TypeError, ValueError):
        return response
    if not isinstance(data, dict) or not isinstance(data.get("views"), list):
        return response
    for view in data["views"]:
        if isinstance(view, dict) and view.get("status") == "ready":
            text = view.get("text")
            view.setdefault(
                "exclusions",
                []
                if isinstance(text, str) and passage in text
                else [{"span": passage, "reason": "test", "forbidden": []}],
            )
    return json.dumps(data)


def excluding_passage(request):
    async def wrapped(*args, **kwargs):
        text, extracted = await request(*args, **kwargs)
        context = kwargs.get("vars", {}).get("context")
        passage = (context.get("passage") or {}).get("text") if context else None
        if not isinstance(passage, str):
            return text, extracted
        return exclude_passage(text, passage), {
            **extracted,
            "response": exclude_passage(extracted.get("response"), passage),
        }

    return wrapped
