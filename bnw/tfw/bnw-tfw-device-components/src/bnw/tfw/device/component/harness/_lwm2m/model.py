# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import copy
import logging
import os
import xml.etree.ElementTree as ETree
from json import load
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger("bnw.tfw.component.harness.lwm2m._model")


class ClientModel(object):
    def __init__(
        self,
        data=None,
        definition: Optional[dict] = None,
        definition_file=os.path.join(os.path.dirname(__file__), "lwm2m-object-definitions.json"),
    ):
        self.data = copy.deepcopy(data) if data is not None else {}

        if definition is not None:
            self.definition = copy.deepcopy(definition)
        else:
            with open(definition_file) as f:
                self.definition = load(f)

        # simple validation: check if all data objects are in the definition
        for obj in self.objects():
            if not self.has_definition(obj):
                raise ValueError(f"data contains undefined object with ID {obj}.")

    @staticmethod
    def from_ipso_spec(directories: Union[os.PathLike, List[os.PathLike]], data=None):
        if isinstance(directories, os.PathLike):
            directories = [directories]

        definition: Dict[str, Any] = {}
        for directory in directories:
            try:
                for file in os.listdir(directory):
                    if not file.endswith(".xml"):
                        continue
                    try:
                        definition.update(ClientModel._parse_ipso_spec_file(os.path.join(directory, file)))
                    except Exception as e:
                        raise ValueError("Could not parse %s (%s)- ignoring file", os.path.join(directory, file)) from e
            except FileNotFoundError as e:
                raise ValueError("Could load IPSO directory %s") from e

        return ClientModel(data=data, definition=definition, definition_file=None)

    @staticmethod
    def _parse_ipso_spec_file(file):
        def _convert_name(name):
            return name

        tree = ETree.parse(file)
        root = tree.getroot()
        _obj = root.find("Object")
        object_id = int(_obj.find("ObjectID").text)
        object_name = _convert_name(_obj.findtext("Name"))
        object_description1 = _obj.findtext("Description1", default="")
        object_multiple_instances = _obj.findtext("MultipleInstances", "Single") == "Multiple"
        object_mandatory = _obj.findtext("Mandatory", "Optional") == "Mandatory"
        object_resources = _obj.find("Resources")

        resources = {}
        for r in object_resources:
            resource_id = int(r.attrib["ID"])
            resource_name = _convert_name(r.findtext("Name"))
            resource_type = r.findtext("Type")
            multiple_instances = r.findtext("MultipleInstances", "Single") == "Multiple"

            resources.update(
                {
                    str(resource_id): {
                        "id": resource_id,
                        "name": resource_name,
                        "operations": r.findtext("Operations", default="NONE"),
                        "instancetype": "single" if not multiple_instances else "multiple",
                        "mandatory": r.findtext("Mandatory", "Optional") == "Mandatory",
                        "type": resource_type.lower(),
                        "range": r.findtext("RangeEnumeration", default=""),
                        "units": r.findtext("Units", default=""),
                        "description": r.findtext("Description", default=""),
                    }
                }
            )

        return {
            str(object_id): {
                "name": object_name,
                "id": object_id,
                "instancetype": "multiple" if object_multiple_instances else "single",
                "mandatory": object_mandatory,
                "description": object_description1,
                "resourcedefs": resources,
            }
        }

    def objects(self):
        return [x for x in sorted([int(i) for i in self.data.keys()])]

    def instances(self, obj):
        _insts = self.data[str(obj)]
        return [x for x in sorted([int(i) for i in _insts.keys()])]

    def resources(self, obj, inst=0):
        return [x for x in sorted([int(i) for i in self.data[str(obj)][str(inst)].keys()])]

    def resource(self, obj, inst, res):
        return self.data[str(obj)][str(inst)][str(res)]

    def has_definition(self, obj):
        return str(obj) in self.definition.keys()

    def is_object_multi_instance(self, obj):
        return self.definition[str(obj)]["instancetype"] == "multiple"

    def is_resource_multi_instance(self, obj, inst, res):
        return self.definition[str(obj)]["resourcedefs"][str(res)]["instancetype"] == "multiple"

    def resource_iter(self):
        for obj in self.objects():
            for inst in self.instances(obj):
                for res in self.resources(obj, inst):
                    yield (str(obj), str(inst), str(res))

    def instance_iter(self):
        for obj in self.objects():
            for inst in self.instances(obj):
                yield (str(obj), str(inst))

    def get_object_links(self):
        for obj in self.objects():
            for inst in self.instances(obj):
                yield f"</{obj}/{inst}>"

    def is_path_valid(self, path):
        if len(path) == 3:
            _obj = int(path[0])
            _inst = int(path[1])
            _res = int(path[2])
            return _obj in self.objects() and _inst in self.instances(_obj) and _res in self.resources(_obj, _inst)
        elif len(path) == 2:
            _obj = int(path[0])
            _inst = int(path[1])
            return _obj in self.objects() and _inst in self.instances(_obj)
        elif len(path) == 1:
            _obj = int(path[0])
            return _obj in self.objects()
        else:
            raise AttributeError(f"invalid path length: {len(path)}")

    def is_resource_readable(self, obj, inst, res):
        _ops = self.definition[obj]["resourcedefs"][str(res)]["operations"]
        return False if _ops == "NONE" else "R" in _ops

    def is_resource_executable(self, obj, inst, res):
        _ops = self.definition[obj]["resourcedefs"][str(res)]["operations"]
        return False if _ops == "NONE" else "E" in _ops

    def set_resource(self, obj, inst, res, content):
        self.data[str(obj)][str(inst)][str(res)] = content

    def apply(self, data):
        for obj in data.keys():
            for inst in data[obj].keys():
                for res in data[obj][inst].keys():
                    logger.debug(f"applying {obj}/{inst}/{res} = {data[obj][inst][res]}")
                    self.set_resource(obj, inst, res, data[obj][inst][res])
