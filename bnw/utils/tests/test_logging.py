# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import logging
import random
import string
from datetime import datetime, timezone

from freezegun import freeze_time

from bnw.utils.logging import BnwActivity, Logging


def test_default_config_journal(monkeypatch, caplog):
    # GIVEN: JOURNAL_STREAM is set
    monkeypatch.setenv("JOURNAL_STREAM", "some value")
    Logging.defaultConfig(logging.DEBUG, force=True)  # force required because logging already setup by pytest
    logging.root.addHandler(caplog.handler)  # re-add caplog handler
    logger_name = "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
    logger = Logging.getLogger(logger_name)
    for h in logging.root.handlers:
        logger.logger.addHandler(h)

    with caplog.at_level(logging.INFO, logger=logger_name):
        # WHEN: journal config is applied

        with freeze_time("2021-10-12 16:43:26,601"):
            caplog.clear()
            logger.info("msg")

        # THEN: message according to journal config (contains severity)
        assert logger.getEffectiveLevel() == logging.INFO
        assert caplog.records[-1].msg == "msg"
        assert logger.logger.handlers[0].format(caplog.records[-1]) == "<6>msg"


def test_default_config_standalone(monkeypatch, caplog):

    # GIVEN: in standalone mode
    monkeypatch.delenv("JOURNAL_STREAM", raising=False)
    Logging.defaultConfig(logging.DEBUG, force=True)  # force to apply our setting
    logging.root.addHandler(caplog.handler)  # re-add caplog handler
    logger_name = "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
    logger = Logging.getLogger(logger_name)
    for h in logging.root.handlers:
        logger.logger.addHandler(h)

    with caplog.at_level(logging.INFO, logger=logger_name):
        # WHEN: default config is applied
        with freeze_time("2021-10-12 16:43:26,601"):
            caplog.clear()
            logger.info("msg")

        # THEN: message according to basic config
        assert caplog.records[-1].msg == "msg"
        # Check logger logged at 2021-10-12 16:43:26,601
        check_time_utc = datetime(2021, 10, 12, 16, 43, 26, 601000, tzinfo=timezone.utc)
        check_time_local = check_time_utc.astimezone(None)
        check_time_local_string = "%s,%03d" % (
            check_time_local.strftime("%Y-%m-%d %H:%M:%S"),
            check_time_local.microsecond / 1000,
        )
        assert (
            logger.logger.handlers[0].format(caplog.records[-1])
            == f"{check_time_local_string} {logger_name}               INFO     msg"
        )


def test_root_logger(caplog):
    with caplog.at_level(logging.INFO):
        # GIVEN: root logger
        logger = Logging.getLogger()

        # WHEN: logging
        logger.info("Hello World")

        # THEN: works as regular logger
        assert caplog.records[0].msg == "Hello World"


def test_named_logger(caplog):
    with caplog.at_level(logging.INFO):
        # GIVEN: named logger
        logger = Logging.getLogger("some.logger")

        # WHEN: logging
        logger.info("Hello World")

        # THEN: works ar regular named logger
        assert caplog.records[0].msg == "Hello World"
        assert caplog.records[0].name == "some.logger"


def test_logger_get_child(caplog):
    with caplog.at_level(logging.INFO):
        # GIVEN: root child logger
        logger = Logging.getLogger().getChild("child")

        # WHEN: logging
        logger.info("Hello World")

        # THEN: has proper name
        assert caplog.records[0].msg == "Hello World"
        assert caplog.records[0].name == "child"


def test_logger_get_grand_child(caplog):
    with caplog.at_level(logging.INFO):
        # GIVEN: grand child logger
        logger = Logging.getLogger("child").getChild("grandchild")

        # WHEN: logging
        logger.info("Hello World")

        # THEN: has proper name
        assert caplog.records[0].msg == "Hello World"
        assert caplog.records[0].name == "child.grandchild"


def test_structured_data_log(caplog):
    with caplog.at_level(logging.INFO):
        # GIVEN: structured logger
        logger = Logging.getLogger()
        logger.sd_define("id", ["v1", "v2"])

        # WHEN: logging with structured data
        logger.info("msg", extra=logger.sd_extra("id", v1="val", v2="val2"))

        # THEN: structured data part of log record
        assert caplog.records[0].msg == '[id@55029 v1="val" v2="val2"] msg'
        assert caplog.records[0].structured_data == {"id": {"v1": "val", "v2": "val2"}}


def test_structured_data_log_extra(caplog):
    with caplog.at_level(logging.INFO):
        # GIVEN: structured logger
        logger = Logging.getLogger()
        logger.sd_define("id", ["v1", "v2"])

        # WHEN: adding structured data via extra
        logger.info("msg", extra=logger.sd_extra("id", v1="val", v2="val2"))

        # THEN: structured data part of log message
        assert caplog.records[0].msg == '[id@55029 v1="val" v2="val2"] msg'


