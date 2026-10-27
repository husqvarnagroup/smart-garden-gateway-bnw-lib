#!/usr/bin/env python3

# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import logging
from enum import Enum
from math import log
from struct import pack, unpack

import cbor2
from aiocoap.message import Message
from aiocoap.numbers.codes import Code

logger = logging.getLogger("bnw.tfw.component.harness._lwm2m.encdec")


class TlvType(Enum):
    OBJECT_INSTANCE = 0b00000000
    RESOURCE_INSTANCE = 0b01000000
    MULTIPLE_RESOURCE = 0b10000000
    RESOURCE_VALUE = 0b11000000


class MediaType(Enum):
    TEXT = 0
    LINK = 40
    OPAQUE = 42
    SENML_CBOR = 112
    TLV = 11542
    JSON = 11543


# useful lambda to calculate the needed bytes from an integer
def needs_bytes(n):
    return 1 if n == 0 else int(log(abs(n), 256)) + 1


def mergedicts(dict1, dict2):
    for k in set(dict1.keys()).union(dict2.keys()):
        if k in dict1 and k in dict2:
            if isinstance(dict1[k], dict) and isinstance(dict2[k], dict):
                yield (k, dict(mergedicts(dict1[k], dict2[k])))
            else:
                yield (k, dict2[k])
        elif k in dict1:
            yield (k, dict1[k])
        else:
            yield (k, dict2[k])


