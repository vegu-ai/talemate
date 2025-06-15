import os
import uuid
from enum import IntEnum
from typing import TYPE_CHECKING, Any, ClassVar, Dict, Optional, TypeVar, Union

import pydantic
import structlog
import yaml
from typing_extensions import Annotated

if TYPE_CHECKING:
    from talemate.config import Config
    from talemate.tale_mate import Scene


__all__ = [
    "log",
    "register",
    "Template",
    "AnnotatedTemplate",
    "Group",
    "Collection",
    "FlatCollection",
    "TypedCollection",
    "TEMPLATE_PATH",
    "TEMPLATE_PATH_TALEMATE",
]

log = structlog.get_logger("world-state.templates")

MODELS = {}
TEMPLATE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "..", "templates", "world-state"
)
TEMPLATE_PATH_TALEMATE = os.path.join(TEMPLATE_PATH, "talemate")


class register:

    def __init__(self, template_type: str):
        self.template_type = template_type

    def __call__(self, cls):
        MODELS[self.template_type] = cls
        return cls


def name_to_id(name: str) -> str:
    return name.replace(" ", "_").lower()


def validate_template(
    v: Any,
    handler: pydantic.ValidatorFunctionWrapHandler,
    info: pydantic.ValidationInfo,
):
    if isinstance(v, dict):
        if v["template_type"] not in MODELS:
            raise ValueError(f"Template type {v['template_type']} is not registered")
        return MODELS[v["template_type"]](**v)
    elif isinstance(v, Template):
        if v.template_type not in MODELS:
            raise ValueError(f"Template type {v.template_type} is not registered")
        return v
    return handler(v)


class Priority(IntEnum):
    low = 1
    medium = 2
    high = 3


class Template(pydantic.BaseModel):
    name: str
    template_type: str = "base"
    instructions: str | None = None
    group: str | None = None
    favorite: bool = False
    uid: str = pydantic.Field(default_factory=lambda: str(uuid.uuid4()))
    # priority: Priority = Priority.low
    # Weird behavior during yaml dump with IntEnum
    priority: int = 1

    async def generate(self, **kwargs):
        raise NotImplementedError("generate method not implemented")

    def formatted(
        self, prop_name: str, scene: "Scene", character_name: str = None, **vars
    ) -> str:
        """
        Format instructions for a template.
        """
        value = getattr(self, prop_name)

        if not value:
            return value

        kwargs = {}

        player_character = scene.get_player_character()

        kwargs.update(
            player_name=player_character.name if player_character else None,
            character_name=character_name or None,
            **vars,
        )

        return value.format(**kwargs)


TemplateType = TypeVar("TemplateType", bound=Template)
AnnotatedTemplate = Annotated[TemplateType, pydantic.WrapValidator(validate_template)]