def test_structured_data_log_context(caplog):
    with caplog.at_level(logging.INFO):
        # GIVEN: structured logger
        logger = Logging.getLogger()
        logger.sd_define("id", ["v1", "v2"])

        # WHEN: adding structured data via sd_context
        with logger.sd_context("id", v1="val", v2="val2"):
            logger.info("msg")

        # THEN: structured data part of log message
        assert caplog.records[0].msg == '[id@55029 v1="val" v2="val2"] msg'


def test_structured_data_log_element_extra(caplog):
    with caplog.at_level(logging.INFO):
        # GIVEN: structured logger
        logger = Logging.getLogger()
        element = logger.sd_define("id", ["v1", "v2"])

        # WHEN: adding structured data via structured element extra
        logger.info("msg", extra=element.extra(v1="val", v2="val2"))

        # THEN: structured data part of log message
        assert caplog.records[0].msg == '[id@55029 v1="val" v2="val2"] msg'


def test_structured_data_log_element_context(caplog):
    with caplog.at_level(logging.INFO):
        # GIVEN: structured logger
        logger = Logging.getLogger()
        element = logger.sd_define("id", ["v1", "v2"])

        # WHEN: adding structured data via structured element context
        with element.context(v1="val", v2="val2"):
            logger.info("msg")

        # THEN: structured data part of log message
        assert caplog.records[0].msg == '[id@55029 v1="val" v2="val2"] msg'


def test_structured_data_nested_context(caplog):
    with caplog.at_level(logging.INFO):
        # GIVEN: structured logger
        logger = Logging.getLogger()
        logger.sd_define("id", ["v1", "v2"])

        # WHEN: nesting multiple context
        with logger.sd_context("id", v1="val"):
            logger.info("msg1")
            with logger.sd_context("id", v2="val2"):
                logger.info("msg2")
            logger.info("msg3")
        logger.info("msg4")

        # THEN: context is merged
        assert caplog.records[0].msg == '[id@55029 v1="val"] msg1'
        assert caplog.records[1].msg == '[id@55029 v1="val" v2="val2"] msg2'
        # AND value from old context removed
        assert caplog.records[2].msg == '[id@55029 v1="val"] msg3'
        assert caplog.records[3].msg == "msg4"


def test_structured_data_nested_overwrite(caplog):
    with caplog.at_level(logging.INFO):
        # GIVEN: structured logger
        logger = Logging.getLogger()
        logger.sd_define("id", ["v1", "v2"])

        # WHEN: context overwrite values
        with logger.sd_context("id", v1="val1"):
            logger.info("msg1")
            with logger.sd_context("id", v1="val2"):
                logger.info("msg2")
            logger.info("msg3")
        logger.info("msg4")

        assert caplog.records[0].msg == '[id@55029 v1="val1"] msg1'
        # THEN: value is overwritten
        assert caplog.records[1].msg == '[id@55029 v1="val2"] msg2'
        # AND previous value restored after exiting context
        assert caplog.records[2].msg == '[id@55029 v1="val1"] msg3'


def test_structured_data_only_processes_defined_values_context(caplog):
    with caplog.at_level(logging.INFO):
        # GIVEN: structured logger
        logger = Logging.getLogger()
        logger.sd_define("id", ["value"])

        # WHEN: context has not allowed value
        with logger.sd_context("id", value="val", value2="not allowed"):
            logger.info("msg")

        # THEN: only defined value is part of message
        assert caplog.records[0].msg == '[id@55029 value="val"] msg'
        assert caplog.records[0].structured_data == {"id": {"value": "val"}}


def test_structured_data_only_processes_defined_values_extra(caplog):
    with caplog.at_level(logging.INFO):
        # GIVEN: structured logger
        logger = Logging.getLogger()
        logger.sd_define("id", ["value"])

        # WHEN: extra has not allowed value
        logger.info("msg", extra={"id": {"value": "val", "value2": "not allowed"}})

        # THEN: only defined value is part of message
        assert caplog.records[0].msg == '[id@55029 value="val"] msg'
        assert caplog.records[0].structured_data == {"id": {"value": "val"}}


def test_structured_data_only_processes_defined_ids_context(caplog):
    with caplog.at_level(logging.INFO):
        # GIVEN: structured logger
        logger = Logging.getLogger()
        logger.sd_define("id", ["value"])

        # WHEN: context used unknown id & values
        with logger.sd_context("id2", value="val"):
            logger.info("msg")

        # THEN: structured data not part of message
        assert caplog.records[0].msg == "msg"


def test_structured_data_only_processes_defined_data_via_extra(caplog):
    with caplog.at_level(logging.INFO):
        # GIVEN: structured logger
        logger = Logging.getLogger()
        logger.sd_define("id", ["value"])

        # WHEN: context overwrite values
        logger.info("msg", extra=logger.sd_extra("id2", value="1"))

        # THEN: only defined value is part of message
        assert caplog.records[0].msg == "msg"
        # AND extra is handled as regular (non-structured) extra
        assert caplog.records[0].id2 == {"value": "1"}


