# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

from pathlib import Path

import cbor2
from bnw.tfw.device.component.harness._lwm2m.encdec import (
    SenmlCborDecoder,
    SenmlCborEncoder,
    TlvDecoder,
    TlvEncoder,
)
from bnw.tfw.device.component.harness._lwm2m.model import ClientModel


def test_tlv_encode_instance():
    data = {"0": {"0": {"3": "deadbeef"}}}
    model = ClientModel(data=data)
    model.definition["0"]["resourcedefs"]["3"]["operations"] = "R"
    res = TlvEncoder.encode_instance(model, "0", "0")
    assert res.payload == b"\x06\x00\xc4\x03\xde\xad\xbe\xef"


def test_tlv_decode_instance():
    payload = b"\x10\x00\x01\xa4\xd0\x03\x01\xa0\xc0\xde"

    model = ClientModel()
    res = TlvDecoder.decode(model, ("0", "0"), payload)
    assert res == {"0": {"0": {"3": "c0de"}}}


def _make_resources_readable(model):
    for d in model.definition.keys():
        for _, resource_def in model.definition[d]["resourcedefs"].items():
            resource_def["operations"] = "R"


def assert_cbor(actual, expected):
    # parsed CBOR is easier to debug...
    parsed_actual = cbor2.loads(actual)
    parsed_expected = cbor2.loads(expected)
    assert parsed_actual == parsed_expected, f"Got CBOR: {actual}"
    # ...but also assert CBOR ist correctly encoded
    # sort each entry to have deterministic CBOR output
    parsed_actual = [dict(sorted(e.items())) for e in parsed_actual]
    parsed_expected = [dict(sorted(e.items())) for e in parsed_expected]
    assert cbor2.dumps(parsed_actual) == cbor2.dumps(parsed_expected)


def test_senml_cbor_encode_object_instance_security():
    # incomplete model just for testing
    # encode
    initial_data = {"0": {"0": {"2": 2, "3": b"deadbeef"}}}
    model = ClientModel(data=initial_data)
    _make_resources_readable(model)
    encoded_res = SenmlCborEncoder.encode_object_instance(model, "0", "0")
    expected = [{0: "2", 2: 2, -2: "/0/0/"}, {0: "3", 8: b"deadbeef"}]
    actual = encoded_res.payload
    expected = cbor2.dumps(expected)
    assert_cbor(actual, expected)

    # decode
    model = ClientModel()
    decoded = SenmlCborDecoder.decode(model, ("0", "0"), encoded_res.payload)
    assert decoded == initial_data


def test_senml_cbor_encode_decode_resource_security_pub_key():
    # encode
    initial_data = {"0": {"0": {"3": b"deadbeef"}}}
    model = ClientModel(data=initial_data)
    _make_resources_readable(model)
    encoded_res = SenmlCborEncoder.encode_resource(model, "0", "0", "3")
    expected = [{0: "/0/0/3", 8: b"deadbeef"}]
    actual = encoded_res.payload
    expected = cbor2.dumps(expected)
    assert_cbor(actual, expected)

    # decode
    model = ClientModel()
    decoded = SenmlCborDecoder.decode(model, ("0", "0", "3"), encoded_res.payload)
    assert decoded == initial_data


