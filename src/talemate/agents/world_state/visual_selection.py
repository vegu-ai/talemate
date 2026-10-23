from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Literal

from talemate.decisions.gate import decision_gate

if TYPE_CHECKING:
    from talemate.character import Character
    from talemate.scene_assets import Asset

VisualKind = Literal["portrait", "background"]


class VisualSelectionMixin:
    """
    Picks the portrait or scene background that fits a message: the decision
    model keeps the current one or picks another existing one when it is
    sure, otherwise the fallback (the usual request) decides.
    """

    async def determine_visual_with_decisions(
        self,
        kind: VisualKind,
        content: str,
        assets: list["Asset"],
        fallback: Callable[[list[str]], Awaitable[dict]],
        character: "Character | None" = None,
    ) -> str | None:
        scene = self.scene
        options = {
            asset.id: {"name": asset.meta.name, "tags": asset.meta.tags}
            for asset in assets
        }

        def current_asset(asset_id):
            # the one place the current asset's name and tags go out, so the
            # question about it can read them in every request part
            if asset_id not in options:
                return None
            return {"id": asset_id, **options[asset_id]}

        if kind == "portrait":
            current = character.current_avatar
            uid, action, slot = "world_state.decision-avatar", "avatars", "avatar"
            state = {
                "character": character.name,
                "content": content,
                "current_avatar": current_asset(current),
            }

            def unchanged():
                return character.current_avatar == current

        else:
            current = scene.assets.backdrop
            uid, action, slot = (
                "world_state.decision-background",
                "backgrounds",
                "background",
            )
            state = {
                "content": content,
                "current_background": current_asset(current),
            }

            def unchanged():
                return scene.assets.backdrop == current

        if not options:
            return (await fallback([slot]))[slot]

        result = await decision_gate(
            uid,
            enabled=self.resolve_config(action, "decision_model"),
            candidates={slot: list(options)},
            # the other assets go out once, as the options of the choice question
            variables=lambda: {"state": state, "assets": options},
            fallback=fallback,
            is_current=lambda: self.scene is scene and unchanged(),
        )
        return result[slot]
