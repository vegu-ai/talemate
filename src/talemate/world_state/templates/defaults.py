from talemate.world_state.templates import (
    TEMPLATE_PATH_TALEMATE,
    Collection,
    Group,
    StateReinforcement,
)

__all__ = [
    "DEFAULT_GROUP",
    "create_defaults_if_empty_collection",
]

DEFAULT_GROUP = Group(
    author="Talemate",
    name="default",
    description="Default world state templates.",
    templates={
        "goals": StateReinforcement(
            auto_create=False,
            description="Long term and short term goals",
            favorite=True,
            insert="conversation-context",
            instructions="Create a long term goal and two short term goals for {character_name}. Your response must only be the long terms and two short term goals.",
            interval=20,
            name="Goals",
            query="Goals",
            state_type="npc",
        ),
        "physical_health": StateReinforcement(
            auto_create=False,
            description="Keep track of health.",
            favorite=True,
            insert="sequential",
            instructions="",
            interval=10,
            name="Physical Health",
            query="What is {character_name}'s current physical health status?",
            state_type="character",
        ),
        "time_of_day": StateReinforcement(
            auto_create=False,
            description="Track night / day cycle",
            favorite=True,
            insert="sequential",
            instructions="",
            interval=10,
            name="Time of day",
            query="What is the current time of day?",
            state_type="world",
        ),
    },
)


def create_defaults():
    collection = Collection()
    collection.groups = [DEFAULT_GROUP]
    collection.save()

    return collection


def create_defaults_if_empty_collection(collection: Collection):
    print("CREATING DEFAULTS")
    if not collection.groups or True:
        collection.groups = [DEFAULT_GROUP]
        collection.save(TEMPLATE_PATH_TALEMATE)

    return collection
