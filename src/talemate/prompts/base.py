"""
Base prompt loader

The idea is to be able to specify prompts for the various agents in a way that is
changeable and extensible. 
"""

import json
import re
import os
import fnmatch
import dataclasses
import jinja2
import structlog
import asyncio
import nest_asyncio
import uuid
import random
from typing import Any
from talemate.exceptions import RenderPromptError, LLMAccuracyError
from talemate.emit import emit
from talemate.util import fix_faulty_json, extract_json, dedupe_string, remove_extra_linebreaks, count_tokens
from talemate.config import load_config

import talemate.instance as instance

__all__ = [
    "Prompt",
    "LoopedPrompt",
    "register_sectioning_handler",
    "SECTIONING_HANDLERS",
    "DEFAULT_SECTIONING_HANDLER",
    "set_default_sectioning_handler",
]

log = structlog.get_logger("talemate")


nest_asyncio.apply()

SECTIONING_HANDLERS = {}
DEFAULT_SECTIONING_HANDLER = "titles"

class register_sectioning_handler:
    def __init__(self, name):
        self.name = name
    
    def __call__(self, func):
        SECTIONING_HANDLERS[self.name] = func
        return func
    
def set_default_sectioning_handler(name):
    
    if name not in SECTIONING_HANDLERS:
        raise ValueError(f"Sectioning handler {name} does not exist. Possible values are {list(SECTIONING_HANDLERS.keys())}")
    
    global DEFAULT_SECTIONING_HANDLER
    DEFAULT_SECTIONING_HANDLER = name
    
def validate_line(line):
    return (
        not line.strip().startswith("//") and
        not line.strip().startswith("/*") and
        not line.strip().startswith("[end of") and
        not line.strip().startswith("</")
    )

def clean_response(response):
    
    # remove invalid lines
    cleaned = "\n".join([line.strip() for line in response.split("\n") if validate_line(line)])

    # find lines containing [end of .*] and remove the match within  the line
    
    cleaned = re.sub(r"\[end of .*?\]", "", cleaned, flags=re.IGNORECASE)
    
    return cleaned.strip()



@dataclasses.dataclass
class LoopedPrompt():
    limit: int = 200
    items: list = dataclasses.field(default_factory=list)
    generated: dict = dataclasses.field(default_factory=dict)
    _current_item: str = None
    _current_loop: int = 0
    _initialized: bool = False
    validate_value: callable = lambda k,v: v
    on_update: callable = None
    
    def __call__(self, item:str):
        if item not in self.items and item not in self.generated:
            self.items.append(item)
        return self.generated.get(item) or ""
        
    @property
    def render_items(self):
        return "\n".join([
            f"{key}: {value}" for key, value in self.generated.items()
        ])
        
    @property
    def next_item(self):
        item = self.items.pop(0)
        while self.generated.get(item):
            try:
                item = self.items.pop(0)
            except IndexError:
                return None
        return item
        
    @property
    def current_item(self):
        try:
            if not self._current_item:
                self._current_item = self.next_item
            elif self.generated.get(self._current_item):
                self._current_item = self.next_item
            return self._current_item
        except IndexError:
            return None
            
    @property
    def done(self):
        if not self._initialized:
            self._initialized = True
            return False
        self._current_loop += 1
        if self._current_loop > self.limit:
            raise ValueError(f"LoopedPrompt limit reached: {self.limit}")
        log.debug("looped_prompt.done", current_item=self.current_item, items=self.items, keys=list(self.generated.keys()))
        if self.current_item:
            return (len(self.items) == 0 and self.generated.get(self.current_item))
        return len(self.items) == 0

    def q(self, item:str):
        log.debug("looped_prompt.q", item=item, current_item=self.current_item, q=self.current_item == item)
        
        if item not in self.items and item not in self.generated:
            self.items.append(item)
        return item == self.current_item

    def update(self, value):
        if value is None or not value.strip() or self._current_item is None:
            return
        self.generated[self._current_item] = self.validate_value(self._current_item, value)
        try:
            self.items.remove(self._current_item)
        except ValueError:
            pass
        
        if self.on_update:
            self.on_update(self._current_item, self.generated[self._current_item])
        
        self._current_item = None

