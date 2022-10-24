"""Parent application smart contract

This file contains the definition of the parent smart contract, which may be used to
instantiate several instances of the child smart contract.
"""
import time
from typing import Final

from beaker import Application, external, sandbox, client, consts, ApplicationStateValue
from beaker.precompile import AppPrecompile
from pyteal import (
    abi,
    TealType,
    TxnType,
    Seq,
    InnerTxnBuilder,
    TxnField,
    InnerTxn,
    Global,
)

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
                    TxnField.type_enum: TxnType.ApplicationCall,
                    TxnField.approval_program: self.sub_app.approval.binary,
                    TxnField.clear_state_program: self.sub_app.clear.binary,
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

    accts = _get_accounts_from_sandbox()
    acct = accts.pop()
    acct2 = accts.pop()

    # Create main app and fund it
    app_client_main = client.ApplicationClient(
        sandbox.get_algod_client(), Parent(), signer=acct.signer
    )
    main_app_id, _, _ = app_client_main.create()
    print(f"Created main app: {main_app_id}")
    app_client_main.fund(1 * consts.algo)

    # Call the main app to create the sub app
    result = app_client_main.call(Parent.create_sub)
    sub_app_id = result.return_value
    print(f"Created sub app: {sub_app_id}")

    # setup client for sub app, signed by acct2
    sub_app_client = client.ApplicationClient(
        sandbox.get_algod_client(), AlgoBet(), signer=acct2.signer
    )
    result = sub_app_client.create()
    print(result)
    print("sub app client: ", sub_app_client.sender)
    # sub_app_client.app_id = sub_app_id
    # sub_app_client.app_addr = get_application_address(sub_app_id)

    # Call setup method of sub app
    result = sub_app_client.call(
        AlgoBet.setup,
        manager_addr=acct.address,
        oracle_addr=acct.address,
        event_end_unix_timestamp=int(time.time() + 60),
        payout_time_window_s=int(60)
    )
    print(f"Return value: {result.return_value}")

    # result = app_client_main.call(
    #     Parent.delete_asset,
    #     asset=created_asset,
    # )
    # print(f"Deleted asset in tx: {result.tx_id}")


if __name__ == "__main__":
    demo()
    # pass