def test_structured_data_handles_invalid_extra_valid_id(caplog):
    with caplog.at_level(logging.INFO):
        # GIVEN: structured logger
        logger = Logging.getLogger()
        logger.sd_define("id", ["value"])

        # WHEN: extra is malformed
        logger.info("msg", extra={"id": "asdf"})

        # THEN: only defined value is part of message
        assert caplog.records[0].msg == "msg"
        # AND extra is handled as regular (non-structured) extra
        assert caplog.records[0].id == "asdf"


def test_structured_data_handles_invalid_extra_invalid_id(caplog):
    with caplog.at_level(logging.INFO):
        # GIVEN: structured logger
        logger = Logging.getLogger()
        logger.sd_define("id", ["value"])

        # WHEN: extra is malformed
        logger.info("msg", extra={"id2": "asdf"})

        # THEN: only defined value is part of message
        assert caplog.records[0].msg == "msg"
        # AND extra is handled as regular (non-structured) extra
        assert caplog.records[0].id2 == "asdf"


def test_structured_data_static(caplog):
    with caplog.at_level(logging.INFO):
        # GIVEN: structured logger with static sd value
        logger = Logging.getLogger()
        logger.sd_define("id", ["static", "dynamic"], static_values={"static": "s"})

        # WHEN: logging without sd values
        logger.info("msg")

        # THEN: static value part of message
        assert caplog.records[0].msg == '[id@55029 static="s"] msg'


def test_structured_data_static_and_dynamic(caplog):
    with caplog.at_level(logging.INFO):
        # GIVEN: structured logger with static sd value
        logger = Logging.getLogger()
        logger.sd_define("id", ["static", "dynamic"], static_values={"static": "s"})

        # WHEN: context overwrite values
        with logger.sd_context(id="id", dynamic="d"):
            logger.info("msg")

        # THEN: static value and dynamic part of message
        assert caplog.records[0].msg == '[id@55029 static="s" dynamic="d"] msg'


def test_structured_data_static_can_be_overwritten_by_dynamic(caplog):
    with caplog.at_level(logging.INFO):
        # GIVEN: structured logger with static sd value
        logger = Logging.getLogger()
        logger.sd_define("id", ["static", "dynamic"], static_values={"static": "s"})

        # WHEN: context overwrite values
        with logger.sd_context(id="id", static="s2", dynamic="d"):
            logger.info("msg")

        # THEN: static value and dynamic part of message
        assert caplog.records[0].msg == '[id@55029 static="s2" dynamic="d"] msg'


def test_structured_data_standardized_element(caplog):
    with caplog.at_level(logging.INFO):
        # GIVEN: structured logger
        logger = Logging.getLogger()
        Logging.sd_define_origin(logger)

        # WHEN: using standardized element
        logger.info("msg", extra=Logging.sd_origin_extra(enterpriseId=None, software="software"))

        # THEN: PEN not part of sd-id
        assert caplog.records[0].msg == '[origin software="software"] msg'


def test_structured_data_origin_add_enterprise_id(caplog):
    with caplog.at_level(logging.INFO):
        # GIVEN: structured logger
        logger = Logging.getLogger()
        Logging.sd_define_origin(logger)

        # WHEN: using origin extra
        logger.info("msg", extra=Logging.sd_origin_extra(software="software"))

        # THEN: PEN not part of sd-id
        assert caplog.records[0].msg == '[origin enterpriseId="55029" software="software"] msg'


def test_structured_data_bnw(caplog):
    with caplog.at_level(logging.INFO):
        # GIVEN: structured logger with bnw sd
        logger = Logging.getLogger()
        Logging.sd_define_bnw(logger)

        # WHEN: logging with bnw sd
        logger.info("msg", extra=Logging.sd_bnw_extra(activity=BnwActivity.INCLUSION, device="device"))

        # THEN: sd part of message
        assert caplog.records[0].msg == '[bnw@55029 activity="inclusion" device="device"] msg'


def test_structured_data_bnw_with_metric(caplog):
    with caplog.at_level(logging.INFO):
        # GIVEN: structured logger with bnw sd
        logger = Logging.getLogger()
        Logging.sd_define_bnw(logger)
        Logging.sd_define_metric(logger)

        logging_extra_remote = Logging.sd_bnw_extra(BnwActivity.FOTA, "device", "true")
        logging_extra_remote.update(Logging.sd_bnw_metric("fota_upload", "true"))

        # WHEN: logging with bnw sd
        logger.info("msg", extra=logging_extra_remote)

        # THEN: sd part of message
        assert (
            caplog.records[0].msg
            == '[bnw@55029 activity="fota" device="device" remote="true"][metric@55029 name="fota_upload" value="true"]'
            " msg"
        )
