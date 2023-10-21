from talemate.prompts import Prompt

BASIC = "Below is an instruction that describes a task. Write a response that appropriately completes the request."

ROLEPLAY = str(Prompt.get("conversation.system"))

NARRATOR = str(Prompt.get("narrator.system"))

CREATOR = str(Prompt.get("creator.system"))

DIRECTOR = str(Prompt.get("director.system"))

ANALYST = str(Prompt.get("summarizer.system-analyst"))

ANALYST_FREEFORM = str(Prompt.get("summarizer.system-analyst-freeform"))

EDITOR = str(Prompt.get("editor.system"))