class Group(pydantic.BaseModel):
    author: str
    name: str
    description: str
    templates: dict[str, AnnotatedTemplate] = pydantic.Field(default_factory=dict)
    uid: str = pydantic.Field(default_factory=lambda: str(uuid.uuid4()))
    path: str | None = None

    @classmethod
    def load(cls, path: str) -> "Group":
        with open(path, "r") as f:
            data = yaml.safe_load(f)
            data = cls.sanitize_data(data)
            return cls(path=path, **data)
        
    @classmethod
    def sanitize_data(cls, data: dict) -> dict:
        """
        Sanitizes the data for the group.
        """
        
        data.pop("path", None)
        
        # ensure uid is set
        if not data.get("uid"):
            data["uid"] = str(uuid.uuid4())
        
        # if group name is null, set it to the group uid
        if not data.get("name"):
            uid = data.get("uid")
            log.warning("Group has no name", group_uid=uid)
            data["name"] = uid[:8]
            
        # if description or author are null, set them to blank strings
        if data.get("description") is None: 
            data["description"] = ""
        if data.get("author") is None:
            data["author"] = ""
        
        # 1 remove null templates
        for template_id, template in list(data["templates"].items()):
            if not template:
                log.warning("Template is null", template_id=template_id)
                del data["templates"][template_id]
                
        # for templates with a null name, set it to the template_id
        for template_id, template in data["templates"].items():
            if template.get("group") != data["uid"]:
                template["group"] = data["uid"]
            
            if not template.get("uid"):
                template["uid"] = template_id
            
            if not template.get("name"):
                log.warning("Template has no name", template_id=template_id)
                template["name"] = template_id[:8]
                
            # try to int priority, on failure set to 1
            try:
                template["priority"] = int(template.get("priority", 1))
            except (ValueError, TypeError):
                template["priority"] = 1

                
        # ensure template_type exists and drop any that are invalid
        for template_id, template in list(data["templates"].items()):
            template_type = template.get("template_type")
            if not template_type:
                log.warning("Template has no template_type", template_id=template_id)
                del data["templates"][template_id]
            
            if template_type not in MODELS:
                log.warning("Template has invalid template_type", template_id=template_id, template_type=template_type)
                del data["templates"][template_id]

        return data
        

    @property
    def filename(self):
        cleaned_name = self.name.replace(" ", "-").lower()
        return f"{cleaned_name}.yaml"

    def save(self, path: str = TEMPLATE_PATH):

        if not self.path:
            path = os.path.join(path, self.filename)
        else:
            path = self.path

        # ensure `group` is set on all templates
        for template in self.templates.values():
            template.group = self.uid

        with open(path, "w") as f:
            group_data = self.model_dump()
            group_data.pop("path", None)
            yaml.dump(group_data, f, sort_keys=True)
        log.debug("Worldstate template group saved", path=path)

    def diff(self, group: "Group") -> "Group":
        """
        Will return a new group that contains only the templates that are
        different between the two groups

        New group will inherit name, author, and description from self.
        """
        templates = {}

        for template_id, template in self.templates.items():

            # we need to ignore the value of `group` since that
            # is always going to be different.
            #
            # to do so we temporarily set the group to the same value

            try:
                _orig_group = template.group
                template.group = group.uid

                if template_id not in group.templates or not (
                    self.templates[template_id] == group.templates[template_id]
                ):
                    templates[template_id] = template

            finally:
                template.group = _orig_group

        return Group(
            author=self.author,
            name=self.name,
            description=self.description,
            templates=templates,
        )

    def insert_template(self, template: Template, save: bool = True):

        if template.uid in self.templates:
            raise ValueError(f"Template with id {template.uid} already exists in group")

        self.templates[template.uid] = template

        if save:
            self.save()

    def update_template(self, template: Template, save: bool = True):

        self.templates[template.uid] = template

        if save:
            self.save()

    def delete_template(self, template: Template, save: bool = True):
        if template.uid not in self.templates:
            return

        del self.templates[template.uid]

        if save:
            self.save()

    def find(self, uid: str) -> Template | None:
        for template in self.templates.values():
            if template.uid == uid:
                return template

        return None

    def delete(self, path: str = TEMPLATE_PATH):
        if os.path.exists(self.path):
            os.remove(self.path)

    def update(self, group: "Group", save: bool = True, ignore_templates: bool = True):
        self.author = group.author
        self.name = group.name
        self.description = group.description

        if not ignore_templates:
            self.templates = group.templates

        if save:
            self.save()


