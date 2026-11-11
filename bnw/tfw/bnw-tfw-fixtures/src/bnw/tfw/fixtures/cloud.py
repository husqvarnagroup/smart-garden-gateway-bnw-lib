# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

from contextlib import contextmanager
from typing import Callable, ContextManager, Optional

import pytest
import pytest_asyncio
from bnw.tfw.component.harness.cloud import AwsIotCloud
from bnw.transport.mqtt.awsiot import AwsMqttClientMqttConnection


@pytest.fixture(scope="session")
def cloud_factory(
    cloud_server_private_key, cloud_server_public_key_chain, cloud_ca_public_key
) -> Callable[[str, int, Optional[int]], ContextManager[AwsIotCloud]]:
    @contextmanager
    def factory(ip, port, ws_port=None, rest_port=None, loop=None):
        with AwsIotCloud.factory(
            ip,
            port,
            cloud_server_private_key,
            cloud_server_public_key_chain,
            cloud_ca_public_key,
            ws_port=ws_port,
            rest_port=rest_port,
            loop=loop,
        ) as cloud:
            yield cloud

    return factory


@pytest.fixture
def cloud_endpoint_port(find_free_port):
    return find_free_port()


@pytest.fixture
def cloud_endpoint_ip():
    return "127.0.0.1"


@pytest_asyncio.fixture
async def cloud(cloud_factory, cloud_endpoint_ip, cloud_endpoint_port, request):
    try:
        cloud_endpoint_ws_port = request.getfixturevalue("cloud_endpoint_ws_port")
    except LookupError:
        cloud_endpoint_ws_port = None

    try:
        cloud_endpoint_rest_port = request.getfixturevalue("cloud_endpoint_rest_port")
    except LookupError:
        cloud_endpoint_rest_port = None

    with cloud_factory(
        cloud_endpoint_ip, cloud_endpoint_port, cloud_endpoint_ws_port, cloud_endpoint_rest_port
    ) as cloud:
        async with cloud:
            yield cloud


@pytest.fixture
def cloud_awsclient_mqtt_connection(
    cloud, cloud_ca_public_key, cloud_client_public_key_chain, cloud_client_private_key, request
) -> AwsMqttClientMqttConnection:
    try:
        cloud_client_name = request.getfixturevalue("cloud_client_name")
    except LookupError:
        cloud_client_name = "test"
    return AwsMqttClientMqttConnection(
        cloud.endpoint,
        cloud_client_name,
        cloud_ca_public_key,
        cloud_client_public_key_chain,
        cloud_client_private_key,
    )


@pytest.fixture(scope="session")
def cloud_server_public_key_chain(cloud_server_public_key, cloud_ca_public_key):
    return cloud_server_public_key + b"\n" + cloud_ca_public_key


@pytest.fixture(scope="session")
def cloud_client_public_key_chain(cloud_client_public_key, cloud_ca_public_key):
    return cloud_client_public_key + b"\n" + cloud_ca_public_key


