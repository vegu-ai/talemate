import structlog
import pydantic
from .websocket_plugin import Plugin


from talemate.game.engine.nodes.packaging import (
    list_packages,
    apply_scene_package_info,
    get_scene_package_info,
    install_package,
    get_package_by_registry,
    uninstall_package,
    update_package_properties,
    PackageProperty,
)

log = structlog.get_logger(__name__)

class InstallPackageRequest(pydantic.BaseModel):
    package_registry: str

class UninstallPackageRequest(pydantic.BaseModel):
    package_registry: str

class SavePackagePropertiesRequest(pydantic.BaseModel):
    package_registry: str
    package_properties: dict[str, PackageProperty]


class PackageManagerPlugin(Plugin):
    router = "package_manager"
    
    def connect(self):
        pass
    
    def disconnect(self):
        pass
    
    async def handle_request_package_list(self, data: dict):
        packages = await list_packages()
        
        scene = self.scene
        
        await apply_scene_package_info(scene, packages)
        
        
        # sort by stats, then name (installed first)
        packages.sort(key=lambda x: (x.status == "installed", x.name))
        
        self.websocket_handler.queue_put(
            {
                "type": self.router,
                "action": "package_list",
                "data": [
                    package.model_dump() for package in packages
                ],
            }
        )
        
    async def handle_install_package(self, data: dict):
        request = InstallPackageRequest(**data)
        
        scene = self.scene
        
        package = await get_package_by_registry(request.package_registry)
        
        if not package:
            await self.signal_operation_failed(f"Package with registry {request.package_registry} not found")
            return
        
        await install_package(scene, package)
        
        self.websocket_handler.queue_put(
            {
                "type": self.router,
                "action": "installed_package",
                "data": {
                    "package": package.model_dump(),
                },
            }
        )
        
        await self.handle_request_package_list(data)
        
    async def handle_uninstall_package(self, data: dict):
        request = UninstallPackageRequest(**data)
        
        scene = self.scene
        
        package = await get_package_by_registry(request.package_registry)
        
        await uninstall_package(scene, request.package_registry)
        
        self.websocket_handler.queue_put(
            {
                "type": self.router,
                "action": "uninstalled_package",
                "data": {
                    "package": package.model_dump(),
                },
            }
        )
        
        await self.handle_request_package_list(data)
        
    async def handle_save_package_properties(self, data: dict):
        request = SavePackagePropertiesRequest(**data)
        
        scene = self.scene
        
        package = await update_package_properties(scene, request.package_registry, request.package_properties)
        
        if not package:
            await self.signal_operation_failed(f"Package with registry {request.package_registry} not found")
            return

        self.websocket_handler.queue_put(
            {
                "type": self.router,
                "action": "updated_package",
                "data": {
                    "package": package.model_dump(),
                },
            }
        )

        await self.handle_request_package_list(data)