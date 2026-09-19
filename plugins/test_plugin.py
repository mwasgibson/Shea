import typing

from shea.bootstrap import SheaRuntime
from shea.extensions.plugin import SheaPlugin


class HelloWorldPlugin(SheaPlugin):
    name = "hello_world"
    version = "1.0.0"
    
    def register(self, runtime: SheaRuntime) -> None:
        print(f"Plugin '{self.name}' v{self.version} successfully registered into SheaRuntime!")
    def declare(self) -> list[dict[str, typing.Any]]:
        return [{"kind": "tool", "name": "hello.greet", "capabilities": ["extension.hello"]}]
    def invoke(self, *, tool: str, action: str, arguments: dict[str, typing.Any]) -> dict[str, typing.Any]:
        return {"message": f"hello {arguments.get('name', 'world')}"}