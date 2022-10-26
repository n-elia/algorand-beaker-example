import time

import pytest
from beaker import (
    consts,
    sandbox
)
from beaker.client import ApplicationClient
from beaker.sandbox import SandboxAccount

from contract import AlgoBet as ChildApp
from parent import Parent as ParentApp
from test import TestBase
from test.conftest import logger


class TestParentContractBase(TestBase):
    @pytest.fixture(scope="class")
    def creator_app_client(self, get_account, algod_client) -> ApplicationClient:
        """Return the application client signed by the creator account, popped out from
        sandbox accounts list. This account is fixed for the duration of a test class run.
        """
        creator_acct = get_account()

        return ApplicationClient(
            client=algod_client,
            # Instantiate app with the program version (default is MAX_TEAL_VERSION)
            app=ParentApp(),
            # Set the Transaction Signer as creator account
            signer=creator_acct.signer
        )

    @pytest.fixture(scope="class")
    def parent_app_addr(self, creator_app_client):
        """Create the application on chain using the Application Client of the creator account."""
        logger.debug("Creating the application...")
        app_id, app_addr, tx_id = creator_app_client.create()
        logger.debug(f"Created parent app with id: {app_id} and address: {app_addr} in tx: {tx_id}")

        creator_app_client.fund(1 * consts.algo)

        return app_addr

    @pytest.fixture(scope="class")
    def user_account(self, get_account) -> SandboxAccount:
        """Return the user's account, fixed for the duration of a test class run."""
        return get_account()


class TestParentContract(TestParentContractBase):
    def test_creation(self, parent_app_addr, creator_app_client):
        assert parent_app_addr == creator_app_client.app_addr

    def test_create_child(self, creator_app_client, user_account):
        # Call the parent app to create the child app
        result = creator_app_client.call(ParentApp.create_sub)
        child_app_id = result.return_value
        logger.debug(f"Created child app with id: {child_app_id} using account {creator_app_client.sender}")

        # Create a client for the child app, signed by user_account
        user_app_client = ApplicationClient(
            client=sandbox.get_algod_client(),
            app=ChildApp(),
            app_id=child_app_id,
            signer=user_account.signer
        )

        # Opt-in the child smart contract
        user_app_client.opt_in()

        # Set up the child smart contract
        user_app_client.call(
            ChildApp.setup,
            oracle_addr=user_app_client.sender,
            event_end_unix_timestamp=int(time.time()) + 2,
            payout_time_window_s=0,
        )
