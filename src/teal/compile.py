"""TEAL generator script

This script, powered by `beaker`, allows the user to export a smart contract as TEAL code.
The output files are:
* approval_program.teal: approval program
* clear_program.teal:  clear program
* contract.json: JSON that documents the external ABI calls

Note: when parent app wants to be compiled, a running sandbox is required!
"""
import json
import os

from algosdk.atomic_transaction_composer import AccountTransactionSigner
from beaker import client, sandbox

from parent import AlgoBet, Parent

# Applications which include Precompiles need to be built using an ApplicationClient.
# This allows a recursive pre-compilation of child applications.
# Note: a running sandbox is required for instantiating an algod client.
parent_apps = [Parent()]

for a in parent_apps:
    app_client = client.ApplicationClient(
        sandbox.get_algod_client(),
        a,
        signer=AccountTransactionSigner("myprivatekey")
    )
    app_client.build()

child_apps = [AlgoBet()]

apps = [*child_apps, *parent_apps]

for app in apps:
    dir_path = os.path.join("src/teal", app.__class__.__name__)
    for filename, content in [
        ("approval_program.teal", app.approval_program),
        ("clear_program.teal", app.clear_program),
        ("contract.json", json.dumps(app.contract.dictify()))
    ]:
        os.makedirs(dir_path, exist_ok=True)
        with open(os.path.join(dir_path, filename), "w+") as fp:
            fp.write(content)
