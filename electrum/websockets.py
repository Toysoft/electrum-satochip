#!/usr/bin/env python
#
# Electrum - lightweight Bitcoin client
# Copyright (C) 2015 Thomas Voegtlin
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation files
# (the "Software"), to deal in the Software without restriction,
# including without limitation the rights to use, copy, modify, merge,
# publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS
# BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN
# ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
# CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
import threading
import os
import json
from collections import defaultdict
import asyncio
from typing import Dict, List, Tuple, TYPE_CHECKING
import traceback
import sys

from .util import PrintError
from . import bitcoin
from .synchronizer import SynchronizerBase

if TYPE_CHECKING:
    from .network import Network
    from .simple_config import SimpleConfig


request_queue = asyncio.Queue()

class BalanceMonitor(SynchronizerBase):
    """
    Used in electrum-merchant
    """
    def __init__(self, config: 'SimpleConfig', network: 'Network'):
        SynchronizerBase.__init__(self, network)
        self.config = config
        self.expected_payments = defaultdict(list)  # type: Dict[str, List[Tuple[WebSocket, int]]]

    def make_request(self, request_id):
        # read json file
        rdir = self.config.get('requests_dir')
        n = os.path.join(rdir, 'req', request_id[0], request_id[1], request_id, request_id + '.json')
        with open(n, encoding='utf-8') as f:
            s = f.read()
        d = json.loads(s)
        addr = d.get('address')
        amount = d.get('amount')
        return addr, amount

    async def main(self):
        # resend existing subscriptions if we were restarted
        for addr in self.expected_payments:
            await self._add_address(addr)
        # main loop
        while True:
            ws, request_id = await request_queue.get()
            try:
                addr, amount = self.make_request(request_id)
            except Exception:
                traceback.print_exc(file=sys.stderr)
                continue
            self.expected_payments[addr].append((ws, amount))
            await self._add_address(addr)

    async def _on_address_status(self, addr, status):
        self.print_error('new status for addr {}'.format(addr))
        sh = bitcoin.address_to_scripthash(addr)
        balance = await self.network.get_balance_for_scripthash(sh)
        for ws, amount in self.expected_payments[addr]:
            if not ws.closed:
                if sum(balance.values()) >= amount:
                    await ws.send_str('paid')
                    await ws.close()
