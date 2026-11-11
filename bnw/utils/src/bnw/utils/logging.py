# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import contextlib
import functools
import logging
import os
from collections import defaultdict
from enum import Enum
from logging import Logger
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    Mapping,
    MutableMapping,
    NamedTuple,
    Optional,
    Set,
    Tuple,
)


class StructuredDataElement(NamedTuple):
    id: str
    context: Callable

    def extra(self, **values):
        return StructuredDataLogger.sd_extra(self.id, **values)


class StructuredDataLogger(logging.LoggerAdapter):
    PEN = "55029"

    def __init__(
        self,
        logger: Logger,
        ids: Optional[Set[str]] = None,
        context_extra: Optional[Mapping[str, Dict[str, str]]] = None,
        params: Optional[Mapping[str, Set[str]]] = None,
    ) -> None:
        self._extra: MutableMapping[str, Mapping[str, str]] = {}
        super().__init__(logger, self._extra)
        self._ids: Set[str] = set()
        self._context_extra: MutableMapping[str, Dict[str, str]] = defaultdict(dict)
        self._params: MutableMapping[str, Set[str]] = {}

        if ids:
            for i in ids:
                self._ids.add(i)

        if context_extra:
            for extra_key, extra_data in context_extra.items():
                self._context_extra[extra_key] = extra_data.copy()

        if params:
            for param_key, param_value in params.items():
                self._params[param_key] = param_value.copy()

    def sd_define(
        self, id: str, params: Iterable[str], static_values: Mapping[str, str] = None
    ) -> StructuredDataElement:
        self._ids.add(id)
        self._params[id] = set(params)
        if static_values:
            self._extra[id] = static_values
        return StructuredDataElement(id=id, context=functools.partial(self.sd_context, id))

    @contextlib.contextmanager
    def sd_context(self, id: str, **values):
        if id not in self._params:
            yield
            return

        params = self._params[id]
        added: Set[Tuple[str, Any]] = set()
        for k, v in values.items():
            if k not in params:
                continue
            key = k
            added.add((key, self._context_extra[id].get(key, None)))
            self._context_extra[id][key] = v
        try:
            yield
        finally:
            for key, previous in added:
                if previous is None:
                    if key in self._context_extra[id]:
                        del self._context_extra[id][key]
                else:
                    self._context_extra[id][key] = previous

    @staticmethod
    def sd_extra(id: str, **values):
        return {id: {k: v for k, v in values.items() if v is not None}}

    def get_values(self, kwargs):
        values = defaultdict(dict)
        if self.extra:
            for sd_element_id, sd_values in self.extra.items():
                values[sd_element_id].update(sd_values)

        if self._context_extra:
            for sd_element_id, sd_values in self._context_extra.items():
                values[sd_element_id].update(sd_values)

        consumed_extra = set()
        if "extra" in kwargs:
            kwargs_extra = kwargs["extra"]
            for sd_element_id, sd_values in kwargs["extra"].items():
                if sd_element_id not in self._ids:
                    continue

                if not isinstance(sd_values, dict) or sd_element_id not in self._params:
                    continue

                consumed_extra.add(sd_element_id)
                valid_params = self._params[sd_element_id]

                for param_name, value in sd_values.items():
                    if param_name not in valid_params:
                        continue

                    values[sd_element_id][param_name] = value

            if consumed_extra:
                new_kwarg_extras = {k: v for k, v in kwargs_extra.items() if k not in consumed_extra}
                kwargs["extra"] = new_kwarg_extras

        return values, kwargs

    def process(self, msg, kwargs):
        sd_values, new_kwargs = self.get_values(kwargs)
        if sd_values:
            if "extra" not in new_kwargs:
                new_kwargs["extra"] = dict()
            if "structured_data" not in new_kwargs["extra"]:
                new_kwargs["extra"]["structured_data"] = dict()

            new_kwargs["extra"]["structured_data"] = dict(sd_values)

            structured_data_string = ""
            for sd_element_id, sd_element_values in sd_values.items():
                if sd_element_values:
                    values_str = " ".join(f'{k}="{v}"' for k, v in sd_element_values.items())
                    if self._is_standardized_element_id(sd_element_id):
                        structured_data_string += f"[{sd_element_id} {values_str}]"
                    else:
                        structured_data_string += f"[{sd_element_id}@{self.PEN} {values_str}]"

            if structured_data_string:
                return structured_data_string + " " + msg, new_kwargs
            else:
                return msg, new_kwargs
        else:
            return msg, kwargs

    def getChild(self, suffix: str):
        if self.logger.root is not self.logger:
            suffix = ".".join((self.name, suffix))

        logger = logging.getLogger(suffix)
        return StructuredDataLogger(logger, ids=self._ids, context_extra=self._context_extra, params=self._params)

    @staticmethod
    def _is_standardized_element_id(sd_element_id):
        return sd_element_id == "origin" or sd_element_id == "timeQuality"


