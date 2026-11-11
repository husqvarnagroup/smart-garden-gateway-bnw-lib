# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest


@pytest.fixture(scope="session")
def find_free_port():
    """
    Returns a factory that finds the next free port that is available on the OS
    This is a bit of a hack, it does this by creating a new socket, and calling
    bind with the 0 port. The operating system will assign a brand new port,
    which we can find out using getsockname(). Once we have the new port
    information we close the socket thereby returning it to the free pool.
    This means it is technically possible for this function to return the same
    port twice (for example if run in very quick succession), however operating
    systems return a random port number in the default range (1024 - 65535),
    and it is highly unlikely for two processes to get the same port number.
    In other words, it is possible to flake, but incredibly unlikely.
    """

    def _find_free_port():
        import socket

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("0.0.0.0", 0))
        portnum = s.getsockname()[1]
        s.close()

        return portnum

    return _find_free_port