def test_senml_cbor_encode_object_device():
    initial_data = {
        "3": {
            "0": {
                "0": "Open Mobile Alliance",
                "1": "Lightweight M2M Client",
                "2": "345000123",
                "3": "1.0",
                "6": {"0": 1, "1": 5},
                "7": {"0": 3800, "1": 5000},
                "8": {"0": 125, "1": 900},
                "9": 100,
                "10": 15,
                "11": {"0": 0},
                "13": 1367491215,
                "14": "+02:00",
                "16": "U",
            },
            "1": {
                "0": "Gardena",
                "1": "dev",
                "2": "345000111",
                "3": "1.1",
                "6": {"0": 3},
                "7": {"0": 300, "1": 3000},
                "8": {"1": 800},
                "9": 99,
                "10": 5,
                "11": {"0": 1},
                "13": 1367491217,
                "14": "+03:00",
                "16": "U",
            },
        }
    }
    model = ClientModel(data=initial_data)
    _make_resources_readable(model)
    encoded_res = SenmlCborEncoder.encode_object(model, "3")
    actual = encoded_res.payload
    expected = [
        {-2: "/3/", 0: "0/0", 3: "Open Mobile Alliance"},
        {0: "0/1", 3: "Lightweight M2M Client"},
        {0: "0/2", 3: "345000123"},
        {0: "0/3", 3: "1.0"},
        {0: "0/6/0", 2: 1},
        {0: "0/6/1", 2: 5},
        {0: "0/7/0", 2: 3800},
        {0: "0/7/1", 2: 5000},
        {0: "0/8/0", 2: 125},
        {0: "0/8/1", 2: 900},
        {0: "0/9", 2: 100},
        {0: "0/10", 2: 15},
        {0: "0/11/0", 2: 0},
        {0: "0/13", 2: 1367491215},
        {0: "0/14", 3: "+02:00"},
        {0: "0/16", 3: "U"},
        {0: "1/0", 3: "Gardena"},
        {0: "1/1", 3: "dev"},
        {0: "1/2", 3: "345000111"},
        {0: "1/3", 3: "1.1"},
        {0: "1/6/0", 2: 3},
        {0: "1/7/0", 2: 300},
        {0: "1/7/1", 2: 3000},
        {0: "1/8/1", 2: 800},
        {0: "1/9", 2: 99},
        {0: "1/10", 2: 5},
        {0: "1/11/0", 2: 1},
        {0: "1/13", 2: 1367491217},
        {0: "1/14", 3: "+03:00"},
        {0: "1/16", 3: "U"},
    ]
    expected = cbor2.dumps(expected)
    assert_cbor(actual, expected)

    # decode
    model = ClientModel()
    decoded = SenmlCborDecoder.decode(model, ("0", "0", "3"), encoded_res.payload)
    assert decoded == initial_data


def test_senml_cbor_encode_object_instance_device():
    initial_data = {
        "3": {
            "0": {
                "0": "Open Mobile Alliance",
                "1": "Lightweight M2M Client",
                "2": "345000123",
                "3": "1.0",
                "6": {"0": 1, "1": 5},
                "7": {"0": 3800, "1": 5000},
                "8": {"0": 125, "1": 900},
                "9": 100,
                "10": 15,
                "11": {"0": 0},
                "13": 1367491215,
                "14": "+02:00",
                "16": "U",
            }
        }
    }
    model = ClientModel(data=initial_data)
    _make_resources_readable(model)
    encoded_res = SenmlCborEncoder.encode_object_instance(model, "3", "0")
    actual = encoded_res.payload
    expected = [
        {-2: "/3/0/", 0: "0", 3: "Open Mobile Alliance"},
        {0: "1", 3: "Lightweight M2M Client"},
        {0: "2", 3: "345000123"},
        {0: "3", 3: "1.0"},
        {0: "6/0", 2: 1},
        {0: "6/1", 2: 5},
        {0: "7/0", 2: 3800},
        {0: "7/1", 2: 5000},
        {0: "8/0", 2: 125},
        {0: "8/1", 2: 900},
        {0: "9", 2: 100},
        {0: "10", 2: 15},
        {0: "11/0", 2: 0},
        {0: "13", 2: 1367491215},
        {0: "14", 3: "+02:00"},
        {0: "16", 3: "U"},
    ]
    expected = cbor2.dumps(expected)
    assert_cbor(actual, expected)

    # decode
    model = ClientModel()
    decoded = SenmlCborDecoder.decode(model, ("3", "0"), encoded_res.payload)
    assert decoded == initial_data


