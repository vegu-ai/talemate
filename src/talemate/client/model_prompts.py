from jinja2 import Environment, FileSystemLoader
import os
import structlog
import shutil

__all__ = ["model_prompt"]

BASE_TEMPLATE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "templates", "llm-prompt"
)

# holds the default templates 
STD_TEMPLATE_PATH = os.path.join(BASE_TEMPLATE_PATH, "std")

# llm prompt templates provided by talemate
TALEMATE_TEMPLATE_PATH = os.path.join(BASE_TEMPLATE_PATH, "talemate")

# user overrides
USER_TEMPLATE_PATH = os.path.join(BASE_TEMPLATE_PATH, "user")

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
            self._env = Environment(loader=FileSystemLoader([
                USER_TEMPLATE_PATH,
                TALEMATE_TEMPLATE_PATH,
            ]))
            
        return self._env
    
    @property
    def std_templates(self) -> list[str]:
        env = Environment(loader=FileSystemLoader(STD_TEMPLATE_PATH))
        return sorted(env.list_templates())
    
    def __call__(self, model_name:str, system_message:str, prompt:str):
        template, template_file = self.get_template(model_name)
        if not template:
            template_file = "default.jinja2"
            template = self.env.get_template(template_file)
        
        if "<|BOT|>" in prompt:
            user_message, coercion_message = prompt.split("<|BOT|>", 1)
        else:
            user_message = prompt
            coercion_message = ""
            
        return template.render({
            "system_message": system_message,
            "prompt": prompt,
            "user_message": user_message,
            "coercion_message": coercion_message,
            "set_response" : self.set_response
        }), template_file
        
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
            return None, None
        
        # If there is only one match, return it
        if len(matches) == 1:
            return self.env.get_template(matches[0]), matches[0]
        
        # If there are multiple matches, return the one with the longest name
        sorted_matches = sorted(matches, key=lambda x: len(x), reverse=True)
        return self.env.get_template(sorted_matches[0]), sorted_matches[0]
    
    
    def create_user_override(self, template_name:str, model_name:str):
        
        """
        Will copy STD_TEMPLATE_PATH/template_name to USER_TEMPLATE_PATH/model_name.jinja2
        """
        
        template_name = template_name.split(".jinja2")[0]
            
        shutil.copyfile(
            os.path.join(STD_TEMPLATE_PATH, template_name + ".jinja2"),
            os.path.join(USER_TEMPLATE_PATH, model_name + ".jinja2")
        )
        
        return os.path.join(USER_TEMPLATE_PATH, model_name + ".jinja2")
    

    
model_prompt = ModelPrompt()