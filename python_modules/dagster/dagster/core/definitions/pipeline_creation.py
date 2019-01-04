from collections import defaultdict
from dagster import check

from dagster.core import types
from dagster.core.errors import DagsterInvalidDefinitionError

from .context import PipelineContextDefinition

from .dependency import (
    DependencyStructure,
    SolidInstance,
    Solid,
)

from .solid import SolidDefinition


class SolidAliasMapper:
    def __init__(self, dependencies_dict):
        aliased_dependencies_dict = {}
        solid_uses = defaultdict(set)
        alias_lookup = {}

        for solid_key, input_dep_dict in dependencies_dict.items():
            if not isinstance(solid_key, SolidInstance):
                solid_key = SolidInstance(solid_key)

            if solid_key.alias:
                key = solid_key.name
                alias = solid_key.alias
            else:
                key = solid_key.name
                alias = solid_key.name

            solid_uses[key].add(alias)
            aliased_dependencies_dict[alias] = input_dep_dict
            alias_lookup[alias] = key

            for dependency in input_dep_dict.values():
                solid_uses[dependency.solid].add(dependency.solid)

        self.solid_uses = solid_uses
        self.aliased_dependencies_dict = aliased_dependencies_dict
        self.alias_lookup = alias_lookup

    def get_uses_of_solid(self, solid_def_name):
        return self.solid_uses.get(solid_def_name)


def create_execution_structure(solids, dependencies_dict):
    mapper = SolidAliasMapper(dependencies_dict)

    pipeline_solids = []
    for solid_def in solids:
        if isinstance(solid_def, SolidDefinition):
            uses_of_solid = mapper.get_uses_of_solid(solid_def.name) or set([solid_def.name])

            for alias in uses_of_solid:
                pipeline_solids.append(Solid(name=alias, definition=solid_def))

        elif callable(solid_def):
            raise DagsterInvalidDefinitionError(
                '''You have passed a lambda or function {func} into a pipeline that is
                not a solid. You have likely forgetten to annotate this function with
                an @solid or @lambda_solid decorator located in dagster.core.decorators
                '''.format(func=solid_def.__name__)
            )
        else:
            raise DagsterInvalidDefinitionError(
                'Invalid item in solid list: {item}'.format(item=repr(solid_def))
            )

    pipeline_solid_dict = {ps.name: ps for ps in pipeline_solids}

    _validate_dependencies(
        mapper.aliased_dependencies_dict,
        pipeline_solid_dict,
        mapper.alias_lookup,
    )

    dependency_structure = DependencyStructure.from_definitions(
        pipeline_solid_dict,
        mapper.aliased_dependencies_dict,
    )

    return dependency_structure, pipeline_solid_dict


def _validate_dependencies(dependencies, solid_dict, alias_lookup):
    for from_solid, dep_by_input in dependencies.items():
        for from_input, dep in dep_by_input.items():
            if from_solid == dep.solid:
                raise DagsterInvalidDefinitionError(
                    'Circular reference detected in solid {from_solid} input {from_input}.'.format(
                        from_solid=from_solid, from_input=from_input
                    )
                )

            if not from_solid in solid_dict:
                aliased_solid = alias_lookup.get(from_solid)
                if aliased_solid == from_solid:
                    raise DagsterInvalidDefinitionError(
                        'Solid {from_solid} in dependency dictionary not found in solid list'.
                        format(from_solid=from_solid),
                    )
                else:
                    raise DagsterInvalidDefinitionError(
                        (
                            'Solid {aliased_solid} (aliased by {from_solid} in dependency '
                            'dictionary) not found in solid list'
                        ).format(
                            aliased_solid=aliased_solid,
                            from_solid=from_solid,
                        ),
                    )
            if not solid_dict[from_solid].definition.has_input(from_input):
                input_list = [
                    input_def.name for input_def in solid_dict[from_solid].definition.input_defs
                ]
                raise DagsterInvalidDefinitionError(
                    'Solid "{from_solid}" does not have input "{from_input}". '.format(
                        from_solid=from_solid,
                        from_input=from_input,
                    ) + \
                    'Input list: {input_list}'.format(input_list=input_list)
                )

            if not dep.solid in solid_dict:
                raise DagsterInvalidDefinitionError(
                    'Solid {dep.solid} in DependencyDefinition not found in solid list'.format(
                        dep=dep
                    ),
                )

            if not solid_dict[dep.solid].definition.has_output(dep.output):
                raise DagsterInvalidDefinitionError(
                    'Solid {dep.solid} does not have output {dep.output}'.format(dep=dep),
                )


def _gather_all_types(solids, context_definitions, environment_type):
    check.list_param(solids, 'solids', SolidDefinition)
    check.dict_param(
        context_definitions,
        'context_definitions',
        key_type=str,
        value_type=PipelineContextDefinition,
    )

    check.inst_param(environment_type, 'environment_type', types.DagsterType)

    seen_config_schemas = set()

    for solid in solids:
        for dagster_type in solid.iterate_types(seen_config_schemas):
            yield dagster_type

    for context_definition in context_definitions.values():
        if context_definition.config_field:
            for dagster_type in context_definition.config_field.dagster_type.iterate_types(
                seen_config_schemas
            ):
                yield dagster_type

    for dagster_type in environment_type.iterate_types(seen_config_schemas):
        yield dagster_type


def construct_type_dictionary(solids, context_definitions, environment_type):
    type_dict = {}
    all_types = list(_gather_all_types(solids, context_definitions, environment_type))
    for dagster_type in all_types:
        name = dagster_type.name
        if name in type_dict:
            if dagster_type is not type_dict[name]:
                raise DagsterInvalidDefinitionError(
                    (
                        'Type names must be unique. You have construct two instances of types '
                        'with the same name {name} but have different instances'.format(name=name)
                    )
                )
        else:
            type_dict[dagster_type.name] = dagster_type

    return type_dict
