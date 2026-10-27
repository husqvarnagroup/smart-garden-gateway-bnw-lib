# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.absolute() / "src"))
collect_ignore = [str(Path(__file__).parent.absolute() / "src")]
