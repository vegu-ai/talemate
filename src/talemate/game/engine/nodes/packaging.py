"""
Nodes that help managing node module packaging setup for easy scene installation.
"""

import json
import os
from typing import ClassVar, TYPE_CHECKING, Literal, Any
import pydantic
import structlog
import traceback

from .core import (
    Node,
    Graph,
    register,
    UNRESOLVED,
    PropertyField,
    NodeStyle,
    TYPE_CHOICES,
)

from .registry import get_node, get_nodes_by_base_type

from .scene import SceneLoop

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

__all__ = [
    "PromoteConfig",
    "initialize_scene_package_info",
    "get_scene_package_info",
    "apply_scene_package_info",
    "list_packages",
    "get_package_by_registry",
    "install_package",
    "update_package_properties",
    "uninstall_package",
    "initialize_package",
    "initialize_packages",
]


log = structlog.get_logger("talemate.game.engine.nodes.packaging")

TYPE_CHOICES.extend(
    [
        "node_module",
    ]
)

SCENE_PACKAGE_INFO_FILENAME = "modules.json"

# ------------------------------------------------------------------------------------------------
# MODELS
# ------------------------------------------------------------------------------------------------


class PackageProperty(pydantic.BaseModel):
    module: str
    name: str
    label: str
    description: str
    type: str
    default: str | int | float | bool | list[str] | None
    value: str | int | float | bool | list[str] | None = None
    required: bool = pydantic.Field(default=False)
    choices: list[str] | None = None


class PackageData(pydantic.BaseModel):
    name: str
    author: str
    description: str
    installable: bool
    registry: str
    status: Literal["installed", "not_installed"] = "not_installed"

    errors: list[str] = pydantic.Field(default_factory=list)

    package_properties: dict[str, PackageProperty] = pydantic.Field(
        default_factory=dict
    )
    install_nodes: list[str] = pydantic.Field(default_factory=list)
    installed_nodes: list[str] = pydantic.Field(default_factory=list)
    restart_scene_loop: bool = pydantic.Field(default=False)

    @pydantic.computed_field(description="Whether the package is configured")
    @property
    def configured(self) -> bool:
        """
        Whether the package is configured.
        """
        return all(
            prop.value is not None
            for prop in self.package_properties.values()
            if prop.required
        )

    def properties_for_node(self, node_registry: str) -> dict[str, Any]:
        """
        Get the properties for a node.
        """

        return {
            prop.name: prop.value
            for prop in self.package_properties.values()
            if prop.module == node_registry
        }


class ScenePackageInfo(pydantic.BaseModel):
    packages: list[PackageData]

    def has_package(self, package_registry: str) -> bool:
        return any(p.registry == package_registry for p in self.packages)

    def get_package(self, package_registry: str) -> PackageData | None:
        return next((p for p in self.packages if p.registry == package_registry), None)


# ------------------------------------------------------------------------------------------------
# FUNCTIONS
# ------------------------------------------------------------------------------------------------


async def initialize_scene_package_info(scene: "Scene"):
    """
    Initialize the scene package info.

    This means creation of an empty json file in the scene's info directory.
    """

    filepath = os.path.join(scene.info_dir, SCENE_PACKAGE_INFO_FILENAME)

    # if info dir does not exist, create it
    if not os.path.exists(scene.info_dir):
        os.makedirs(scene.info_dir)

    if not os.path.exists(filepath):
        with open(filepath, "w") as f:
            json.dump(ScenePackageInfo(packages=[]).model_dump(), f)


async def get_scene_package_info(scene: "Scene") -> ScenePackageInfo:
    """
    Get the scene package info.

    Returns:
        ScenePackageInfo: Scene package info.
    """

    filepath = os.path.join(scene.info_dir, SCENE_PACKAGE_INFO_FILENAME)

    # if info dir does not exist, create it
    if not os.path.exists(scene.info_dir):
        os.makedirs(scene.info_dir)

    if not os.path.exists(filepath):
        return ScenePackageInfo(packages=[])

    with open(filepath, "r") as f:
        return ScenePackageInfo.model_validate_json(f.read())


async def apply_scene_package_info(scene: "Scene", package_datas: list[PackageData]):
    """
    Will set the status to installed or not_installed for each package.

    Will update the property values for each installed package.

    Args:
        scene (Scene): The scene to apply the package info to.
        package_datas (list[PackageData]): The package data to apply.
    """

    scene_package_info = await get_scene_package_info(scene)

    for package_data in package_datas:
        if scene_package_info.has_package(package_data.registry):
            package_data.status = "installed"
            package = scene_package_info.get_package(package_data.registry)
            package_data.package_properties = package.package_properties
        else:
            package_data.status = "not_installed"


