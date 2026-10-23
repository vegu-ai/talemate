from talemate.knowledge.step import knowledge_step


async def push_and_step(scene, messages, **kwargs):
    await scene.push_history(messages, **kwargs)
    await knowledge_step(scene)
