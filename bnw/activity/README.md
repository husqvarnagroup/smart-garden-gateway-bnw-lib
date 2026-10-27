<!--
SPDX-FileCopyrightText: GARDENA GmbH

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Activity

## Model

Models of different entities in our system, modeled based on the common dominator; so that
their interface is minimal and can be consistent across all layers. 
E.g. a device is nothing more than just a SGTIN string. 

## Transport

bnw-lib transport package extended with some additional BNW protocol concepts / conventions. 
E.g. request & response pattern. 

# Details
## Implementation
The implementation is using the strategy pattern to offer an identical interface regardless
of the communication channel that is used to carry out the activity.

### Context
Some processes require additional context information in order for them to work.
One such example is the gateway ID that is required when performing an activity via the cloud.
Another such example is the includable device id when including a device. 

There are 3 different ways how a process gets to the necessary context
- context can be provided by caller when invoking the activity: `process.include(device_name, includable_device_id=1)`
- context is provided by the strategy provider (e.g. `UnixInclusionStrategy`, `SgBackendApiInclusionStrategy`). 
- context is dynamically fetched via context resolvers (e.g. `IncludableDeviceResolver`)

## Multiple Inheritance

Code makes use of python multiple inheritance, however the code tries to not actually
run into the situation where implementations are inherited from different sources. The lack of interfaces
in python also contributes to having multiple base cases. 

There are 3 different main hierarchies, that often merge together at the concrete activity strategies:
1. Activities (e.g. `InclusionActivities`)
2. Business Process (e.g `InclusionProcess`)
3. Activity Strategy (basic ones like `BaseActivityStrategy`, `UnixActivityStrategy` or concrete ones like `UnixInclusionStrategy`)
