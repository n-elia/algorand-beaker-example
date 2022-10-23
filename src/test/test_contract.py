import logging
import time
from pprint import pformat
from typing import Callable

import pytest
from algosdk.atomic_transaction_composer import TransactionWithSigner
from algosdk.encoding import decode_address
from algosdk.future import transaction
from beaker import (
    consts,
    external, sandbox
)
from beaker.client import ApplicationClient, LogicException
from beaker.sandbox import SandboxAccount
from pyteal import Approve

from src.test.conftest import logger
from src.contract import AlgoBet as App

from src.config import current_config as cc

# Block production time
block_prod_time = 0


# Workaround for https://github.com/algorand/go-algorand/issues/3192 .
# Add a dummy transaction to the smart contract. This transaction may be used for triggering
# the creation of a new block when using a sandbox in dev mode. In this way, transactions
# which depend on the timestamp of last forged block will be able to retrieve a recent block
# for current timestamp estimation.
@external
def dummy(self):
    return Approve()


App.dummy = dummy


class TestBase:
    """
    Base class for testing routines.

    When subclassing this, `config` dictionary and `_safe_*` methods will be subclass-scoped.
    A new instance of smart contract is deployed for each subclass, and its application ID may
    be retrieved using `app_addr` fixture.
    This allows classes to have different smart contract instances, each one with its own
    timing constraints.
    """
    ###########################################
    # Test configuration
    ###########################################
    # Test configuration
    config = {
        "session_start_s": time.time(),  # Start time of test session
        "event_end_since_test_start_s": 2,  # Time interval before event end
        "payout_time_s": 2  # Minimum time interval to allow payout
    }

    def _safe_to_payout(self):
        """ Return true if payout can be requested, according to creation parameters. """
        return time.time() > (
                self.config["session_start_s"] + self.config["event_end_since_test_start_s"] + block_prod_time)

    @pytest.fixture(scope="class")
    def safe_wait_to_payout(self, ping_sandbox):
        """Waits until payout time is reached. """

        def _safe_wait_to_payout():
            while not self._safe_to_payout():
                logger.debug("Waiting for a time in which payout is allowed.")
                # Workaround for https://github.com/algorand/go-algorand/issues/3192 .
                ping_sandbox()
                time.sleep(1)
            time.sleep(2)
            ping_sandbox()

        return _safe_wait_to_payout

    def _safe_to_delete(self):
        """ Return true if app can be deleted, according to creation parameters. """
        return time.time() > (
                self.config["session_start_s"] + self.config["event_end_since_test_start_s"] +
                self.config["payout_time_s"] + block_prod_time)

    @pytest.fixture(scope="class")
    def safe_wait_to_delete(self, ping_sandbox):
        """Waits until deletion time is reached. """

        def _safe_wait_to_delete():
            while not self._safe_to_delete():
                logger.debug("Waiting for a time in which app deletion is allowed.")
                # Workaround for https://github.com/algorand/go-algorand/issues/3192 .
                ping_sandbox()
                time.sleep(1)
            time.sleep(2)
            ping_sandbox()

        return _safe_wait_to_delete

    @pytest.fixture(scope="class", autouse=True)
    def update_test_start_time(self):
        """ Updates session start time, to allow _safe_to_payout and _safe_to_delete to work properly
         within test classes with different configurations.
         """
        self.config["session_start_s"] = time.time()
        logging.debug(f'{self.config["session_start_s"]}')
        return

    ###########################################
    # Test Accounts and Clients
    ###########################################
    @pytest.fixture(scope="class")
    def accounts(self):
        """Retrieve sandbox accounts. Accounts are re-listed for each TestBase subclass."""
        # Pop accounts from sandbox accounts
        if cc.TEST_SANDBOX_CONFIG == 'dev':
            return sandbox.get_accounts()
        elif cc.TEST_SANDBOX_CONFIG == 'testnet':
            return sandbox.get_accounts(
                wallet_name=cc.TEST_SANDBOX_WALLET_NAME,
                wallet_password=cc.TEST_SANDBOX_WALLET_PASS
            )
        else:
            pytest.exit("Wrong sandbox configuration")

    @pytest.fixture(scope="class")
    def get_account(self, accounts) -> Callable[[], SandboxAccount]:
        """Pop an account from the list of sandbox accounts."""
        accounts_count = 0

        def _get_account():
            nonlocal accounts_count
            try:
                accounts_count += 1
                return accounts.pop()
            except IndexError:
                pytest.skip(f"Attempting to get {accounts_count} account from sandbox."
                            f"No more available accounts in sandbox!", allow_module_level=True)

        return _get_account

    @pytest.fixture(scope="class")
    def creator_app_client(self, get_account, algod_client) -> ApplicationClient:
        """Return the application client signed by the creator account, popped out from
        sandbox accounts list. This account is fixed for the duration of a test class run.
        """
        creator_acct = get_account()

        return ApplicationClient(
            client=algod_client,
            # Instantiate app with the program version (default is MAX_TEAL_VERSION)
            app=App(),
            # Set the Transaction Signer as creator account
            signer=creator_acct.signer
        )

    @pytest.fixture(scope="class")
    def get_client(self, creator_app_client, get_account):
        """Return a client Factory built on top of an account popped from sandbox.

        New accounts clients are built using beaker's `prepare` method, which requires
        an already set-up app client, such as creator account's one.

        Recall that:
        -  Address of client account can be retrieved with: `client.get_sender()`
        -  The signer (TransactionSigner) of client account is stored into: `client.signer`
        """

        def _make_client():
            # Using existing app client, prepare a new client with a different signer account
            acct = get_account()
            return creator_app_client.prepare(signer=acct.signer)

        return _make_client

    @pytest.fixture(scope="class")
    def oracle_account(self, get_account) -> SandboxAccount:
        """Return the oracle's account, fixed for the duration of a test class run."""
        return get_account()

    @pytest.fixture(scope="class")
    def oracle_app_client(self, creator_app_client, oracle_account) -> ApplicationClient:
        """Return the oracle's application client, fixed for the duration of a test class run."""
        return creator_app_client.prepare(signer=oracle_account.signer)

    @pytest.fixture(scope="class")
    def participant_accounts(self, get_account) -> list[SandboxAccount]:
        """Return a list of 3 accounts, fixed for the duration of a test class run."""
        accounts_list = []
        for i in range(3):
            accounts_list.append(get_account())
        return accounts_list

    @pytest.fixture(scope="class")
    def participant_clients(self, creator_app_client, participant_accounts) -> list[ApplicationClient]:
        """Return  list of 3 application clients, fixed for the duration of a test class run."""
        clients_list = []
        for a in participant_accounts:
            clients_list.append(creator_app_client.prepare(signer=a.signer))
        return clients_list

    # Workaround for https://github.com/algorand/go-algorand/issues/3192 .
    @pytest.fixture(scope="class")
    def ping_sandbox(self, get_client):
        """Require a dummy transaction for triggering the creation of a new sandbox block.
        Workaround for https://github.com/algorand/go-algorand/issues/3192 .
        """
        c = get_client()

        def _call_dummy(client=c):
            client.call(App.dummy)

        return _call_dummy

    @pytest.fixture(scope="class")
    def app_addr(self, creator_app_client, oracle_account):
        """Create the application on chain using the Application Client of the creator account.
        `oracle_addr` parameter is set as the `oracle_account` account address.
        """
        logger.debug("Creating the application...")
        app_id, app_addr, tx_id = creator_app_client.create()
        logger.debug(f"Created app with id: {app_id} and address: {app_addr} in tx: {tx_id}")

        logger.debug("Setting up the application...")
        result = creator_app_client.call(
            App.setup,
            manager_addr=creator_app_client.get_sender(),
            oracle_addr=oracle_account.address,  # Don't use oracle client before app creation
            event_end_unix_timestamp=int(time.time() + self.config["event_end_since_test_start_s"]),
            payout_time_window_s=self.config["payout_time_s"],
        )
        app_state = creator_app_client.get_application_state()
        logger.debug(f"Setup requested with transaction: {result.tx_id}.\n"
                     f"Current app state: {app_state}")

        # Fund the app account with 200 milliAlgos (using creator account) for minimum balance
        fund_amount = 200 * consts.milli_algo
        creator_app_client.fund(fund_amount)
        logger.debug(f"Funded {app_addr} with {fund_amount}microAlgos")

        yield app_addr

        # Remove comments for enabling app teardown after a class test
        # try:
        #     creator_app_client.delete()
        # except Exception as e:
        #     logging.debug("Unable to delete the app (already deleted?): ", e)

    @pytest.fixture(scope="class", autouse=True)
    def debug_print(self):
        logger.debug(f"Class configuration:\n{pformat(self.config)}")