@dataclasses.dataclass
class Prompt:
    
    """
    Base prompt class.
    """
    
    # unique prompt id {agent_type}-{prompt_name}
    uid: str
    
    # agent type
    agent_type: str
    
    # prompt name
    name: str
    
    # prompt text
    prompt: str = None
    
    # prompt variables
    vars: dict = dataclasses.field(default_factory=dict)
    
    # pad prepared response and ai response with a white-space
    pad_prepended_response: bool = True
    
    prepared_response: str = ""
    
    eval_response: bool = False
    eval_context: dict = dataclasses.field(default_factory=dict)

    json_response: bool = False
    
    client: Any = None
    
    sectioning_hander: str = dataclasses.field(default_factory=lambda: DEFAULT_SECTIONING_HANDLER)
    
    dedupe_enabled: bool = True
    
    @classmethod
    def get(cls, uid:str, vars:dict=None):
        
        #split uid into agent_type and prompt_name
        
        agent_type, prompt_name = uid.split(".")
        
        prompt = cls(
            uid = uid,
            agent_type = agent_type,
            name = prompt_name,
            vars = vars or {},
        )
        
        return prompt
    
    @classmethod
    async def request(cls, uid:str, client:Any, kind:str, vars:dict=None):
        prompt = cls.get(uid, vars)
        return await prompt.send(client, kind)
    

    
    @property
    def as_list(self):
        if not self.prompt:
            return ""
        return self.prompt.split("\n")

    @property
    def config(self):
        if not hasattr(self, "_config"):
            self._config = load_config()
        return self._config
 
    def __str__(self):
        return self.render()
    
    def template_env(self):
        # Get the directory of this file
        dir_path = os.path.dirname(os.path.realpath(__file__))
        
        # Create a jinja2 environment with the appropriate template paths
        return jinja2.Environment(
            loader=jinja2.FileSystemLoader([
                os.path.join(dir_path, '..', '..', '..', 'templates', 'prompts', self.agent_type),
                os.path.join(dir_path, 'templates', self.agent_type),
            ])
        )
        
    def list_templates(self, search_pattern:str):
        env = self.template_env()
        found = []

        # Ensure the loader is FileSystemLoader
        if isinstance(env.loader, jinja2.FileSystemLoader):
            for search_path in env.loader.searchpath:
                for root, dirs, files in os.walk(search_path):
                    for filename in fnmatch.filter(files, search_pattern):
                        # Compute the relative path to the template directory
                        relpath = os.path.relpath(root, search_path)
                        found.append(os.path.join(relpath, filename))

        return found
        
    
    def render(self):
        """
        Render the prompt using jinja2.
        
        This method uses the jinja2 library to render the prompt. It first creates a jinja2 environment with the
        appropriate template paths. Then it loads the template corresponding to the prompt name. Finally, it renders
        the template with the prompt variables.
        
        Returns:
            str: The rendered prompt.
        """
        
        env = self.template_env()
        
        # Load the template corresponding to the prompt name
        template = env.get_template('{}.jinja2'.format(self.name))
        
        ctx = {
            "bot_token": "<|BOT|>"
        }
        
        env.globals["set_prepared_response"] = self.set_prepared_response
        env.globals["set_prepared_response_random"] = self.set_prepared_response_random
        env.globals["set_eval_response"] = self.set_eval_response
        env.globals["set_json_response"] = self.set_json_response
        env.globals["set_question_eval"] = self.set_question_eval
        env.globals["disable_dedupe"] = self.disable_dedupe
        env.globals["random"] = self.random
        env.globals["query_scene"] = self.query_scene
        env.globals["query_memory"] = self.query_memory
        env.globals["query_text"] = self.query_text
        env.globals["uuidgen"] = lambda: str(uuid.uuid4())
        env.globals["to_int"] = lambda x: int(x)
        env.globals["config"] = self.config
        env.globals["len"] = lambda x: len(x)
        env.globals["count_tokens"] = lambda x: count_tokens(dedupe_string(x, debug=False))
        env.globals["print"] = lambda x: print(x)
        
        ctx.update(self.vars)
        
        sectioning_handler = SECTIONING_HANDLERS.get(self.sectioning_hander)
        
        # Render the template with the prompt variables
        self.eval_context = {}
        self.dedupe_enabled = True
        try:
            self.prompt = template.render(ctx)
            if not sectioning_handler:
                log.warning("prompt.render", prompt=self.name, warning=f"Sectioning handler `{self.sectioning_hander}` not found")
            else:
                self.prompt = sectioning_handler(self)
        except jinja2.exceptions.TemplateError as e:
            log.error("prompt.render", prompt=self.name, error=e)
            emit("system", status="error", message=f"Error rendering prompt `{self.name}`: {e}")
            raise RenderPromptError(f"Error rendering prompt: {e}")
        
        
        self.prompt = self.render_second_pass(self.prompt)
        
        return self.prompt
    
    def render_second_pass(self, prompt_text:str):
        """
        Will find all {!{ and }!} occurances replace them with {{ and }} and
        then render the prompt again.
        """
        
        # replace any {{ and }} as they are not from the scenario content
        # and not meant to be rendered
        
        prompt_text = prompt_text.replace("{{", "__").replace("}}", "__")
        
        # now replace {!{ and }!} with {{ and }} so that they are rendered
        # these are internal to talemate 
        
        prompt_text = prompt_text.replace("{!{", "{{").replace("}!}", "}}")
        
        env = self.template_env()
        env.globals["random"] = self.random
        parsed_text = env.from_string(prompt_text).render(self.vars)
        
        if self.dedupe_enabled:
            parsed_text = dedupe_string(parsed_text, debug=True)
        
        parsed_text = remove_extra_linebreaks(parsed_text)
        
        return parsed_text
        
    async def loop(self, client:any, loop_name:str, kind:str="create"):
        
        loop = self.vars.get(loop_name)
        
        while not loop.done:
            result = await self.send(client, kind=kind)
            loop.update(result)
    
    def query_scene(self, query:str, at_the_end:bool=True, as_narrative:bool=False):
        loop = asyncio.get_event_loop()
        narrator = instance.get_agent("narrator")
        query = query.format(**self.vars)
        return "\n".join([
            f"Question: {query}",
            f"Answer: " + loop.run_until_complete(narrator.narrate_query(query, at_the_end=at_the_end, as_narrative=as_narrative)),
        ])
        
    
    def query_text(self, query:str, text:str):
        loop = asyncio.get_event_loop()
        summarizer = instance.get_agent("summarizer")
        query = query.format(**self.vars)
        return "\n".join([
            f"Question: {query}",
            f"Answer: " + loop.run_until_complete(summarizer.analyze_text_and_answer_question(text, query)),
        ])
        
    def query_memory(self, query:str, as_question_answer:bool=True):
        loop = asyncio.get_event_loop()
        memory = instance.get_agent("memory")
        query = query.format(**self.vars)
        
        if not as_question_answer:
            return loop.run_until_complete(memory.query(query))
        
        return "\n".join([
            f"Question: {query}",
            f"Answer: " + loop.run_until_complete(memory.query(query)),
        ])
              
    def set_prepared_response(self, response:str, prepend:str=""):
        """
        Set the prepared response.
        
        Args:
            response (str): The prepared response.
        """
        self.prepared_response = response
        return f"<|BOT|>{prepend}{response}"


    def set_prepared_response_random(self, responses:list[str], prefix:str=""):
        """
        Set the prepared response from a list of responses using random.choice
        
        Args:
        
            responses (list[str]): A list of responses.
        """
        
        response = random.choice(responses)
        return self.set_prepared_response(f"{prefix}{response}")

    def set_eval_response(self, empty:str = None):
        """
        Set the prepared response for evaluation
        
        Args:
            response (str): The prepared response.
        """
        
        if empty:
            self.eval_context.setdefault("counters", {})[empty] = 0
        
        self.eval_response = True
        return self.set_json_response({
            "answers": [""]
        }, instruction='schema: {"answers": [ {"question": "question?", "answer": "yes", "reasoning": "your reasoning"}, ...]}')
    
    def set_json_response(self, initial_object:dict, instruction:str="", cutoff:int=3):
        """
        Prepares for a json response
        
        Args:
            response (str): The prepared response.
        """
        
        prepared_response  = json.dumps(initial_object, indent=2).split("\n")
        self.json_response = True
        
        prepared_response = ["".join(prepared_response[:-cutoff])]
        if instruction:
            prepared_response.insert(0, f"// {instruction}")
            
        cleaned = "\n".join(prepared_response)
        
        # remove all duplicate whitespace
        cleaned = re.sub(r"\s+", " ", cleaned)
        
        return self.set_prepared_response(cleaned)
        

    def set_question_eval(self, question:str, trigger:str, counter:str, weight:float=1.0):
        self.eval_context.setdefault("questions", [])
        self.eval_context.setdefault("counters", {})[counter] = 0
        self.eval_context["questions"].append((question, trigger, counter, weight))
        
        num_questions = len(self.eval_context["questions"])        
        return f"{num_questions}. {question}"
    
    def disable_dedupe(self):
        self.dedupe_enabled = False
        return ""

    def random(self, min:int, max:int):
        return random.randint(min, max)

    async def parse_json_response(self, response, ai_fix:bool=True):
        
        # strip comments
        try:
            
            try:
                response = json.loads(response)
                return response
            except json.decoder.JSONDecodeError as e:
                pass
            response = response.replace("True", "true").replace("False", "false")
            response = "\n".join([line for line in response.split("\n") if validate_line(line)]).strip()
            
            response = fix_faulty_json(response)
            response, json_response = extract_json(response)
            log.debug("parse_json_response ", response=response, json_response=json_response)
            return json_response            
        except Exception as e:
            
            # JSON parsing failed, try to fix it via AI
            
            if self.client and ai_fix:
                
                log.warning("parse_json_response error on first attempt - sending to AI to fix", response=response, error=e)
                fixed_response = await self.client.send_prompt(
                    f"fix the json syntax\n\n```json\n{response}\n```<|BOT|>"+"{",
                    kind="analyze_long",
                )
                log.warning("parse_json_response error on first attempt - sending to AI to fix", response=response, error=e)
                try:
                    fixed_response = "{"+fixed_response
                    return json.loads(fixed_response)
                except Exception as e:
                    log.error("parse_json_response error on second attempt", response=fixed_response, error=e)
                    raise LLMAccuracyError(
                        f"{self.name} - Error parsing JSON response: {e}",
                        model_name=self.client.model_name,
                    )
                
            else:
                log.error("parse_json_response", response=response, error=e)
                raise LLMAccuracyError(
                    f"{self.name} - Error parsing JSON response: {e}",
                    model_name=self.client.model_name,
                )

    async def evaluate(self, response:str) -> (str, dict):
        questions = self.eval_context["questions"]
        log.debug("evaluate", response=response)
        
        try:
            parsed_response = await self.parse_json_response(response)
            answers = parsed_response["answers"]
        except Exception as e:
            log.error("evaluate", response=response, error=e)
            raise LLMAccuracyError(
                f"{self.name} - Error parsing JSON response: {e}",
                model_name=self.client.model_name,
            )
            
        
        # if questions and answers are not the same length, raise an error
        if len(questions) != len(answers):
            log.error("evaluate", response=response, questions=questions, answers=answers)
            raise LLMAccuracyError(
                f"{self.name} - Number of questions ({len(questions)}) does not match number of answers ({len(answers)})",
                model_name=self.client.model_name,
            )        
        
        # collect answers
        try:
            answers = [(answer["answer"] + ", " + answer.get("reasoning","")).strip("").strip(",") for answer in answers]
        except KeyError as e:
            log.error("evaluate", response=response, error=e)
            raise LLMAccuracyError(
                f"{self.name} - expected `answer` key missing: {e}",
                model_name=self.client.model_name,
            )
                    
        # evaluate answers against questions and tally up the counts for each counter
        # by checking if the lowercase string starts with the trigger word
        
        questions_and_answers = zip(self.eval_context["questions"], answers)
        response = []
        for (question, trigger, counter, weight), answer in questions_and_answers:
            log.debug("evaluating", question=question, trigger=trigger, counter=counter, weight=weight, answer=answer)
            if answer.lower().startswith(trigger):
                self.eval_context["counters"][counter] += weight
            response.append(
                f"Question: {question}\nAnswer: {answer}",
            )
                
        log.info("eval_context", **self.eval_context)
        
        return "\n".join(response), self.eval_context.get("counters")
            
    async def send(self, client:Any, kind:str="create"):
        """
        Send the prompt to the client.
        
        Args:
            client (Any): The client to send the prompt to.
            kind (str): The kind of prompt to send.
        """
        
        self.client = client
        
        response = await client.send_prompt(str(self), kind=kind)
        
        if not response.lower().startswith(self.prepared_response.lower()):
            pad = " " if self.pad_prepended_response else ""
            response = self.prepared_response.rstrip() + pad + response.strip()

        
        if self.eval_response:
            return await self.evaluate(response)
        
        if self.json_response:
            log.debug("json_response", response=response)
            return response, await self.parse_json_response(response)
        
        response = clean_response(response)        
        
        return response
    
    def poplines(self, num):
        """
        Pop the first n lines from the prompt.
        
        Args:
            num (int): The number of lines to pop.
        """
        lines = self.as_list[:-num]
        self.prompt = "\n".join(lines)
        
        
    def cleaned(self, as_list:bool=False):
        """
        Clean the prompt.
        """
        cleaned = []
        
        for line in self.as_list:
            if "<|BOT|>" in line:
                cleaned.append(line.split("<|BOT|>")[0])
                break
            cleaned.append(line)
        
        if as_list:
            return cleaned
        return "\n".join(cleaned)
        
        

    
