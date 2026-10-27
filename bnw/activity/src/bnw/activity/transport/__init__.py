# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later


def delegate_abstract_methods(to):
    def dec(klass):
        def create_delegator(method):
            def delegator(self, *args, **kwargs):
                obj = getattr(self, to)
                m = getattr(obj, method)
                return m(*args, **kwargs)

            return delegator

        for m in klass.__abstractmethods__:
            setattr(klass, m, create_delegator(m))

        klass.__abstractmethods__ = frozenset()
        return klass

    return dec