class TlvEncoder(object):
    def __init__(self):
        pass

    @staticmethod
    def encode_object(model, obj):
        _buf = bytearray()
        for inst in model.instances(obj):
            _buf.extend(TlvEncoder._instance_to_tlv(model, obj, inst))
        msg = Message(code=Code.CONTENT, payload=_buf, content_format=MediaType.TLV.value)
        return msg

    @staticmethod
    def encode_instance(model, obj, inst):
        _buf = bytearray()
        _buf.extend(TlvEncoder._instance_to_tlv(model, obj, inst))
        msg = Message(code=Code.CONTENT, payload=_buf, content_format=MediaType.TLV.value)
        return msg

    @staticmethod
    def encode_resource(model, obj, inst, res):
        if not model.is_resource_multi_instance(obj, inst, res):
            if model.is_resource_readable(obj, inst, res):
                # single resource queries are returned as TEXT (plain)
                _r = model.resource(obj, inst, res)
                _payload = str(_r).encode()
                return Message(code=Code.CONTENT, payload=_payload, content_format=MediaType.TEXT.value)
            else:
                return Message(code=Code.METHOD_NOT_ALLOWED)
        else:
            # multi-resource
            if not model.is_resource_readable(obj, inst, res):
                return Message(code=Code.METHOD_NOT_ALLOWED)
            _payload = TlvEncoder._resource_to_tlv(model, obj, inst, res)
            msg = Message(code=Code.CONTENT, payload=_payload, content_format=MediaType.TLV.value)
            return msg

    @staticmethod
    def _instance_to_tlv(model, obj, inst):
        _buf = bytearray()
        for res in model.resources(obj, inst):
            if model.is_resource_readable(obj, inst, res):
                _buf.extend(TlvEncoder._resource_to_tlv(model, obj, inst, res))
        return TlvEncoder._pack(TlvType.OBJECT_INSTANCE, int(inst), payload=_buf)

    @staticmethod
    def _resource_to_tlv(model, obj, inst, res):
        _r = model.resource(obj, inst, res)
        if model.is_resource_multi_instance(obj, inst, res):
            if not isinstance(_r, dict):
                raise TypeError(f'multiple resource {obj}/{inst}/{res} must be of "dict" type')
            # MULTIPLE_RESOURCE ( RESOURCE_INSTANCE, RESOURCE_INSTANCE... )
            _buf = bytearray()
            for _res_inst in _r.keys():
                _buf.extend(
                    TlvEncoder._pack(
                        TlvType.RESOURCE_INSTANCE,
                        int(_res_inst),
                        TlvEncoder._get_resource_payload(model, obj, inst, res, _res_inst),
                    )
                )
            return TlvEncoder._pack(TlvType.MULTIPLE_RESOURCE, int(res), _buf)
        else:
            # RESOURCE_VALUE (single)
            return TlvEncoder._pack(
                TlvType.RESOURCE_VALUE, int(res), TlvEncoder._get_resource_payload(model, obj, inst, res)
            )

    @staticmethod
    def _pack(tlv_type, _id, payload):
        result = bytearray()
        _type = int(tlv_type.value)
        _len = len(payload)
        _type |= 0b000000 if 1 == needs_bytes(_id) else 0b100000
        if _len < 8:
            _type |= _len
        elif needs_bytes(_len) == 1:
            _type |= 0b00001000
        elif needs_bytes(_len) == 2:
            _type |= 0b00010000
        else:
            _type |= 0b00011000
        result.append(_type)
        result.extend(_id.to_bytes(1, byteorder="big") if _id < 256 else _id.to_bytes(2, byteorder="big"))
        if _len >= 8:
            if _len < 256:
                result.extend(_len.to_bytes(1, byteorder="big"))
            elif _len < 65536:
                result.extend(_len.to_bytes(2, byteorder="big"))
            else:
                msb = _len & 0xFF0000 >> 16
                result.extend(msb.to_bytes(1, byteorder="big"))
                result.extend((_len & 0xFFFF).to_bytes(2, byteorder="big"))
        result.extend(payload)
        return result

    @staticmethod
    def _get_resource_payload(model, obj, inst, res, res_idx=None):
        _type = model.definition[obj]["resourcedefs"][str(res)]["type"]
        if res_idx is not None:
            _content = model.resource(obj, inst, res)[res_idx]
            logger.debug(f'_resource_to_tlv(): {obj}/{inst}/{res}, idx={res_idx}, type={_type}, content="{_content}"')
        else:
            _content = model.resource(obj, inst, res)
            logger.debug(f'_resource_to_tlv(): {obj}/{inst}/{res}, type={_type}, content="{_content}"')
        if _type == "integer":
            i = int(_content)
            _payload = i.to_bytes(int(i.bit_length() / 8) + 1, byteorder="big", signed=True)
        elif _type == "string":
            _payload = _content.encode()
        elif _type == "float":
            f = float(_content)
            if float.fromhex("0x0.000002P-126") <= f <= float.fromhex("0x1.fffffeP+127"):
                # fits in a float
                _payload = pack(">f", f)
            else:
                # use double
                _payload = pack(">d", f)
        elif _type == "boolean":
            _payload = b"\x01" if _content else b"\x00"
        elif _type == "time":
            _payload = pack(">q", int(_content))
        elif _type == "opaque":
            _payload = bytearray.fromhex(_content)
        else:
            raise TypeError(
                f"unknown resource type: {_type}. Must be one of (integer,string,float,boolean,time,opaque)"
            )
        return _payload


class DecoderException(BaseException):
    def __init__(self, message):
        super(DecoderException, self).__init__(message)
        self.message = message

    def __str__(self):
        return self.message


class TextDecoder(object):
    def __init__(self):
        pass

    @staticmethod
    def decode(_model, path, payload):
        _obj = path[0]
        _inst = path[1]
        _res = path[2]
        result = dict()
        result[_obj] = dict()
        result[_obj][_inst] = dict()
        _payload = payload.decode()
        _type = _model.definition[_obj]["resourcedefs"][str(_res)]["type"]
        if _type == "integer":
            result[_obj][_inst][_res] = int(_payload)
        elif _type == "string":
            result[_obj][_inst][_res] = _payload
        elif _type == "float":
            result[_obj][_inst][_res] = float(_payload)
        elif _type == "boolean":
            result[_obj][_inst][_res] = True if _payload == "1" else False
        elif _type == "time":
            result[_obj][_inst][_res] = int(_payload)
        elif _type == "opaque":
            result[_obj][_inst][_res] = payload.hex()
        else:
            raise TypeError(f"unknown type: {_type}")
        logger.debug(f"result of TEXT decoding: {result}")
        return result