def _prompt_sectioning(prompt:Prompt, handle_open:callable, handle_close:callable, strip_empty_lines:bool=False) -> str:
    """
    Will loop through the prompt lines and find <|SECTION:{NAME}|> and <|CLOSE_SECTION|> tags
    and replace them with section tags according to the handle_open and handle_close functions.
    
    Arguments:
        prompt (Prompt): The prompt to section.
        handle_open (callable): A function that takes the section name as an argument and returns the opening tag.
        handle_close (callable): A function that takes the section name as an argument and returns the closing tag.
        strip_empty_lines (bool): Whether to strip empty lines after opening and before closing tags.
    """
    
    # loop through the prompt lines and find <|SECTION:{NAME}|> tags
    # keep track of currently open sections and close them when a new one is found
    #
    # sections are either closed by a <|CLOSE_SECTION|> tag or a new <|SECTION:{NAME}|> tag
    
    lines = prompt.as_list
    
    section_name = None
    
    new_lines = []
    at_beginning_of_section = False
    
    def _handle_strip_empty_lines_on_close():
        if not strip_empty_lines:
            return
        while new_lines[-1] == "":
            new_lines.pop()
        
    for line in lines:
        
        if "<|SECTION:" in line:
            
            if not handle_open:
                continue
            
            if section_name and handle_close:
                
                if at_beginning_of_section:
                    new_lines.pop()
                else:
                    _handle_strip_empty_lines_on_close()
                    new_lines.append(handle_close(section_name))
                    new_lines.append("")
            
            section_name = line.split("<|SECTION:")[1].split("|>")[0].lower()
            new_lines.append(handle_open(section_name))
            at_beginning_of_section = True
            continue
        
        if "<|CLOSE_SECTION|>" in line and section_name:
            
            if at_beginning_of_section:
                section_name = None
                new_lines.pop()
                continue
            
            if not handle_close:
                section_name = None
                continue
            _handle_strip_empty_lines_on_close()
            new_lines.append(handle_close(section_name))
            section_name = None
            continue
        elif "<|CLOSE_SECTION|>" in line and not section_name:
            continue
        
        if line == "" and strip_empty_lines and at_beginning_of_section:
            continue
        
        at_beginning_of_section = False
        
        new_lines.append(line)
    
    return "\n".join(new_lines)
    

