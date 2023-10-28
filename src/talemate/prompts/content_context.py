from contextvars import ContextVar
import pydantic

current_prompt_context = ContextVar("current_content_context", default=None)

class PromptContextState(pydantic.BaseModel):
    content: list[str] = pydantic.Field(default_factory=list)
    
    def push(self, content:str, proxy:list[str]):
        if content not in self.content:
            self.content.append(content)
            proxy.append(content)
            
    def has(self, content:str):
        return content in self.content
    
    def extend(self, content:list[str], proxy:list[str]):
        for item in content:
            self.push(item, proxy)
    
class PromptContext:
    
    def __enter__(self):
        self.state = PromptContextState()
        self.token = current_prompt_context.set(self.state)
        return self.state
    
    def __exit__(self, *args):
        current_prompt_context.reset(self.token)
        return False