class OpaqueDecoder(object):
    def __init__(self):
        pass

    @staticmethod
    def decode(_model, path, payload):
        _obj = path[0]
        _inst = path[1]
        _res = path[2]
        result = dict()
        result[_obj] = dict()
        result[_obj][_inst] = dict()
        _type = _model.definition[_obj]["resourcedefs"][str(_res)]["type"]
        if _type != "opaque":
            raise TypeError(f"unsupported type: {_type}")

        result[_obj][_inst][_res] = payload.hex()

        logger.debug(f"result of OPAQUE decoding: {result}")
        return result


class TlvDecoder(object):
    def __init__(self):
        pass

    @staticmethod
    def decode(_model, path, payload):
        _payload = payload
        result = dict()
        while len(_payload) != 0:
            _id, _value, _type, _payload = TlvDecoder._decode(path, _payload)
            if _type >> 6 == 0b00:
                # object instance
                new_path = list(path)
                new_path.append(str(_id))
                _value = TlvDecoder.decode(_model, new_path, _value)
            else:
                _value = TlvDecoder.value_from_bytes(
                    _model,
                    (
                        path[0],
                        path[1] if len(path) > 1 else "0",
                        str(_id),
                    ),
                    _value,
                )
            result = dict(mergedicts(result, _value))
        logger.debug(f"decode result: {result}")
        return result

    @staticmethod
    def value_from_bytes(_model, path, payload):
        _obj = path[0]
        _inst = path[1]
        _res = path[2]
        result = dict()
        result[_obj] = dict()
        result[_obj][_inst] = dict()
        _type = _model.definition[_obj]["resourcedefs"][str(_res)]["type"]
        if _type == "integer":
            result[_obj][_inst][_res] = int.from_bytes(payload, byteorder="big")
        elif _type == "string":
            result[_obj][_inst][_res] = payload.decode()
        elif _type == "float":
            result[_obj][_inst][_res] = unpack("f", payload)
        elif _type == "boolean":
            result[_obj][_inst][_res] = True if payload[0] == 1 else False
        elif _type == "time":
            result[_obj][_inst][_res] = int.from_bytes(payload, byteorder="big")
        elif _type == "opaque":
            result[_obj][_inst][_res] = payload.hex()
        else:
            raise TypeError(f"unknown type: {_type}")
        logger.debug(f"decoding result: {result}")
        return result

    @staticmethod
    def _decode(path, payload):
        try:
            _type = payload[0]
        except IndexError:
            raise DecoderException("invalid TLV length")
        _len_type = _type >> 3 & 0b11
        _len = None
        if _len_type == 0:
            _len = _type & 0b111
            logger.debug(f"Value length: {_len} bytes")
        elif _len_type == 1:
            logger.debug("length's length: 8 bits")
        elif _len_type == 2:
            logger.debug("length's length: 16 bits")
        elif _len_type == 3:
            logger.debug("length's length: 24 bits")
        id_len = _type >> 5 & 1
        try:
            _payload = payload[1:]
        except IndexError:
            raise DecoderException("unable to determine ID from invalid payload")

        _id = None
        if id_len == 1:
            logger.debug("ID: 16 bits")
            try:
                _id = int.from_bytes(_payload[0:2], byteorder="big")
                logger.debug(f"ID: {_id}")
                _payload = _payload[2:]
            except IndexError:
                raise DecoderException("missing ID bytes in TLV")
        elif id_len == 0:
            logger.debug("ID length: 8 bits")
            try:
                _id = int.from_bytes(_payload[0:1], byteorder="big")
                logger.debug(f"ID: {_id}")
                _payload = _payload[1:]
            except IndexError:
                raise DecoderException("missing ID bytes in TLV")
        else:
            raise DecoderException("invalid ID length")
        try:
            if _len is None:
                _len = int.from_bytes(_payload[0:_len_type], byteorder="big")
                logger.info(f"value length: {_len}")
                _payload = _payload[_len_type:]
            _value = _payload[0:_len]
        except IndexError:
            raise DecoderException("not enough bytes for TLV value in payload")

        if _type >> 6 == 0b00:
            # OBJECT_INSTANCE
            logger.debug("type = OBJECT_INSTANCE")
            pass
        elif _type >> 6 == 0b01:
            # RESOURCE_INSTANCE
            logger.debug("type = RESOURCE_INSTANCE")
            pass
        elif _type >> 6 == 0b10:
            # MULTIPLE_RESOURCE
            logger.debug("type = MULTIPLE_RESOURCE")
            pass
        elif _type >> 6 == 0b11:
            # RESOURCE_VALUE
            logger.debug("type = RESOURCE_VALUE")
            pass
        else:
            raise DecoderException(f"invalid TLV type: {_type >> 6}")
        return _id, _value, _type, _payload[_len:]