@register_sectioning_handler("bracket")
def bracket_prompt_sectioning(prompt:Prompt) -> str:
    """
    Will loop through the prompt lines and find <|SECTION:{NAME}|> and <|CLOSE_SECTION|> tags
    and replace them with a bracketed section.
    
    Bracketed sections have both a beginning and end tag.
    """
 
    return _prompt_sectioning(
        prompt,
        lambda section_name: f"[{section_name}]",
        lambda section_name: f"[end of {section_name}]",
        strip_empty_lines=True,
    )

@register_sectioning_handler("none")
def none_prompt_sectioning(prompt:Prompt) -> str:
    return _prompt_sectioning(
        prompt,
        None,
        None,
    )
    
@register_sectioning_handler("titles")
def titles_prompt_sectioning(prompt:Prompt) -> str:
    
    return _prompt_sectioning(
        prompt,
        lambda section_name: f"\n## {section_name.capitalize()}",
        None,
    )
    
@register_sectioning_handler("html")
def html_prompt_sectioning(prompt:Prompt) -> str:
    
    return _prompt_sectioning(
        prompt,
        lambda section_name: f"<{section_name.capitalize().replace(' ','')}>",
        lambda section_name: f"</{section_name.capitalize().replace(' ','')}>",
        strip_empty_lines=True,
    )