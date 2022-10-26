"""Parent application smart contract

This file contains the definition of the parent smart contract, which may be used to
instantiate several instances of the child smart contract.
"""
import time
from typing import Final

from beaker import Application, external, sandbox, consts, ApplicationStateValue
from beaker.client.application_client import ApplicationClient
from beaker.precompile import AppPrecompile
from pyteal import (
    abi,
    TealType,
    Seq,
    InnerTxnBuilder,
    InnerTxn,
    Global, )

from config import current_config as cc
from contract import AlgoBet


class Parent(Application):
    ###########################################
    # Application State
    ###########################################

    # Store a "manager" account, which will have particular privileges
    manager: Final[ApplicationStateValue] = ApplicationStateValue(
        stack_type=TealType.bytes,
        # Default to the application creator address
        default=Global.creator_address()
    )

    # Store the pre-compiled child application
    sub_app: Final[AppPrecompile] = AppPrecompile(AlgoBet())

    @external
    def create_sub(self, *, output: abi.Uint64):
        return Seq(
            InnerTxnBuilder.Execute(
                {
                    # Auto generation of create call parameters
                    **self.sub_app.get_create_config(),
                }
            ),
            output.set(InnerTxn.created_application_id()),
        )


def demo():
    def _get_accounts_from_sandbox():
        if cc.TEST_SANDBOX_CONFIG == 'dev':
            return sandbox.get_accounts()
        elif cc.TEST_SANDBOX_CONFIG == 'testnet':
            return sandbox.get_accounts(
                wallet_name=cc.TEST_SANDBOX_WALLET_NAME,
                wallet_password=cc.TEST_SANDBOX_WALLET_PASS
            )
        else:
            raise NameError("Wrong sandbox configuration")

    # Get accounts
    accts = _get_accounts_from_sandbox()
    acct = accts.pop()
    acct2 = accts.pop()

    # Create main app and fund it
    app_client_main = ApplicationClient(
        sandbox.get_algod_client(), Parent(), signer=acct.signer
    )
    main_app_id, _, _ = app_client_main.create()
    print(f"Created main app: {main_app_id} by account {app_client_main.sender}")
    app_client_main.fund(1 * consts.algo)

    # Call the main app to create the sub app
    result = app_client_main.call(Parent.create_sub)
    sub_app_id = result.return_value
    print(f"Created sub app: {sub_app_id} by account {app_client_main.sender}")
    print(f"Sub app state:\n{app_client_main.get_application_state()}")

    # Create a new user using account 2
    app_client_user = ApplicationClient(
        client=sandbox.get_algod_client(),
        app=AlgoBet(),
        signer=acct2.signer,
        app_id=sub_app_id,
    )

    # Opt-in the child smart contract
    app_client_user.opt_in()
    print(f"Sub app state:\n{app_client_user.get_application_state()}")
    print(f"Account state:\n{app_client_user.get_account_state()}")

    # Set up the child smart contract
    app_client_user.call(
        AlgoBet.setup,
        oracle_addr=app_client_user.sender,
        event_end_unix_timestamp=int(time.time()) + 2,
        payout_time_window_s=0,
    )
    print(f"Sub app state:\n{app_client_user.get_application_state()}")


if __name__ == "__main__":
    demo()