@pytest.fixture(scope="session")
def cloud_server_private_key():
    return b"""-----BEGIN PRIVATE KEY-----
MIIEuwIBADANBgkqhkiG9w0BAQEFAASCBKUwggShAgEAAoIBAQCkUMDP3MMtUByi
NG6p4zUI/ab1GRVG/ahbVaAfTz3YX/kwpVn/bBLYiTyA4kButp31E5f40UNRHViV
OCrmKV/zgzs98O7xbSH/MbpknjTql/PlCP1kPJQXIId+DnMoTlVDH4k2tBsS9t8z
KnGH+I9ByWAOGi+XqmFXKJVeqYUH2i6PKuYTu7yTlVM9vHMHm7W0bz4y1I2u48QT
6VajF6J+NEKbncbIc/jn2PgsLwIsXu16PY2VQ6InFXmpUn9WMrTgL0Te2H0mGnt/
NnZOfaiA77CNatKrUoi/HP6irQWwrHpP9BADYdtSIn5oFyhnj4qpBLAydcn5YRqI
VUtfnddDAgMBAAECggEAA1dC/Fb0PvUch+3B/EFK4EJsBRq79IQOysCcb1aInuAg
rG0IPenAHlf3+3TeM4ISBxwdYGk80abjmLEaKjDYKxbVewZtjUoXQV2M+SPAVq69
PkBnCoUyy5+VMapwi/a/xAwdmZei30lWs28e/NFAdGl4QwEkS5SiwwdnthODSWwN
YLi2vyqS16CQunB3j4kx2+hGPdUZKBhGUHEIj8hPRPK2YBLOAs6qgB71NcbCWVBK
PaJpPRGdWQNNUsMViStBJ357ncznEET/7L8zuY7dksirIHNGqz0GUQRKGLC7URxu
ptEneQ9pul0u5TZaFkTB/VVX+ul4pGtQ2w+RuajVxQKBgQDZJSx/6xztvb9SrGPm
suPnmu253xLBDWB53eV8TnV/Jc65iS5HVGigaGG7fGmJcxlHeajRxGYF8IocytZu
GEgBEDtWEzQQa+EdPXp1sFAb8wp4BfZXxAhuTFz5+7d0+IsoAG/7TUqhAWJ7HOun
+Sxc2lHV7wP8/ahX1CWsoy3d3wKBgQDBt5e3i2eSX/zvLhQOrw+4XtXs0eoli5/W
UjCdwIiTfnCdxBytimRuJwCiqEjbjjXiV62jOna+9lj2dO60r/r4co5gSLV0F0tL
SRtMpb/Svtbsz51g9uj54Dz4dNlSgKfZ5kV9eLr0bTNtXS6EontWIpdRtoinD4Sk
qSdNz0DrHQJ/WQ/mMJE+TESHNGGAmB7HWzcwSgw0pPnXmCRq+5Eyn/Ph1jdtw9Pb
Fe+6JivhHX8X3zkHBQKI1ebSvvxy9rT+03DU5Xj64cFdk6CjmaG3Ob91i8TmRRki
XBr2B5I2rMNEUCPdyjTpZyAqRFSYU0zf5TWmWxitihZ/9YYN7cEADwKBgFeYsGdU
B2KeOx7gxDsbmE0zvSKYjXuq1n0wr0E2ZcvkWgJNQvaKZP2Wb2geFswJU35lTWRJ
NJcHiJTxrVtRVHhyPMV3O24idm61wT14mfQvTbrJ6w2EuTb82jUziW4QNVaIFRY2
uLt8gcvLXhSl8IWzoJ9XnhWFI+LdhqNdu6pVAoGBALvcoYFOdg4hDGgVj8LMAUNW
SlTqrJjlG5HubDcWjXIZqj2Q8VLpyAGpFGzs83rocDrVff4PcPX4P8Id/9LEDFhx
opyDo3p+7oFLG+VY5nBLweep7fPGGzpNZPMoeuR3kykFSeepzTSB23Bfp4Cuuyou
yFc4gytiyllGwwWOjrvn
-----END PRIVATE KEY-----
"""