class Collection(pydantic.BaseModel):
    groups: list[Group] = pydantic.Field(default_factory=list)

    @classmethod
    def load(cls, path: str = TEMPLATE_PATH) -> "Collection":
        """
        Look for .yaml files in the given path and load them as groups
        into a new collection
        """

        groups = []

        for root, _, files in os.walk(path):
            # loop through root and directories
            # and load any .yaml files as groups

            for file in files:
                if file.endswith(".yaml"):
                    group = Group.load(os.path.join(root, file))
                    groups.append(group)

        return cls(groups=groups)

    @classmethod
    def create_from_legacy_config(
        cls,
        config: "Config",
        save: bool = True,
        check_if_exists: bool = True,
    ) -> "Collection":
        """
        templates used to be stored in the main tailmate config as
        a dictionary of dictionaries. This method will convert those
        """

        groups = []

        collection = cls.load(TEMPLATE_PATH_TALEMATE)

        config_templates = config.game.world_state.templates.model_dump()

        for template_type, templates in config_templates.items():

            name = f"legacy-{template_type.replace('_', '-')}s"

            if check_if_exists:
                if os.path.exists(os.path.join(TEMPLATE_PATH_TALEMATE, f"{name}.yaml")):
                    log.debug(
                        "template transfer from legacy config",
                        template_type=template_type,
                        status="skipped",
                        reason="already exists",
                    )
                    continue

            converted_templates = []
            for template in templates.values():
                _template = MODELS[template_type](**template)
                _template.uid = f"{name_to_id(_template.name)}"
                converted_templates.append(_template)

            group = Group(
                author="unknown",
                name=name,
                description=f"Auto-generated group for {template_type} templates. This group was created from the legacy templates in the main talemate config file.",
                templates={template.uid: template for template in converted_templates},
                # [MODELS[template_type](**template) for template in templates.values()]
            )

            for _group in collection.groups:
                group = group.diff(_group)

            groups.append(group)

            if save:
                group.save(TEMPLATE_PATH_TALEMATE)

        collection = cls(groups=groups)

        return collection

    def flat(self, types: list[str] = None) -> "FlatCollection":
        """
        merged templates from all groups
        """

        templates = {}

        for group in self.groups:
            for template_id, template in group.templates.items():

                if types and template.template_type not in types:
                    continue

                uid = f"{group.uid}__{template_id}"
                templates[uid] = template

        return FlatCollection(templates=templates)
    
    def flat_by_template_uid_only(self) -> "FlatCollection":
        """
        Returns a flat collection of templates by template uid only
        """
        templates = {}
        for group in self.groups:
            for template_id, template in group.templates.items():
                templates[template_id] = template

        return FlatCollection(templates=templates)

    def typed(self, types: list[str] = None) -> "TypedCollection":
        """
        Returns a dictionary of templates grouped by their template type
        """

        templates = {}

        for group in self.groups:
            for template_id, template in group.templates.items():

                if types and template.template_type not in types:
                    continue

                if template.template_type not in templates:
                    templates[template.template_type] = {}
                uid = f"{group.uid}__{template_id}"
                templates[template.template_type][uid] = template

        return TypedCollection(templates=templates)

    def save(self, path: str = TEMPLATE_PATH):
        for group in self.groups:
            group.save(path)

    def find(self, uid: str) -> Group | None:
        for group in self.groups:
            if group.uid == uid:
                return group
        return None

    def find_template(self, group_uid: str, template_uid: str) -> Template | None:
        group = self.find(group_uid)
        if group:
            return group.find(template_uid)
        return None

    def remove(self, group: Group, save: bool = True):
        self.groups.remove(group)
        if save:
            group.delete()
            
    def collect_all(self, uids: list[str]) -> dict[str, AnnotatedTemplate]:
        """
        Returns a dictionary of all templates in the collection
        """
        templates = {}
        for group in self.groups:
            for template in group.templates.values():
                if template.uid in uids:
                    templates[template.uid] = template

        return templates


class FlatCollection(pydantic.BaseModel):
    templates: dict[str, AnnotatedTemplate] = pydantic.Field(default_factory=dict)


class TypedCollection(pydantic.BaseModel):
    templates: dict[str, dict[str, AnnotatedTemplate]] = pydantic.Field(
        default_factory=dict
    )
    
    def find_by_name(self, name: str) -> AnnotatedTemplate | None:
        for templates in self.templates.values():
            for template in templates.values():
                if template.name == name:
                    return template
        return None