class PayloadEncoder(object):
    def __init__(self, _model):
        self.model = _model

    def encode(self, path):
        if not self.model.is_path_valid(path):
            return Message(code=Code.NOT_FOUND)
        path_len = len(path)
        if path_len == 1:
            # read on whole object (SenML CBOR)
            return SenmlCborEncoder.encode_object(self.model, path[0])
        elif path_len == 2:
            # read on instance (SenML CBOR)
            return SenmlCborEncoder.encode_object_instance(self.model, path[0], path[1])
        elif path_len == 3:
            return SenmlCborEncoder.encode_resource(self.model, path[0], path[1], path[2])
        else:
            return Message(code=Code.BAD_REQUEST)


class PayloadDecoder(object):
    def __init__(self, _model):
        self.model = _model

    def decode(self, path, payload, content_format):
        if not self.model.is_path_valid(path):
            return Message(code=Code.NOT_FOUND), None
        try:
            if content_format == MediaType.TLV.value:
                return Message(code=Code.CHANGED), TlvDecoder.decode(self.model, path, payload)
            if content_format == MediaType.SENML_CBOR.value:
                return Message(code=Code.CHANGED), SenmlCborDecoder.decode(self.model, path, payload)
            elif content_format == MediaType.TEXT.value:
                if len(path) != 3 or self.model.is_resource_multi_instance(path[0], path[1], path[2]):
                    raise Exception("TEXT format should only be used for single non-multiple resource")
                return Message(code=Code.CHANGED), TextDecoder.decode(self.model, path, payload)
            elif content_format == MediaType.OPAQUE.value:
                if len(path) != 3 or self.model.is_resource_multi_instance(path[0], path[1], path[2]):
                    raise Exception("OPAQUE format should only be used for single non-multiple resource")
                return Message(code=Code.CHANGED), OpaqueDecoder.decode(self.model, path, payload)
            else:
                raise Exception(f"unsupported content format: {content_format}")
        except DecoderException as e:
            return Message(code=Code.BAD_REQUEST, payload=e.message.encode()), None


class SenmlCborLabel(Enum):
    BASE_VERSION = -1
    BASE_NAME = -2
    BASE_TIME = -3
    BASE_UNIT = -4
    BASE_VALUE = -5
    BASE_SUM = -6
    NAME = 0
    UNIT = 1
    VALUE = 2
    STRING_VALUE = 3
    BOOLEAN_VALUE = 4
    SUM = 5
    TIME = 6
    UPDATE_TIME = 7
    DATA_VALUE = 8
    OBJECT_LINK = "vlo"


