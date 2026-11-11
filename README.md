# BNW Lib

## Why?
bnw-lib was started with the intention to become the primary toolbox when interacting with BNW devices.
It should be the foundation of most tooling around BNW devices.
It attempts to reduce the multitude of different (re-)implementation of similar things in different contexts
(such as test automation, monitoring, development tools, etc.).

## What does it contain?
- Documentation / Reference implementation of BNW message protocol
- Interface to interact with devices, agnostic of the underlying technology used
- Implementation of common use cases / features / activities (e.g. inclusion, read device data)
- Wide range of tools for test automation (test harness, fixtures)
- Shared utilities to be re-used in BNW gateway components

## Who is using it?
- **bnw-cli**:
  - cli itself is only an user interface around bnw-lib activity package, heavy lifting is done by bnw-lib
  - test framework harness & fixtures for tests
- **gateway bnw-integration-test**: tfw component and harness to implement gateway integration tests (device to cloud)
- **lwm2mserver**, **cloudadapter**:
  - reference implementation of protocol, logging & systemd utils
  - test framework harness & fixtures for component tests
- some zephyr JIG tests
- sg-bnw-firmware-testing

### You ?! ###
Before writing your own code, consider using bnw-lib. If you feel it is lacking functionality,
extend it or contribute your code back to it for the benefit of all of us (and you).
While no single solution fits all problems, there shouldn't be many good reasons to not use bnw lib.
If you find a reason not to use it, let us know.

## Covered BNW Layers / Areas
- Devices; BNW/LWM2M and legacy lemonbeat via lemonbeat-server
- Gateway
- IoT Backend / Cloud (AWS IoT)

### Areas that would still like some of your love
Contributes are welcome!
- Activity:
  - Additional higher level activities (e.g. generic scheduling or valve handling)

## Available Python Packages
- **transport**: speak coap, http, mqtt & Unix domain socket, all with a similar interface
- **activity**: include/exclude, read/write device data via gateway or cloud
- **tfw**: see [TFW Readme](bnw/tfw/README.md)
  - **components**:
    - **commander**: control our own components such as zephyr firmware, gateway services or backend services.
    - **harness**: various mocks / implementations / tools for different parts of the BNW system, such as lwm2m device, generic gateway service, manufacturing certificate authority, AWS IoT cloud mock, packet / message capture
  - **fixtures**:
    - **cases**: use different variations to run components or  use connections
    - **setup**: some common test setups
  - **gateway**: components & fixtures for gateway layer
  - **device**: components & fixtures for device layer

## Future Work
- **state** package: interface to query device state on the different layers
  - use case: tell me if a device is included from the perspective of the device itself, lwm2mserver, cloudadpater and AWS IoT.

# Getting Started with Development
Prerequisite: [Get Poetry](https://python-poetry.org/docs/#installation)
```
git clone git@ssh.dev.azure.com:v3/HQV-Gardena/SG-Gateway/sg-bnw-lib
cd sg-bnw-lib
poetry install --no-root
poetry run pre-commit install

# add poetry plugins
poetry self add "poetry-dynamic-versioning[plugin]" poetry-monorepo-dependency-plugin
# or with pipx
pipx inject poetry "poetry-dynamic-versioning[plugin]" poetry-monorepo-dependency-plugin
```

## Use of a compatible Python version
Make sure you are using a compatible Python version. Poetry allows you to easily switch between different Python
versions. Either use the system package manager, the [deadsnakes PPA](https://launchpad.net/~deadsnakes/+archive/ubuntu/ppa),
build your own Python version or any other way to get a Python installation on your system.
```
# e.g.
export BNW_LIB_PYTHON_EXECUTABLE="~/.local/opt/cpython_3.12.8/bin/python3.12"
poetry env use "$BNW_LIB_PYTHON_EXECUTABLE"
```

**Create new virtual environments**
```
find . -name pyproject.toml ! -path "*/.venv*/*" -print -execdir poetry env use "$BNW_LIB_PYTHON_EXECUTABLE" \;
```

## Create a Release on GitHub

To create a release of the Python wheels, create a git tag in the form of
`v<major>.<minor>.<patch>` that points to a commit on the `main` branch.
Push the tag to GitHub. The `release` job in `.github/workflows/build.yaml` creates the release.
The job fails if the tag does not point to a commit on `main`.

If a release for the tag already exists, the job fails. To run it again, delete the release
and the tag on GitHub, then push the tag again.
