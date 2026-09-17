from shea.bootstrap import SheaRuntime
from shea.extensions.plugin import SheaPlugin


class HelloWorldPlugin(SheaPlugin):
    name = "hello_world"
    version = "1.0.0"
    
    def register(self, runtime: SheaRuntime) -> None:
        print(f"Plugin '{self.name}' v{self.version} successfully registered into SheaRuntime!")