class SenmlCborDecoder:
    @staticmethod
    def decode(_model, path, payload):
        data = cbor2.loads(payload)
        base_name = ""
        result = {}
        for d in data:
            if SenmlCborLabel.BASE_NAME.value in d:
                base_name = d[SenmlCborLabel.BASE_NAME.value]
            name = d[SenmlCborLabel.NAME.value]
            path = tuple(f"{base_name}{name}".split("/")[1:])
            decoded = SenmlCborDecoder._value_from_bytes(_model, path, d)
            result = dict(mergedicts(result, decoded))
        return result

    @staticmethod
    def _value_from_bytes(_model, path, payload):
        _obj = path[0]
        _inst = path[1]
        _res = path[2]
        result = dict()
        result[_obj] = dict()
        result[_obj][_inst] = dict()

        res_def = _model.definition[_obj]["resourcedefs"][str(_res)]
        res_multi_inst = res_def["instancetype"] == "multiple"
        _type = res_def["type"]

        base_dict = result[_obj][_inst]
        new_key = _res

        if res_multi_inst:
            _res_inst = path[3]
            result[_obj][_inst][_res] = dict()
            base_dict = result[_obj][_inst][_res]
            new_key = _res_inst
        if _type == "integer" or _type == "unsigned integer":
            base_dict[new_key] = payload[SenmlCborLabel.VALUE.value]
        elif _type == "string":
            base_dict[new_key] = payload[SenmlCborLabel.STRING_VALUE.value]
        elif _type == "float":
            base_dict[new_key] = payload[SenmlCborLabel.VALUE.value]
        elif _type == "boolean":
            base_dict[new_key] = payload[SenmlCborLabel.BOOLEAN_VALUE.value]
        elif _type == "time":
            base_dict[new_key] = payload[SenmlCborLabel.VALUE.value]
        elif _type == "opaque":
            base_dict[new_key] = payload[SenmlCborLabel.DATA_VALUE.value]
        elif _type == "objlnk":
            base_dict[new_key] = payload[SenmlCborLabel.OBJECT_LINK.value]
        else:
            raise TypeError(f"unknown type: {_type}")
        logger.debug(f"decoding result: {result}")
        return result