async def list_packages() -> list[PackageData]:
    """
    List all installable packages.

    Returns:
        list[PackageData]: List of package data.
    """

    packages = get_nodes_by_base_type("util/packaging/Package")
    package_datas = []

    for package_module_cls in packages:
        package_module: "Package" = package_module_cls()

        # skip if not installable
        if not package_module.get_property("installable"):
            continue

        errors = []

        install_node_modules = await package_module.get_nodes(
            lambda node: node.registry == "util/packaging/InstallNodeModule"
        )
        promoted_properties = await package_module.get_nodes(
            lambda node: node.registry == "util/packaging/PromoteConfig"
        )
        install_nodes = []

        module_properties = {}
        for install_node_module in install_node_modules:
            node_registry = install_node_module.get_property("node_registry")
            node_module_cls = get_node(node_registry)
            node_module: "Graph" = node_module_cls()
            module_properties[node_module.registry] = node_module.module_properties
            install_nodes.append(node_module.registry)

        log.debug(
            "package_module",
            package_module=package_module,
            module_properties=module_properties,
            promoted_properties=promoted_properties,
        )
        package_properties = {}

        for promoted_property in promoted_properties:
            property_name = promoted_property.properties["property_name"]
            exposed_property_name = promoted_property.properties[
                "exposed_property_name"
            ]
            target_node_registry = promoted_property.properties["node_registry"]

            try:
                module_property = module_properties[target_node_registry][property_name]
            except KeyError:
                log.warning(
                    "module property not found",
                    target_node_registry=target_node_registry,
                    property_name=property_name,
                    module_properties=module_properties,
                )
                errors.append(
                    f"Module property {property_name} not found in {target_node_registry}"
                )
                continue

            package_property = PackageProperty(
                module=target_node_registry,
                name=property_name,
                label=promoted_property.properties.get("label", ""),
                type=module_property.type,
                default=module_property.default,
                description=module_property.description,
                choices=module_property.choices,
                required=promoted_property.properties.get("required", False),
            )
            package_properties[exposed_property_name] = package_property

        package_data = PackageData(
            name=package_module.properties["package_name"],
            author=package_module.properties["author"],
            description=package_module.properties["description"],
            installable=package_module.properties["installable"],
            registry=package_module.registry,
            package_properties=package_properties,
            install_nodes=install_nodes,
            restart_scene_loop=package_module.properties["restart_scene_loop"],
            errors=errors,
        )

        package_datas.append(package_data)

    return package_datas


async def get_package_by_registry(package_registry: str) -> PackageData | None:
    """
    Get a package by its registry.

    Args:
        package_registry (str): The registry of the package to get.
    """

    packages = await list_packages()

    return next((p for p in packages if p.registry == package_registry), None)


async def save_scene_package_info(scene: "Scene", scene_package_info: ScenePackageInfo):
    """
    Save the scene package info to the scene's info directory.
    """

    # if info dir does not exist, create it
    if not os.path.exists(scene.info_dir):
        os.makedirs(scene.info_dir)

    with open(os.path.join(scene.info_dir, SCENE_PACKAGE_INFO_FILENAME), "w") as f:
        json.dump(scene_package_info.model_dump(), f, indent=4)


async def install_package(scene: "Scene", package_data: PackageData) -> PackageData:
    """
    Install a package to the scene.

    Args:
        scene (Scene): The scene to install the package to.
        package_data (PackageData): The package data to install.
    """

    scene_package_info = await get_scene_package_info(scene)

    if scene_package_info.has_package(package_data.registry):
        # already installed
        return package_data

    package_data.status = "installed"

    scene_package_info.packages.append(package_data)

    await save_scene_package_info(scene, scene_package_info)

    return package_data


async def update_package_properties(
    scene: "Scene",
    package_registry: str,
    package_properties: dict[str, PackageProperty],
) -> PackageData | None:
    """
    Update the properties of a package.
    """

    scene_package_info = await get_scene_package_info(scene)

    package_data = scene_package_info.get_package(package_registry)

    if not package_data:
        return

    for property_name, property_data in package_properties.items():
        package_data.package_properties[property_name].value = property_data.value

    await save_scene_package_info(scene, scene_package_info)

    return package_data


async def uninstall_package(scene: "Scene", package_registry: str):
    """
    Uninstall a package from the scene. (Removes the package from the scene package info)

    Args:
        scene (Scene): The scene to uninstall the package from.
        package_registry (str): The registry of the package to uninstall.
    """

    scene_package_info = await get_scene_package_info(scene)

    if not scene_package_info.has_package(package_registry):
        # not installed
        return

    package_data = scene_package_info.get_package(package_registry)

    scene_package_info.packages = [
        p for p in scene_package_info.packages if p.registry != package_registry
    ]

    scene_loop: SceneLoop | None = scene.active_node_graph
    if scene_loop:
        for node_id in package_data.installed_nodes:
            scene_loop.nodes.pop(node_id, None)

    package_data.installed_nodes = []

    await save_scene_package_info(scene, scene_package_info)