class TestContractPermissions(TestBase):
    def test_permissions_at_creation(self, app_addr, creator_app_client, oracle_app_client):
        # Get the App Global State
        app_state = creator_app_client.get_application_state()

        # Assert that the Global State variable `manager` has been correctly set to the creator address
        assert (app_state[App.manager.str_key()] == decode_address(creator_app_client.get_sender()).hex()), \
            "The manager should be equal to creator address"

        # Assert that the Global State variable `manager` has been correctly set to the creator address
        assert (app_state[App.oracle_addr.str_key()] == decode_address(oracle_app_client.get_sender()).hex()), \
            "The oracle should be equal to oracle address"

    def test_opt_in_creator(self, app_addr, creator_app_client):
        """Evaluate if transactions which require an opt-in cannot actually be accessed before the opt-in."""
        # Try calling bet() without opting in.
        with pytest.raises(LogicException):
            logger.debug("Try calling bet() without opting in...")
            creator_app_client.call(
                App.bet,  # noqa
                bet_deposit_tx=TransactionWithSigner(
                    txn=transaction.PaymentTxn(
                        creator_app_client.get_sender(),
                        creator_app_client.client.suggested_params(),
                        app_addr,
                        140 * consts.milli_algo),
                    signer=creator_app_client.signer
                ),
                opt=1
            )

        # Opt-in the accounts
        logger.debug("Opting-in accounts...")
        creator_app_client.opt_in()

        # Try calling set_nick() after opting in.
        logger.debug("Trying same transaction after opt-in...")
        _ = creator_app_client.call(
            App.bet,  # noqa
            bet_deposit_tx=TransactionWithSigner(
                txn=transaction.PaymentTxn(
                    creator_app_client.get_sender(),
                    creator_app_client.client.suggested_params(),
                    app_addr,
                    140 * consts.milli_algo),
                signer=creator_app_client.signer
            ),
            opt=1
        )

    def test_opt_in_participant(self, app_addr, get_client):
        """Evaluate if transactions which require an opt-in cannot actually be accessed before the opt-in."""
        # Try calling bet() without opting in.
        c = get_client()
        with pytest.raises(LogicException):
            logger.debug("Try calling bet() without opting in...")
            c.call(
                App.bet,  # noqa
                bet_deposit_tx=TransactionWithSigner(
                    txn=transaction.PaymentTxn(
                        c.get_sender(),
                        c.client.suggested_params(),
                        app_addr,
                        140 * consts.milli_algo),
                    signer=c.signer
                ),
                opt=1
            )

        # Opt-in the accounts
        logger.debug("Opting-in accounts...")
        c.opt_in()

        # Try calling set_nick() after opting in.
        logger.debug("Trying same transaction after opt-in...")
        _ = c.call(
            App.bet,  # noqa
            bet_deposit_tx=TransactionWithSigner(
                txn=transaction.PaymentTxn(
                    c.get_sender(),
                    c.client.suggested_params(),
                    app_addr,
                    140 * consts.milli_algo),
                signer=c.signer
            ),
            opt=1
        )

    def test_opt_in_oracle(self, app_addr, oracle_app_client):
        """Evaluate if transactions which require an opt-in cannot actually be accessed before the opt-in."""
        # Try calling bet() without opting in.
        c = oracle_app_client
        with pytest.raises(LogicException):
            logger.debug("Try calling bet() without opting in...")
            result = c.call(
                App.bet,  # noqa
                bet_deposit_tx=TransactionWithSigner(
                    txn=transaction.PaymentTxn(
                        c.get_sender(),
                        c.client.suggested_params(),
                        app_addr,
                        140 * consts.milli_algo),
                    signer=c.signer
                ),
                opt=1
            )

        # Opt-in the accounts
        logger.debug("Opting-in accounts...")
        c.opt_in()

        # Try calling set_nick() after opting in.
        logger.debug("Trying same transaction after opt-in...")
        _ = c.call(
            App.bet,  # noqa
            bet_deposit_tx=TransactionWithSigner(
                txn=transaction.PaymentTxn(
                    c.get_sender(),
                    c.client.suggested_params(),
                    app_addr,
                    140 * consts.milli_algo),
                signer=c.signer
            ),
            opt=1
        )

    def test_set_result_from_non_authorized(self, app_addr, creator_app_client, participant_clients,
                                            safe_wait_to_payout):
        safe_wait_to_payout()
        for c in [participant_clients[0], creator_app_client]:
            with pytest.raises(LogicException):
                c.call(
                    App.set_event_result,  # noqa
                    opt=1,
                )

    def test_delete_from_non_authorized(self, app_addr, oracle_app_client, participant_clients, safe_wait_to_payout):
        safe_wait_to_payout()
        for c in [participant_clients[0], oracle_app_client]:
            with pytest.raises(LogicException):
                c.delete()

    def test_app_deletion_and_close_out(self, creator_app_client, ping_sandbox, safe_wait_to_delete):
        # Delete the app
        safe_wait_to_delete()
        result = creator_app_client.delete()
        logger.debug(f"App deleted with TX {result}")

        # Assert close out of smart contract account
        assert creator_app_client.get_application_account_info()['amount'] == 0