def test_prod_cbor():
    expected = [
        {
            0: "/0/0/3",
            8: b"0\x82\x01\x9c0\x82\x01A\xa0\x03\x02\x01\x02\x02\x10an\xcbJ\xc9\xa3\xed\xbeb\xc0Np|\xbeT\x0c0\n\x06"
            b"\x08*\x86H\xce=\x04\x03\x020\x161\x140\x12\x06\x03U\x04\x03\x0c\x0bsmartsystem0 \x17\r220704130715Z"
            b"\x18\x0f21220610130715Z0+1)0'\x06\x03U\x04\x03\x0c 7fdef25000e9401d87613775687dde570Y0\x13\x06\x07*"
            b"\x86H\xce=\x02\x01\x06\x08*\x86H\xce=\x03\x01\x07\x03B\x00\x04F\x84\xef\x18]\x18k\xc8a\xe8\xcb\x88"
            b"\xfb\xe3.\xfb\t\xf5\xdc\xef\xb0h\x97\xac\xa4{A\xe6\x8aa\x99\xe1I\x9d/I8\x0c\xef5\x9a\xe5U\xd3\xec"
            b"\xf8\xcbrG\xaeXN\xd5\xc4\xc5\x14;\xa8HR/D\xe9\xfb\xa3Z0X0\t\x06\x03U\x1d\x13\x04\x020\x000\x13\x06"
            b"\x03U\x1d%\x04\x0c0\n\x06\x08+\x06\x01\x05\x05\x07\x03\x020\x0b\x06\x03U\x1d\x0f\x04\x04\x03\x02\x07"
            b'\x800)\x06\x03U\x1d\x11\x04"0 \x86\x1esgtin:3014000000000040000000330\n\x06\x08*\x86H\xce=\x04\x03'
            b"\x02\x03I\x000F\x02!\x00\xf6\xe2\xf4g\x80@\x9e\xa9\xadZ\nd\xeeV\xea\x9cQ\x0b\x9f?\xdba\x14GLNd\xa9"
            b"\x8e\x96\xa3\xfb\x02!\x00\xc4\x80\xd6\xc0\x1e\x06\x91n\xa6\x9aF/\\\x04\xb4\x97\x88\xd3n\x0b\xaa\x0f"
            b"\x8e\xf2'\x98\xf2\xa9\n|Hy",
        }
    ]

    expected_cbor = cbor2.dumps(expected)

    key = (
        b"0\x82\x01\x9c0\x82\x01A\xa0\x03\x02\x01\x02\x02\x10an\xcbJ\xc9"
        b"\xa3\xed\xbeb\xc0Np|\xbeT\x0c0\n\x06\x08*\x86H\xce=\x04\x03\x020"
        b"\x161\x140\x12\x06\x03U\x04\x03\x0c\x0bsmartsystem0 \x17\r220704130715Z"
        b"\x18\x0f21220610130715Z0+1)0'\x06\x03U\x04\x03\x0c 7fdef25000e9401d87"
        b"613775687dde570Y0\x13\x06\x07*\x86H\xce=\x02\x01\x06\x08*\x86H"
        b"\xce=\x03\x01\x07\x03B\x00\x04F\x84\xef\x18]\x18k\xc8a\xe8\xcb"
        b"\x88\xfb\xe3.\xfb\t\xf5\xdc\xef\xb0h\x97\xac\xa4{A\xe6\x8aa\x99"
        b"\xe1I\x9d/I8\x0c\xef5\x9a\xe5U\xd3\xec\xf8\xcbrG\xaeXN\xd5\xc4\xc5"
        b"\x14;\xa8HR/D\xe9\xfb\xa3Z0X0\t\x06\x03U\x1d\x13\x04\x020\x00"
        b"0\x13\x06\x03U\x1d%\x04\x0c0\n\x06\x08+\x06\x01\x05\x05\x07\x03"
        b"\x020\x0b\x06\x03U\x1d\x0f\x04\x04\x03\x02\x07\x800)\x06\x03U\x1d"
        b'\x11\x04"0 \x86\x1esgtin:3014000000000040000000330\n\x06\x08*\x86H'
        b"\xce=\x04\x03\x02\x03I\x000F\x02!\x00\xf6\xe2\xf4g\x80@\x9e\xa9\xadZ\n"
        b"d\xeeV\xea\x9cQ\x0b\x9f?\xdba\x14GLNd\xa9\x8e\x96\xa3\xfb\x02!\x00"
        b"\xc4\x80\xd6\xc0\x1e\x06\x91n\xa6\x9aF/\\\x04\xb4\x97\x88\xd3n\x0b"
        b"\xaa\x0f\x8e\xf2'\x98\xf2\xa9\n|Hy"
    )

    initial_data = {"0": {"0": {"3": key}}}
    model = ClientModel(data=initial_data)
    _make_resources_readable(model)
    encoded_res = SenmlCborEncoder.encode_object_instance(model, "0", "0")

    assert_cbor(encoded_res.payload, expected_cbor)

    # decode
    model = ClientModel()
    decoded = SenmlCborDecoder.decode(model, ("0", "0"), encoded_res.payload)
    assert decoded == initial_data