@pytest.fixture(scope="session")
def cloud_server_public_key():
    return b"""-----BEGIN CERTIFICATE-----
MIIDbjCCAlYCFCVIFvF1oXUMiksA7YvEKNPPuUr+MA0GCSqGSIb3DQEBCwUAMHIx
CzAJBgNVBAYTAkNIMQswCQYDVQQIDAJaSDEPMA0GA1UEBwwGWnVyaWNoMRUwEwYD
VQQKDAxHQVJERU5BIEdtYkgxGzAZBgNVBAsMEmRpZ2l0YWwgaHViIFp1cmljaDER
MA8GA1UEAwwIY2xvdWQtY2EwIBcNMjMxMDEwMTYzODUzWhgPMjEyMzA5MTYxNjM4
NTNaMHMxCzAJBgNVBAYTAkNIMQswCQYDVQQIDAJaSDEPMA0GA1UEBwwGWnVyaWNo
MRUwEwYDVQQKDAxHQVJERU5BIEdtYkgxGzAZBgNVBAsMEmRpZ2l0YWwgaHViIFp1
cmljaDESMBAGA1UEAwwJMTI3LjAuMC4xMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8A
MIIBCgKCAQEApFDAz9zDLVAcojRuqeM1CP2m9RkVRv2oW1WgH0892F/5MKVZ/2wS
2Ik8gOJAbrad9ROX+NFDUR1YlTgq5ilf84M7PfDu8W0h/zG6ZJ406pfz5Qj9ZDyU
FyCHfg5zKE5VQx+JNrQbEvbfMypxh/iPQclgDhovl6phVyiVXqmFB9oujyrmE7u8
k5VTPbxzB5u1tG8+MtSNruPEE+lWoxeifjRCm53GyHP459j4LC8CLF7tej2NlUOi
JxV5qVJ/VjK04C9E3th9Jhp7fzZ2Tn2ogO+wjWrSq1KIvxz+oq0FsKx6T/QQA2Hb
UiJ+aBcoZ4+KqQSwMnXJ+WEaiFVLX53XQwIDAQABMA0GCSqGSIb3DQEBCwUAA4IB
AQB5jNkHdiUXp4NtZJxsmZelL5qlLwK6NJR6r+tnSF4Wi2c4D/g/eTbPB/yE9eIP
l5xZNpChyRa+baZcQJoZeuKucRx/ylTElbUVy2JEqJ7utTLYnU0RNE9GqGtcVv+K
6prFhGcyEQPm1nZYpD8T/knjbsl+B0MMvyJzJ9Azdq/CpSnS3dwTeVTYQyje+F6v
W3R6BdPc/OxpW38YJehirwkV89qDONeZu2d1zxlWQNIWbRRyCBnNPu96bFca00Ff
FrpQXZQ0Erz8c1pYhkvjK4efsqt5217x6XM0NLVWShhwdnsQIV/k1P9E7WBm5CQT
s1V+jpJS7+Xp7vOUaOtWJTix
-----END CERTIFICATE-----
"""


@pytest.fixture(scope="session")
def cloud_ca_public_key():
    return b"""-----BEGIN CERTIFICATE-----
MIIDxzCCAq+gAwIBAgIUCaKXFfzSpMsceMKhVkIkNJgAmlwwDQYJKoZIhvcNAQEL
BQAwcjELMAkGA1UEBhMCQ0gxCzAJBgNVBAgMAlpIMQ8wDQYDVQQHDAZadXJpY2gx
FTATBgNVBAoMDEdBUkRFTkEgR21iSDEbMBkGA1UECwwSZGlnaXRhbCBodWIgWnVy
aWNoMREwDwYDVQQDDAhjbG91ZC1jYTAgFw0yMzEwMTAxNjM3NTVaGA8yMTIzMDkx
NjE2Mzc1NVowcjELMAkGA1UEBhMCQ0gxCzAJBgNVBAgMAlpIMQ8wDQYDVQQHDAZa
dXJpY2gxFTATBgNVBAoMDEdBUkRFTkEgR21iSDEbMBkGA1UECwwSZGlnaXRhbCBo
dWIgWnVyaWNoMREwDwYDVQQDDAhjbG91ZC1jYTCCASIwDQYJKoZIhvcNAQEBBQAD
ggEPADCCAQoCggEBAMmlUFxiAPLxfrVo17VdIhzPqZ9dI9pubaQ3EAaZ+uB0UYbx
RJlB1Ir9rvzPcb6RxZzz3vzamjOzMBXeZEM/B2F9IZabJEOHBAHK43T0paa+LxCi
uSRDh5KgmThS3vqGaW5uBgNB1xn4qiCqy1zWVPcDGjAWWTSv2i2ZrHJVC6ud7ZxN
/6fn0CHKP0AK26L65zZqpyDrIlFYgHaQhUZVZeEagkq8p014TqZxmoBE1bps7THv
nsGi4za3QnLG4QkIRY1N9nE/tVD4FURSQtiZ7p/GUsSg77fbTlIJl5oyFbNndgKT
hKcdicSYq99BSGz6pqnvZRHY4V7g7vIWbmjZlSsCAwEAAaNTMFEwHQYDVR0OBBYE
FGsCsQDs/rGtxCjg1lj4e+GlFYFdMB8GA1UdIwQYMBaAFGsCsQDs/rGtxCjg1lj4
e+GlFYFdMA8GA1UdEwEB/wQFMAMBAf8wDQYJKoZIhvcNAQELBQADggEBABGHlLJj
c1Lp9/Wuwcvi+j8fNjxpI/18zIqMgu+elgogUYv2XRrYlY9elh2W03geapnwuvTY
5Zi/ekzTpjwGx+pLwcBJY/w0pmcLjoeWyj3lRveJ822pdjtDZizWEVJV3cp90bSu
sR2HByFuQHG2kktAnPzT6bnHGkWfxRGXMpbMTcHM2JvrJwUNyIkbPwAZ5sMBsX8y
ekNV/6fGe32ZPGpjee9f2OpGfeB3yWY1QJtjcaCOwhRh88cMA8RrsIExMZZyMQtM
fIODIK1+gU0JUT+2J939Igj63Xrgl70kOaftDcKiOPW8vg17d5oEvud7WXkIG7MA
OlZH6tAYC55oWNw=
-----END CERTIFICATE-----
"""