class TestContractFlow(TestBase):
    # Test configuration
    config = {
        "session_start_s": time.time(),  # Start time of test session
        "event_end_since_test_start_s": 10,  # Time interval before event end
        "payout_time_s": 10  # Minimum time interval to allow payout
    }

    def test_participants_opt_in(self, app_addr, participant_clients):
        for p in participant_clients:
            p.opt_in()

    def test_make_bet_wrong_stack(self, app_addr, creator_app_client, participant_clients):
        balance_1 = creator_app_client.get_application_account_info()['amount']

        c = participant_clients[0]

        # TX for paying the bet quote
        bet_deposit_tx = TransactionWithSigner(
            txn=transaction.PaymentTxn(
                c.get_sender(),
                c.client.suggested_params(),
                app_addr,
                348 * consts.milli_algo),
            signer=c.signer
        )

        # Make a bet
        with pytest.raises(LogicException):
            c.call(
                App.bet,  # noqa
                bet_deposit_tx=bet_deposit_tx,
                opt=2
            )

        balance_2 = creator_app_client.get_application_account_info()['amount']

        assert balance_2 == balance_1

    def test_make_bet_wrong_option(self, app_addr, creator_app_client, participant_clients):
        balance_1 = creator_app_client.get_application_account_info()['amount']

        c = participant_clients[0]

        # TX for paying the bet quote
        bet_deposit_tx = TransactionWithSigner(
            txn=transaction.PaymentTxn(
                c.get_sender(),
                c.client.suggested_params(),
                app_addr,
                140 * consts.milli_algo),
            signer=c.signer
        )

        # Make a bet
        with pytest.raises(LogicException):
            c.call(
                App.bet,  # noqa
                bet_deposit_tx=bet_deposit_tx,
                opt=8
            )

        balance_2 = creator_app_client.get_application_account_info()['amount']

        assert balance_2 == balance_1

    def test_make_bets(self, app_addr, creator_app_client, participant_clients):
        def _make_bet(c: ApplicationClient, opt):
            # TX for paying the bet quote
            bet_deposit_tx = TransactionWithSigner(
                txn=transaction.PaymentTxn(
                    c.get_sender(),
                    c.client.suggested_params(),
                    app_addr,
                    140 * consts.milli_algo),
                signer=c.signer
            )

            # Make a bet
            c.call(
                App.bet,  # noqa
                bet_deposit_tx=bet_deposit_tx,
                opt=opt
            )

        balance_1 = creator_app_client.get_application_account_info()['amount']

        # Bets with different options
        _make_bet(participant_clients[0], 0)
        _make_bet(participant_clients[1], 0)
        _make_bet(participant_clients[2], 1)

        balance_2 = creator_app_client.get_application_account_info()['amount']

        assert (balance_2 - balance_1) == 140000 * 3

    def test_make_bets_twice(self, app_addr, creator_app_client, participant_clients):
        balance_1 = creator_app_client.get_application_account_info()['amount']

        c = participant_clients[0]

        # TX for paying the bet quote
        bet_deposit_tx = TransactionWithSigner(
            txn=transaction.PaymentTxn(
                c.get_sender(),
                c.client.suggested_params(),
                app_addr,
                140 * consts.milli_algo),
            signer=c.signer
        )

        # Make a bet
        with pytest.raises(LogicException):
            c.call(
                App.bet,  # noqa
                bet_deposit_tx=bet_deposit_tx,
                opt=2
            )

        balance_2 = creator_app_client.get_application_account_info()['amount']

        assert balance_2 == balance_1

    def test_request_payout_before_event_end(self, app_addr, participant_clients):
        c = participant_clients[0]

        with pytest.raises(LogicException):
            c.call(
                App.payout,  # noqa
            )

    def test_oracle_set_result_before_event_end(self, app_addr, oracle_app_client):
        c = oracle_app_client
        with pytest.raises(LogicException):
            c.call(
                App.set_event_result,  # noqa
                opt=1,
            )

    def test_request_payout_before_event_results(self, app_addr, participant_clients):
        c = participant_clients[0]

        with pytest.raises(LogicException):
            c.call(
                App.payout,  # noqa
            )

    def test_oracle_set_result_after_event_end(self, app_addr, oracle_app_client, safe_wait_to_payout):
        safe_wait_to_payout()

        c = oracle_app_client
        c.call(
            App.set_event_result,  # noqa
            opt=0
        )

    def test_request_payout_looser(self, app_addr, participant_clients):
        c = participant_clients[2]

        with pytest.raises(LogicException):
            c.call(
                App.payout,  # noqa
            )

    def test_request_payout_winners(self, app_addr, participant_clients):
        for c in [participant_clients[0], participant_clients[1]]:
            res = c.call(
                App.payout,  # noqa
            )
            tx_amount = res.tx_info["inner-txns"][0]["txn"]["txn"]["amt"]
            tx_fee = res.tx_info["inner-txns"][0]["txn"]["txn"]["fee"]
            assert tx_amount == (140000 * 3 / 2 - tx_fee)

    def test_request_payout_winners_again(self, app_addr, participant_clients):
        for c in [participant_clients[0], participant_clients[1]]:
            with pytest.raises(LogicException):
                res = c.call(
                    App.payout,  # noqa
                )
                tx_amount = res.tx_info["inner-txns"][0]["txn"]["txn"]["amt"]
                tx_fee = res.tx_info["inner-txns"][0]["txn"]["txn"]["fee"]
                assert tx_amount == (140000 * 3 / 2 - tx_fee)

    def test_request_deletion_before_payout_time(self, app_addr, creator_app_client):
        with pytest.raises(LogicException):
            creator_app_client.delete()

    def test_request_deletion_after_payout_time(self, app_addr, creator_app_client, safe_wait_to_delete):
        safe_wait_to_delete()
        creator_app_client.delete()