class BnwActivity(str, Enum):
    INCLUSION = "inclusion"
    EXCLUSION = "exclusion"
    FOTA = "fota"
    STATE = "state"
    VALUE_REPORT = "value-report"
    REGISTRATION = "registration"
    CONTROL = "control"
    DEVICE_CONNECTIVITY = "connection-status"
    TIME_SYNC = "time-sync"

    def __str__(self) -> str:
        return self.value


class Logging:
    @staticmethod
    def defaultConfig(
        level=logging.WARN,
        journal_format="%(syslog_level)s%(message)s",
        standalone_format="%(asctime)-15s %(name)-24s %(levelname)-8s %(message)s",
        **kwargs,
    ):
        if os.getenv("JOURNAL_STREAM"):
            logging.basicConfig(level=level, format=journal_format, **kwargs)
            logging_to_syslog_mapping = {
                logging.CRITICAL: 2,
                logging.ERROR: 3,
                logging.WARNING: 4,
                logging.INFO: 6,
                logging.DEBUG: 7,
            }
            old_factory = logging.getLogRecordFactory()

            def record_factory(*args, **kwargs):
                record: logging.LogRecord = old_factory(*args, **kwargs)
                syslog_level = logging_to_syslog_mapping.get(record.levelno, None)
                if syslog_level is not None:
                    record.syslog_level = f"<{syslog_level}>"
                else:
                    record.syslog_level = ""
                return record

            logging.setLogRecordFactory(record_factory)
        else:
            logging.basicConfig(level=level, format=standalone_format, **kwargs)

    @staticmethod
    def getLogger(name: Optional[str] = None) -> StructuredDataLogger:
        logger = logging.getLogger(name)
        return StructuredDataLogger(logger)

    @staticmethod
    def sd_define_bnw(logger: StructuredDataLogger) -> StructuredDataElement:
        return logger.sd_define("bnw", ["device", "activity", "remote"])

    @staticmethod
    def sd_bnw_extra(activity: BnwActivity = None, device: str = None, remote: str = None):
        return StructuredDataLogger.sd_extra("bnw", activity=activity, device=device, remote=remote)

    @staticmethod
    def sd_define_origin(logger: StructuredDataLogger) -> StructuredDataElement:
        return logger.sd_define("origin", ["ip", "enterpriseId", "software", "swVersion"])

    @staticmethod
    def sd_origin_extra(
        ip: str = None,
        enterpriseId: Optional[str] = StructuredDataLogger.PEN,
        software: str = None,
        swVersion: str = None,
    ):
        return StructuredDataLogger.sd_extra(
            "origin", enterpriseId=enterpriseId, ip=ip, software=software, swVersion=swVersion
        )

    @staticmethod
    def sd_define_metric(logger: StructuredDataLogger) -> StructuredDataElement:
        return logger.sd_define("metric", ["name", "value"])

    @staticmethod
    def sd_bnw_metric(name: str = None, value: str = None) -> dict:
        return StructuredDataLogger.sd_extra("metric", name=name, value=value)