def test_encode_ic24_registration():

    # Captured from ic24
    expected_cbor = bytes.fromhex(
        "92a321652f332f302f006130036747617264656e61a2006131036131a200613203683030303030303731a2006133036b302e302e302d33"
        "2e322e30a2006431312f300200a200623133020ca2006231340360a2006231350360a200623136036155a200623137036747656e657269"
        "63a2006231380365302e302e30a20062313903781b302e302e322b32392d67316336373837632d6465762d6469727479a321652f352f30"
        "2f0061310360a20061330200a20061350200a20061360360a20061370360a20061390201"
    )

    expected = [
        {-2: "/3/0/", 0: "0", 3: "Gardena"},
        {0: "1", 3: "1"},
        {0: "2", 3: "00000071"},
        {0: "3", 3: "0.0.0-3.2.0"},
        {0: "11/0", 2: 0},
        {0: "13", 2: 12},
        {0: "14", 3: ""},
        {0: "15", 3: ""},
        {0: "16", 3: "U"},
        {0: "17", 3: "Generic"},
        {0: "18", 3: "0.0.0"},
        {0: "19", 3: "0.0.2+29-g1c6787c-dev-dirty"},
        {-2: "/5/0/", 0: "1", 3: ""},
        {0: "3", 2: 0},
        {0: "5", 2: 0},
        {0: "6", 3: ""},
        {0: "7", 3: ""},
        {0: "9", 2: 1},
    ]
    assert_cbor(expected_cbor, cbor2.dumps(expected))

    initial_data = {
        "3": {
            "0": {
                "0": "Gardena",
                "1": "1",
                "2": "00000071",
                "3": "0.0.0-3.2.0",
                "11": {"0": 0},
                "13": 12,
                "14": "",
                "15": "",
                "16": "U",
                "17": "Generic",
                "18": "0.0.0",
                "19": "0.0.2+29-g1c6787c-dev-dirty",
            }
        },
        "5": {"0": {"1": "", "3": 0, "5": 0, "6": "", "7": "", "9": 1}},
    }
    model = ClientModel(data=initial_data)
    _make_resources_readable(model)
    encoded_res = SenmlCborEncoder.encode_multiple_objects(model, ["3", "5"])
    actual = encoded_res.payload
    assert_cbor(actual, cbor2.dumps(expected))

    # decode
    model = ClientModel()
    decoded = SenmlCborDecoder.decode(model, ("0", "0"), encoded_res.payload)
    assert decoded == initial_data


def test_decode_encode_testing_object():
    # Captured from zephyr_bnw_minimal
    cbor = bytes.fromhex(
        "981ca321692f33323736352f302f0061310360a20061330200a200613502fb0000000000000000a200613704f4a2006139085000000000"
        "000000000000000000000000a2006231310200a20062313363766c6f6b36353533353a3635353335a2006231350200a2006231390360a2"
        "006232310360a2006232340360a20063322f300360a20063322f310360a20063342f300200a20063342f310200a20063362f3002fb0000"
        "000000000000a20063362f3102fb0000000000000000a20063382f3004f4a20063382f3104f4a2006431302f3008500000000000000000"
        "0000000000000000a2006431302f31085000000000000000000000000000000000a2006431322f300200a2006431322f310200a2006431"
        "342f3063766c6f6b36353533353a3635353335a2006431342f3163766c6f6b36353533353a3635353335a2006431362f300200a2006431"
        "362f310200a2006232330360"
    )

    expected_diagnostic = [
        {-2: "/32765/0/", 0: "1", 3: ""},
        {0: "3", 2: 0},
        {0: "5", 2: 0.0},
        {0: "7", 4: False},
        {0: "9", 8: b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"},
        {0: "11", 2: 0},
        {0: "13", "vlo": "65535:65535"},
        {0: "15", 2: 0},
        {0: "19", 3: ""},
        {0: "21", 3: ""},
        {0: "24", 3: ""},
        {0: "2/0", 3: ""},
        {0: "2/1", 3: ""},
        {0: "4/0", 2: 0},
        {0: "4/1", 2: 0},
        {0: "6/0", 2: 0.0},
        {0: "6/1", 2: 0.0},
        {0: "8/0", 4: False},
        {0: "8/1", 4: False},
        {0: "10/0", 8: b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"},
        {0: "10/1", 8: b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"},
        {0: "12/0", 2: 0},
        {0: "12/1", 2: 0},
        {0: "14/0", "vlo": "65535:65535"},
        {0: "14/1", "vlo": "65535:65535"},
        {0: "16/0", 2: 0},
        {0: "16/1", 2: 0},
        {0: "23", 3: ""},
    ]
    expected_cbor = cbor2.dumps(expected_diagnostic)
    assert cbor == expected_cbor

    # decode
    model = ClientModel.from_ipso_spec(Path(__file__).parent / "ipso_registry")
    decoded = SenmlCborDecoder.decode(model, ("32765", "0"), cbor)
    model.data = decoded
    encoded = SenmlCborEncoder.encode_object_instance(model, "32765", "0")

    # sort according to base name & name
    parsed_expected_diagnostic = sorted(cbor2.loads(cbor), key=lambda e: e.get(-2, "/65535/65535/65535/") + "-" + e[0])
    parsed_actual_diagnostic = sorted(
        cbor2.loads(encoded.payload), key=lambda e: e.get(-2, "/65535/65535/65535/") + "-" + e[0]
    )
    # compare if content is the same
    assert parsed_actual_diagnostic == parsed_expected_diagnostic