class TestContractNoWinners(TestBase):
    def test_participants_opt_in(self, app_addr, participant_clients):
        for p in participant_clients:
            p.opt_in()

    def test_make_bets(self, app_addr, creator_app_client, participant_clients):
        def _make_bet(c: ApplicationClient, opt):
            # TX for paying the bet quote
            bet_deposit_tx = TransactionWithSigner(
                txn=transaction.PaymentTxn(
                    c.get_sender(),
                    c.client.suggested_params(),
                    app_addr,
                    140 * consts.milli_algo),
                signer=c.signer
            )

            # Make a bet
            c.call(
                App.bet,  # noqa
                bet_deposit_tx=bet_deposit_tx,
                opt=opt
            )

        balance_1 = creator_app_client.get_application_account_info()['amount']

        # Bets with different options
        _make_bet(participant_clients[0], 0)
        _make_bet(participant_clients[1], 0)
        _make_bet(participant_clients[2], 0)

        balance_2 = creator_app_client.get_application_account_info()['amount']

        assert (balance_2 - balance_1) == 140000 * 3

    def test_oracle_set_result_after_event_end(self, app_addr, oracle_app_client, safe_wait_to_payout):
        safe_wait_to_payout()

        c = oracle_app_client
        c.call(
            App.set_event_result,  # noqa
            opt=2
        )

    def test_request_payout_winners(self, app_addr, participant_clients):
        for c in [participant_clients[0], participant_clients[1], participant_clients[2]]:
            with pytest.raises(LogicException):
                res = c.call(
                    App.payout,  # noqa
                )

    def test_request_deletion_after_payout_time(self, app_addr, creator_app_client, safe_wait_to_delete):
        safe_wait_to_delete()
        creator_app_client.delete()

        # Assert close out of smart contract account
        assert creator_app_client.get_application_account_info()['amount'] == 0
