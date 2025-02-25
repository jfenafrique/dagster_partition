import subprocess
from typing import Optional

from dagster_components import (
    Component,
    ComponentLoadContext,
    registered_component_type,
)
from dagster_components.core.schema.objects import AssetAttributesModel, OpSpecModel
from pydantic import BaseModel

import dagster as dg


# highlight-start
class ShellScriptSchema(BaseModel):
    script_path: str
    asset_attributes: AssetAttributesModel
    op: Optional[OpSpecModel] = None
    # highlight-end


@registered_component_type(name="shell_command")
class ShellCommand(Component):
    def __init__(self, params: ShellScriptSchema):
        self.params = params

    @classmethod
    def get_schema(cls) -> type[ShellScriptSchema]:
        # higlight-start
        return ShellScriptSchema
        # highlight-end

    @classmethod
    def load(
        cls, params: ShellScriptSchema, load_context: ComponentLoadContext
    ) -> "ShellCommand":
        return cls(params=params)

    def build_defs(self, load_context: ComponentLoadContext) -> dg.Definitions:
        resolved_asset_attributes = (
            self.params.asset_attributes.get_resolved_properties(
                load_context.resolution_context
            )
        )
        resolved_op_properties = (
            self.params.op.get_resolved_properties(load_context.resolution_context)
            if self.params.op
            else {}
        )

        @dg.asset(**resolved_asset_attributes, **resolved_op_properties)
        def _asset(context: dg.AssetExecutionContext):
            self.execute(context)

        return dg.Definitions(assets=[_asset])

    def execute(self, context: dg.AssetExecutionContext):
        subprocess.run(["sh", self.params.script_path], check=False)