@pytest.fixture(scope="session")
def cloud_ca_private_key():
    return b"""-----BEGIN PRIVATE KEY-----
MIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQDJpVBcYgDy8X61
aNe1XSIcz6mfXSPabm2kNxAGmfrgdFGG8USZQdSK/a78z3G+kcWc89782pozszAV
3mRDPwdhfSGWmyRDhwQByuN09KWmvi8QorkkQ4eSoJk4Ut76hmlubgYDQdcZ+Kog
qstc1lT3AxowFlk0r9otmaxyVQurne2cTf+n59Ahyj9ACtui+uc2aqcg6yJRWIB2
kIVGVWXhGoJKvKdNeE6mcZqARNW6bO0x757BouM2t0JyxuEJCEWNTfZxP7VQ+BVE
UkLYme6fxlLEoO+3205SCZeaMhWzZ3YCk4SnHYnEmKvfQUhs+qap72UR2OFe4O7y
Fm5o2ZUrAgMBAAECggEAKRQjbd6NQPDPlldYclsZwvLPJGcOEcajUWviOOYPhMBN
h4cJKYuOqA4MIvaDvoXl0xafW7WQ6m1bo2jd1hE2CLc8K3lJhvQvbcoOUlowkOp3
nhT4UJntOYK8FAxV3oWZXuTNFsbH8kOFLQh+S1hikLuyDw/OdnxInzeKOPR4Xyp9
dzlBP3/m/+dN72CiSuXKpIfOT+U8AhqSC0oatY+vp0DKo/GNedlaeG/yAMXHvUsM
agT01+WmzwO/HkUW3hy74Gk9mG7I8BuIEPVor53X+CLrvn0ex6B5oOHTmpPp4kkx
26OjZYeyg2VpmPjuFwZTU1lQeg1abe3nXs67+xHoIQKBgQDvGZZTWJ51WX9FArV9
103tlS1fVgGUlYsS6gYzQjr0GqY1aHrp+Q5TzXFKi8WgVBr86SGsUTxMyJFh8vXc
x5e/71HlzQ+agJIdR0Pz5sxpUFDSnXwi5Y1sS6FaxnIBMWvrBkJSuf6P/JyUQtDT
AfIpYZJyJPRuC7vtGaXTdY1DGwKBgQDX5gJFuvfaX7V1BUZ0cyUc3dd3Y8L+0aGX
i0WeKi0shIrtqvkFfsYgeOPjGzbuAuJ7eLIM9diunabmdlcaF3RvC7zdjB3TAdwZ
nICxD3mVEoFLlmW4WQ7ybn9Qgv8FfX6FlOFAyIi5BtwSHqm7YxZAAcTl0nQxdGMM
6iyiqY4HMQKBgQCEJVMk+1yQpQcnIAko5N8oCQPLpiA3e7Min/8PQ3KLyVLFP9p3
B/R4MpqDxd5S70j/MOYwc7FtCoj3Zq2l+RYQuXc9F+mgzaBz2Bhha9Tb+8y/qtSa
AN751I74Oad2q1bmzU3IpQ1hjQ8JDiiWBoRNhKTIu03wqEGUGFHDHjwVswKBgQCC
tujDTSsJFQ9pFVON57UdoBb3WvhRjZx3g0QYOdL19B2lPfHdaN8OBAN9mhmMy0RS
m0W54RNazWqieB3OV0sQfJvRyya3fZXED+Q+z26+WeDcYeeeUJVjJJGCrn021r9G
o1gp////fm65rcT4BksPX8LVnrDozF24EQQLS/sI0QKBgF/PGXiM/6a3YxcBkahl
jpvw2LNUv7bwiypBDfC7PwjJiYfZso5z71HrF2vUWqq0FNN2Ag+w0UrKwD2cN662
4xpFLkHIvraCWLOsVpI3eTKpBas3g/mDnWpF3hfqvJ01lGZjGAWD943ydc5RiQur
Y0jGWx9CYmg3mAxRqNUZ3EL/
-----END PRIVATE KEY-----
"""