async def initialize_packages(scene: "Scene", scene_loop: SceneLoop):
    """
    Initialize all installed packages into the scene loop.
    """

    try:
        scene_package_info = await get_scene_package_info(scene)
        for package_data in scene_package_info.packages:
            if not package_data.configured:
                log.warning("package is not configured", package=package_data.name)
                continue

            if package_data.errors:
                log.warning("package information has errors", package=package_data.name)
                continue

            await initialize_package(scene, scene_loop, package_data)

    except Exception:
        log.error("initialize_packages failed", error=traceback.format_exc())


async def initialize_package(
    scene: "Scene",
    scene_loop: SceneLoop,
    package_data: PackageData,
):
    """
    Initialize an installed package into the scene loop.

    This is the logic that actually adds the package's nodes to the scene loop through the InstallNodeModule node(s)
    contained in the package module.

    Args:
        scene (Scene): The scene to install the package to.
        scene_loop (SceneLoop): The scene loop to install the package to.
        package_data (PackageData): The package data to install.
    """

    try:
        for registry in package_data.install_nodes:
            install_node_cls = get_node(registry)

            node: Node = install_node_cls()
            scene_loop.add_node(node)

            for property_name, property_value in package_data.properties_for_node(
                registry
            ).items():
                field = node.get_property_field(property_name)
                field.default = property_value
                node.properties[property_name] = property_value
            log.debug(
                "installed node",
                registry=registry,
                properties=package_data.properties_for_node(registry),
            )
    except Exception:
        log.error(
            "initialize_package failed",
            error=traceback.format_exc(),
            package_data=package_data,
        )


# ------------------------------------------------------------------------------------------------
# NODES
# ------------------------------------------------------------------------------------------------


@register("util/packaging/Package", as_base_type=True)
class Package(Graph):
    """
    Configure node that helps managing node module packaging setup for easy scene installation.

    This graph expects node module packaging instructions via various packaging nodes.
    """

    _export_definition: ClassVar[bool] = False

    class Fields:
        package_name = PropertyField(
            name="package_name",
            description="The name of the node module",
            type="str",
            default="",
        )

        author = PropertyField(
            name="author",
            description="The author of the node module",
            type="str",
            default="",
        )

        description = PropertyField(
            name="description",
            description="The description of the node module",
            type="str",
            default="",
        )

        installable = PropertyField(
            name="installable",
            description="Whether the node module is installable to the scene",
            type="bool",
            default=True,
        )

        restart_scene_loop = PropertyField(
            name="restart_scene_loop",
            description="Whether the scene loop should be restarted after the package is installed",
            type="bool",
            default=False,
        )

    def __init__(self, title="Package", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.set_property("package_name", "")
        self.set_property("author", "")
        self.set_property("description", "")
        self.set_property("installable", True)
        self.set_property("restart_scene_loop", False)


@register("util/packaging/InstallNodeModule")
class InstallNodeModule(Node):
    class Fields:
        node_registry = PropertyField(
            name="node_registry",
            description="The registry path of the node module to package",
            type="str",
            default=UNRESOLVED,
        )

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(
            node_color="#2c3339",
            title_color="#2e4657",
            icon="F01A6",
        )

    def __init__(self, title="Install Node Module", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.set_property("node_registry", UNRESOLVED)


@register("util/packaging/PromoteConfig")
class PromoteConfig(Node):
    """
    Promotes a single module property to be configurable through the scene once the package is installed.
    """

    class Fields:
        node_registry = PropertyField(
            name="node_registry",
            description="The registry path of the node module to package",
            type="str",
            default=UNRESOLVED,
        )

        property_name = PropertyField(
            name="property_name",
            description="Property Name",
            type="str",
            default=UNRESOLVED,
        )

        exposed_property_name = PropertyField(
            name="exposed_property_name",
            description="Exposed Property Name",
            type="str",
            default=UNRESOLVED,
        )

        label = PropertyField(
            name="label",
            description="Label",
            type="str",
            default="",
        )

        required = PropertyField(
            name="required",
            description="Whether the property is required",
            type="bool",
            default=False,
        )

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(
            icon="F168A",
        )

    def __init__(self, title="Promote Config", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.set_property("node_registry", UNRESOLVED)
        self.set_property("property_name", UNRESOLVED)
        self.set_property("exposed_property_name", UNRESOLVED)
        self.set_property("required", False)
        self.set_property("label", "")