class SenmlCborEncoder:
    @staticmethod
    def encode_multiple_objects(model, objects):
        data = []
        for obj in objects:
            obj_data = []
            for inst in model.instances(obj):
                base_name = f"/{obj}/{inst}/"
                obj_data.extend(SenmlCborEncoder._object_instance_to_senml_cbor(model, obj, inst))
            data.extend(SenmlCborEncoder._strip_name_prefix_and_add_basename(obj_data, base_name))

        buf = cbor2.dumps(data)
        msg = Message(code=Code.CONTENT, payload=buf, content_format=MediaType.SENML_CBOR.value)
        return msg

    @staticmethod
    def encode_object(model, obj):
        base_name = f"/{obj}/"
        data = []
        for inst in model.instances(obj):
            data.extend(SenmlCborEncoder._object_instance_to_senml_cbor(model, obj, inst))
        data = SenmlCborEncoder._strip_name_prefix_and_add_basename(data, base_name)
        buf = cbor2.dumps(data)
        msg = Message(code=Code.CONTENT, payload=buf, content_format=MediaType.SENML_CBOR.value)
        return msg

    @staticmethod
    def encode_object_instance(model, obj, inst):
        base_name = f"/{obj}/{inst}/"
        data = SenmlCborEncoder._object_instance_to_senml_cbor(model, obj, inst)
        data = SenmlCborEncoder._strip_name_prefix_and_add_basename(data, base_name)
        buf = cbor2.dumps(data)
        msg = Message(code=Code.CONTENT, payload=buf, content_format=MediaType.SENML_CBOR.value)
        return msg

    @staticmethod
    def encode_resource(model, obj, inst, res):
        base_name = f"/{obj}/{inst}/{res}/"
        data = SenmlCborEncoder._resource_to_senml_cbor(model, obj, inst, res)
        data = SenmlCborEncoder._strip_name_prefix_and_add_basename(data, base_name)
        buf = cbor2.dumps(data)
        msg = Message(code=Code.CONTENT, payload=buf, content_format=MediaType.SENML_CBOR.value)
        return msg

    @staticmethod
    def _strip_name_prefix_and_add_basename(entries, base_name):
        if len(entries) > 1:

            def strip_name(entry):
                entry[SenmlCborLabel.NAME.value] = entry[SenmlCborLabel.NAME.value].removeprefix(base_name)
                return entry

            entries = [strip_name(e) for e in entries]
            entries[0].update({SenmlCborLabel.BASE_NAME.value: base_name})
        return entries

    @staticmethod
    def _object_instance_to_senml_cbor(model, obj, inst):
        cbor_resources = []
        for res in model.resources(obj, inst):
            if model.is_resource_readable(obj, inst, res):
                cbor_resources.extend(SenmlCborEncoder._resource_to_senml_cbor(model, obj, inst, res))
        return cbor_resources

    @staticmethod
    def _resource_to_senml_cbor(model, obj, inst, res):
        _r = model.resource(obj, inst, res)
        if model.is_resource_multi_instance(obj, inst, res):
            if type(_r) is not dict:
                raise TypeError(f'multiple resource {obj}/{inst}/{res} must be of "dict" type')
            # MULTIPLE_RESOURCE ( RESOURCE_INSTANCE, RESOURCE_INSTANCE... )
            cbor_data = []
            for _res_inst, _res_val in _r.items():
                name = f"/{obj}/{inst}/{res}/{_res_inst}"

                res_data = {SenmlCborLabel.NAME.value: name}
                senml_cbor_label = SenmlCborEncoder._resource_type_to_senml_cbor_label(
                    model.definition[obj]["resourcedefs"][str(res)]["type"]
                )
                inst_data = {senml_cbor_label.value: _res_val}
                res_data.update(inst_data)
                cbor_data.append(res_data)
            return cbor_data
        else:
            # RESOURCE_VALUE (single)
            name = f"/{obj}/{inst}/{res}"
            res_data = {0: name}
            _res_val = model.resource(obj, inst, res)
            _type = model.definition[obj]["resourcedefs"][str(res)]["type"]
            _res_val = SenmlCborEncoder._to_type(_res_val, _type)
            label = SenmlCborEncoder._resource_type_to_senml_cbor_label(_type)
            inst_data = {label.value: _res_val}
            res_data.update(inst_data)

            return [res_data]

    @staticmethod
    def _resource_type_to_senml_cbor_label(_type) -> SenmlCborLabel:
        if _type == "integer" or _type == "unsigned integer":
            return SenmlCborLabel.VALUE
        elif _type == "string":
            return SenmlCborLabel.STRING_VALUE
        elif _type == "float":
            return SenmlCborLabel.VALUE
        elif _type == "boolean":
            return SenmlCborLabel.BOOLEAN_VALUE
        elif _type == "time":
            return SenmlCborLabel.VALUE
        elif _type == "opaque":
            return SenmlCborLabel.DATA_VALUE
        elif _type == "objlnk":
            return SenmlCborLabel.OBJECT_LINK
        else:
            raise TypeError(
                f"unknown resource type: {_type}."
                f" Must be one of (integer,unsigned integer,string,float,boolean,time,opaque,objlnk)"
            )

    @staticmethod
    def _to_type(data, _type):
        if _type == "integer" or _type == "unsigned integer":
            return int(data)
        elif _type == "string":
            return data
        elif _type == "float":
            return float(data)
        elif _type == "boolean":
            return bool(data)
        elif _type == "opaque":
            if isinstance(data, str):
                return bytearray.fromhex(data)
            else:
                return bytearray(data)
        elif _type == "time":
            return int(data)
        elif _type == "objlnk":
            return str(data)
        else:
            raise TypeError(
                f"unknown resource type: {_type}."
                f" Must be one of (integer,unsigned integer,string,float,boolean,time,opaque,objlnk)"
            )