@pytest.fixture(scope="session")
def cloud_client_private_key():
    return b"""-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQCyFs0A3vz3lRo0
rUL6YvqUEO1WtRSr/G3JPJi65YbsOxAuIX6nvvz8+fj9PkDJu9KOWqY9iQAN1F/t
edTeczs18MzCBdRYzdt/6Fcq4xQMR46dZibmvrnFRXWQ0tBZ1DC9+7yNlTNDgBzE
88kMbvnYaHwfHati2OfKMeJ0nTmYNcKp0UW3KI2P7KMRxac+Ga4CjY+78Qwes8uj
x2dBMdjGvBXp3biRxD+ENLc8ANMdlRFDipAdxcFv0dKgDx7mXQvogk1gsCguUd7K
lBwfN7By8tc61aaczhff650uQSELP595izD5i6PuG8fkI0nZZB0kfBYGnByq/mr8
31wcqeQrAgMBAAECggEAUm3XSXXs5LOww30GqVoy3WHQWPfLr6dRMXnIv4kJoEHe
RVvfgckW1AjnxF+SIU28MYOnuoe07LHGDOb9LlFrsJXaUFveY5Q06skhv4oHd3+P
dS8ZBmh1F+gEeJn7MfjS7rycE3Rhm/aqWkb0YbrkDdSeztAuybvX3XClfpBfXiGO
JF4eSIQZZOiIcAPS7XvQfNWRHYea8Sp5UNtPaKwpVoEVQXRv3rphWVMn9vW7WiTM
ox4BKUf64pNDAz7AlqAhagnDUcUcAg3XHvg6ksUbUHVp18b7247LeIv9HCA/y3L9
HlfXHhOI4Xhn6NaaznI/b2lc7SNDuvLDqp+eRpJ5sQKBgQDK8ryqjrTCOyRoIPPT
wn7Xn+UqrlSqnhVux4rnS/udjiCseCV5Cy8LY7MIo5s9iCzhxRPnF3fx2VzFQJon
5XuduzPDBbTWa9nrmq6z1rwzcss4/opwHGTC1a/56u++HTLCvXTz9B6zZQbVMXJ2
ZE8AFAfr5QbCJUcPZy7gWL1KHQKBgQDgpH6qqgtMdkUsGYMYfS9niYMge4CYLtzk
+edlGpoV/3O7YtGBI/VLL5M1SWglsgg01BEuz8ak+yeVDo8ch7gGxr3YJ0udC8Hi
xixRn5inb/y6BlejhFJiogcyyDFePXmbdA6hbv8in4ULiHSsUtObrLXjOCYQjs9J
YLI24azU5wKBgEymQPtpyntROv7Y8z4XRzDJAxSLow6NhirA0oVo/S8UbuK0vfJp
dusmTIgGwqsKs2jRtiKhinudTJxzOcW3tmhsO7B8h0A0m6mQUks53vrPcFGmUULm
dmffrQcG5GU5QeKrC3DX0oCOt3Xtpv1wBSZSamt9pH/O9Hes0NeKrHNBAoGAeq57
Gps5Bm4Ewtu/84zSabn4qbGo/fOB4W71RwrrIZ5bxvdlsSBBIul9fHl1bji3MJqs
M6N3ObyL1mSYFZ2tC85X+YckTUURgtZ1d7IwPSj0nWc/T2bBU2pngf1AsNXj5tjP
8KvcnDz//Ndt2Hp3ZCpDPy734s0LOWici0peB/sCgYEAgBzLwbfQAPZUO7IWxH4B
cWYKTqN3F3pkjli2PgTcGpHL25i9KC/lTwfyKef809KCV7nO5whRboFCpPSB6q4g
aUbJ02bRwLXkAblLEIyjgSPzIkktkq+NcVBOlAywTCm9xbplnMOqorRInuhlIdsM
DeNtvAyrIIL7IaS9AgPWDYE=
-----END PRIVATE KEY-----
"""


