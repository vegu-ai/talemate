from jinja2 import Environment, FileSystemLoader
import os
import structlog

__all__ = ["model_prompt"]

BASE_TEMPLATE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "templates", "llm-prompt"
)

log = structlog.get_logger("talemate.model_prompts")

class ModelPrompt:
    
    """
    Will attempt to load an LLM prompt template based on the model name
    
    If the model name is not found, it will default to the 'default' template
    """
    
    template_map = {}

    @property
    def env(self):
        if not hasattr(self, "_env"):
            log.info("modal prompt", base_template_path=BASE_TEMPLATE_PATH)
            self._env = Environment(loader=FileSystemLoader(BASE_TEMPLATE_PATH))
            
        return self._env
    
    def __call__(self, model_name:str, system_message:str, prompt:str):
        template = self.get_template(model_name)
        if not template:
            template = self.env.get_template("default.jinja2")
            
        return template.render({
            "system_message": system_message,
            "prompt": prompt,
            "set_response" : self.set_response
        })
        
    def set_response(self, prompt:str, response_str:str):
        
        prompt = prompt.strip("\n").strip()
        
        if "<|BOT|>" in prompt:
            if "\n<|BOT|>" in prompt:
                prompt = prompt.replace("\n<|BOT|>", response_str)
            else:
                prompt = prompt.replace("<|BOT|>", response_str)
        else:
            prompt = prompt.rstrip("\n") + response_str
            
        return prompt

    def get_template(self, model_name:str):
        """
        Will attempt to load an LLM prompt template - this supports
        partial filename matching on the template file name.
        """
        
        matches = []
        
        # Iterate over all templates in the loader's directory
        for template_name in self.env.list_templates():
            # strip extension
            template_name_match = os.path.splitext(template_name)[0]
            # Check if the model name is in the template filename
            if template_name_match.lower() in model_name.lower():
                matches.append(template_name)
               
        # If there are no matches, return None
        if not matches:
            return None
        
        # If there is only one match, return it
        if len(matches) == 1:
            return self.env.get_template(matches[0])
        
        # If there are multiple matches, return the one with the longest name
        return self.env.get_template(sorted(matches, key=lambda x: len(x), reverse=True)[0])
    
model_prompt = ModelPrompt()