@pytest.fixture(scope="session")
def cloud_client_public_key():
    return b"""-----BEGIN CERTIFICATE-----
MIIDWDCCAkACAQIwDQYJKoZIhvcNAQELBQAwcjELMAkGA1UEBhMCQ0gxCzAJBgNV
BAgMAlpIMQ8wDQYDVQQHDAZadXJpY2gxFTATBgNVBAoMDEdBUkRFTkEgR21iSDEb
MBkGA1UECwwSZGlnaXRhbCBodWIgWnVyaWNoMREwDwYDVQQDDAhjbG91ZC1jYTAg
Fw0yMzEwMTAxNjM5MDNaGA8yMTIzMDkxNjE2MzkwM1owcDELMAkGA1UEBhMCQ0gx
CzAJBgNVBAgMAlpIMQ8wDQYDVQQHDAZadXJpY2gxFTATBgNVBAoMDEdBUkRFTkEg
R21iSDEbMBkGA1UECwwSZGlnaXRhbCBodWIgWnVyaWNoMQ8wDQYDVQQDDAZjbGll
bnQwggEiMA0GCSqGSIb3DQEBAQUAA4IBDwAwggEKAoIBAQCyFs0A3vz3lRo0rUL6
YvqUEO1WtRSr/G3JPJi65YbsOxAuIX6nvvz8+fj9PkDJu9KOWqY9iQAN1F/tedTe
czs18MzCBdRYzdt/6Fcq4xQMR46dZibmvrnFRXWQ0tBZ1DC9+7yNlTNDgBzE88kM
bvnYaHwfHati2OfKMeJ0nTmYNcKp0UW3KI2P7KMRxac+Ga4CjY+78Qwes8ujx2dB
MdjGvBXp3biRxD+ENLc8ANMdlRFDipAdxcFv0dKgDx7mXQvogk1gsCguUd7KlBwf
N7By8tc61aaczhff650uQSELP595izD5i6PuG8fkI0nZZB0kfBYGnByq/mr831wc
qeQrAgMBAAEwDQYJKoZIhvcNAQELBQADggEBAI+WaUNsWCtTvNXG/2P4WbOioskP
Zd6CMd9iFFAAL3pzA/O3JmXH0JnZzRhb7OuIEc2bGSu5CyXfW6VtSgmM/w1wp9v6
oN5q3X2dyZboXeMSPOk8nKPxp3SkSB9fFRCdcsoaZZ9X1KXtpdngugLSDf7yF3Ow
q+wUzAVN9YJLYYzpRcVOEGRPgSqIYnu7QiCc5Cs/keJvJxmcs2lkmKqqCVu2a4o/
Ta9ie7jcE99a32MZHWs1730X7bzeapbXLPZIakE7vBPGmIR3xdxIvj8P0OS6jSJb
A9ac9p+gg/f/Ek1IRJaYUAxJasQJwcV4XtiSVG1qLzRpVh6sDrB9X/by5gE=
-----END CERTIFICATE-----
"""
