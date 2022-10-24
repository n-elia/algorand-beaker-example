import time
from math import ceil
from typing import Final

from algosdk.atomic_transaction_composer import TransactionWithSigner
from algosdk.future import transaction
from beaker import (
    consts,
    sandbox,
    opt_in,
    ApplicationStateValue,
    AccountStateValue,
    Authorize,
    delete,
)
from beaker.application import Application
from beaker.client import ApplicationClient
from beaker.decorators import external, internal
from pyteal import (
    Assert, TealType, Global, Int, Approve, abi, Seq, Cond, InnerTxnBuilder, TxnField, TxnType,
    Txn, Div, Minus, If
)

from config import current_config as cc

# microAlgos minimum fee for transactions
network_min_trans_fee = Int(1000)


# Create an app subclassing `beaker.Application`
class AlgoBet(Application):
    ###########################################
    # Application State
    ###########################################

    # Store a "manager" account, which will have particular privileges
    manager: Final[ApplicationStateValue] = ApplicationStateValue(
        stack_type=TealType.bytes,
        # Default to the application creator address
        default=Global.creator_address()
    )

    # Store the oracle address
    oracle_addr: Final[ApplicationStateValue] = ApplicationStateValue(
        stack_type=TealType.bytes,
        # Default to the application creator address
        default=Global.creator_address()
    )

    # Store the event result
    event_result: Final[ApplicationStateValue] = ApplicationStateValue(
        stack_type=TealType.uint64,
        default=Int(99)
    )

    # Store the fixed bet amount
    bet_amount: Final[ApplicationStateValue] = ApplicationStateValue(
        stack_type=TealType.uint64,
        # Defaults to 140 milliAlgos
        default=consts.MilliAlgos(140),
        descr="Fixed bet amount."
    )

    # Store the bet options
    counter_opt_0: Final[ApplicationStateValue] = ApplicationStateValue(
        stack_type=TealType.uint64,
        default=Int(0),
        descr="Number of bet on '0' event. can be used as a total budget since bet amount is fixed"
    )

    counter_opt_1: Final[ApplicationStateValue] = ApplicationStateValue(
        stack_type=TealType.uint64,
        default=Int(0),
        descr="Number of bet on '1' event. can be used as a total budget since bet amount is fixed"
    )

    counter_opt_2: Final[ApplicationStateValue] = ApplicationStateValue(
        stack_type=TealType.uint64,
        default=Int(0),
        descr="Number of bet on '2' event. can be used as a total budget since bet amount is fixed"
    )

    stake_amount: Final[ApplicationStateValue] = ApplicationStateValue(
        stack_type=TealType.uint64,
        default=Int(0),
        descr="Algos collected with bets"
    )

    winning_count: Final[ApplicationStateValue] = ApplicationStateValue(
        stack_type=TealType.uint64,
        default=Int(0),
        descr="Number of winning accounts"
    )

    winning_payout: Final[ApplicationStateValue] = ApplicationStateValue(
        stack_type=TealType.uint64,
        default=Int(0),
        descr="Algos that winner participants will receive"
    )

    event_timestamp: Final[ApplicationStateValue] = ApplicationStateValue(
        stack_type=TealType.uint64,
        default=Int(0),
        descr="Unix UTC timestamp at which the event ends"
    )

    payout_time_window_s: Final[ApplicationStateValue] = ApplicationStateValue(
        stack_type=TealType.uint64,
        default=Int(0),
        descr="Minimum amount of seconds to wait between event end and smart contract deletion."
    )

    ###########################################
    # Account State
    ###########################################

    chosen_opt: Final[AccountStateValue] = AccountStateValue(
        stack_type=TealType.uint64,
        descr="Bet option chosen by the participant user"
    )

    has_placed_bet: Final[AccountStateValue] = AccountStateValue(
        stack_type=TealType.uint64, default=Int(0),
        descr="Flag to check if the account has already placed a bet"
    )

    has_requested_payout: Final[AccountStateValue] = AccountStateValue(
        stack_type=TealType.uint64, default=Int(0),
        descr="Flag to check if the account has already requested the payout"
    )

    ###########################################
    # Administrative Actions
    ###########################################

    @external
    def setup(self,
              manager_addr: abi.Address,
              oracle_addr: abi.Address,
              event_end_unix_timestamp: abi.Uint64,
              payout_time_window_s: abi.Uint64):
        """ Initialize application state variables at creation time. """
        return Seq(
            self.initialize_application_state(),
            If(manager_addr.get() != Txn.sender(), self.set_manager(manager_addr)),
            If(oracle_addr.get() != Txn.sender(), self.set_oracle(oracle_addr)),
            # Checks that the provided event timestamp represents a future period
            Assert(event_end_unix_timestamp.get() > Global.latest_timestamp(),
                   comment="Expiry time must be in the future."),
            self.set_event_end_time(event_end_unix_timestamp),
            self.set_payout_time(payout_time_window_s),
        )

    # Authorize only the manager account to request this transaction
    @external(authorize=Authorize.only(addr=oracle_addr))
    def set_event_result(self, opt: abi.Uint64):
        """ Set the event result. """
        return Seq(
            Assert(Global.latest_timestamp() >= self.event_timestamp.get(),
                   comment="Event expiry time not reached, yet."),
            # Assert that the option is valid
            Assert(
                Cond(
                    [opt.get() == Int(0), Int(1)],
                    [opt.get() == Int(1), Int(1)],
                    [opt.get() == Int(2), Int(1)],
                ),
                comment="Valid options are: 0, 1, 2"
            ),
            # Put the winning option into Global State variable "event_result"
            self.event_result.set(opt.get()),
            # Compute the number of winning participants
            Cond(
                [opt.get() == Int(0), self.winning_count.set(self.counter_opt_0.get())],
                [opt.get() == Int(1), self.winning_count.set(self.counter_opt_1.get())],
                [opt.get() == Int(2), self.winning_count.set(self.counter_opt_2.get())],
            ),
            # To avoid division by zero, check if there is a non-zero number of winners
            If(
                self.winning_count.get() == Int(0),
                # Compute the (dummy) winning payout as: total_stake - network_min_trans_fee
                self.winning_payout.set(
                    Minus(
                        self.stake_amount.get(),
                        network_min_trans_fee
                    )
                ),
                # Compute the winning payout as: (total_stake / number_of_winners) - network_min_trans_fee
                self.winning_payout.set(
                    Minus(
                        Div(
                            self.stake_amount.get(),
                            self.winning_count.get()
                        ),
                        network_min_trans_fee
                    )
                )
            ),
        )

    @delete(authorize=Authorize.only(manager))
    def delete(self):
        return Seq(
            # Assert that the event ended
            Assert(Global.latest_timestamp() >= self.event_timestamp.get(),
                   comment="Event expiry time not reached, yet."),
            # Assert that the payout time elapsed
            Assert(Global.latest_timestamp() >= self.event_timestamp.get() + self.payout_time_window_s.get(),
                   comment="Payout time not expired, yet."),
            # Make a transaction for closing out the smart contract account
            InnerTxnBuilder.Execute(
                {
                    TxnField.type_enum: TxnType.Payment,
                    TxnField.receiver: Txn.sender(),
                    TxnField.amount: Int(0),
                    # If close_remainder_to is defined, the Sender account will be closed, and all the
                    # remaining funds, after the fee and amount are paid, will be transferred to it
                    TxnField.close_remainder_to: Txn.sender(),
                },
            ),
            Approve()
        )

    ###########################################
    # Bare Calls
    ###########################################

    @opt_in
    def opt_in(self):
        """ Initialize the sender account state variables. """
        return self.initialize_account_state()

    ###########################################
    # Internal methods
    ###########################################

    @internal(TealType.none)
    def set_manager(self, new_manager: abi.Address):
        """ Change the application manager account address. """
        return self.manager.set(new_manager.get())

    @internal(TealType.none)
    def set_oracle(self, new_oracle_addr: abi.Address):
        """ Change the application oracle account address. """
        return self.oracle_addr.set(new_oracle_addr.get())

    @internal(TealType.none)
    def set_event_end_time(self, unix_timestamp: abi.Uint64):
        """ Change the timestamp at which the event ends. """
        return self.event_timestamp.set(unix_timestamp.get())

    @internal(TealType.none)
    def set_payout_time(self, time_s: abi.Uint64):
        """ Change the time at which deletion is enabled since event end. """
        return self.payout_time_window_s.set(time_s.get())

    ###########################################
    # Exposed Application Calls
    ###########################################

    @external(authorize=Authorize.opted_in(app_id=Application.id))
    def bet(self, opt: abi.Uint64, bet_deposit_tx: abi.PaymentTransaction):
        """ Place a bet. """
        return Seq(
            # Check if the event has been closed
            Assert(
                self.event_result.get() == self.event_result.default,
                comment="The event is closed. Bets are no more allowed"
            ),
            # Check if the bet is equal to the fixed amount
            Assert(
                bet_deposit_tx.get().amount() == self.bet_amount.get(),
                comment="Bet amount is wrong"
            ),
            # Assert that the deposit targets the smart contract
            Assert(
                bet_deposit_tx.get().receiver() == self.address,
                comment="Receiver must be the smart contract"
            ),
            # Assert that the user has not placed any bet yet
            Assert(
                self.has_placed_bet.get() == Int(0),
                comment="User has already placed a bet"
            ),
            # Assert that the option is valid
            Assert(
                Cond(
                    [opt.get() == Int(0), Int(1)],
                    [opt.get() == Int(1), Int(1)],
                    [opt.get() == Int(2), Int(1)],
                ),
                comment="Valid options are: 0, 1, 2"
            ),
            # Store the chosen option into Local State
            self.chosen_opt.set(opt.get()),
            # Increase the chosen option counter
            Cond(
                [opt.get() == Int(0), self.counter_opt_0.set(self.counter_opt_0.get() + Int(1))],
                [opt.get() == Int(1), self.counter_opt_1.set(self.counter_opt_1.get() + Int(1))],
                [opt.get() == Int(2), self.counter_opt_2.set(self.counter_opt_2.get() + Int(1))],
            ),
            # Set the 'bet already placed' flag for the sender account
            self.has_placed_bet.set(Int(1)),
            # Increase the stake amount
            self.stake_amount.set(self.stake_amount.get() + self.bet_amount.get())
        )

    @external
    def payout(self):
        return Seq(
            # Assert that the participant has chosen the winning option
            Assert(
                self.event_result == self.chosen_opt,
                comment="You did not choose the winning option"
            ),
            # Assert that the participant is not requesting the payout a second time
            Assert(
                self.has_requested_payout == Int(0),
                comment="You already requested your payout"
            ),
            # Set the 'payout already requested' flag for the sender account
            self.has_requested_payout.set(Int(1)),
            # Make a transaction for payout
            InnerTxnBuilder.Execute(
                {
                    TxnField.type_enum: TxnType.Payment,
                    TxnField.receiver: Txn.sender(),
                    TxnField.amount: self.winning_payout.get(),
                    # If close_remainder_to is defined, the Sender account will be closed, and all the
                    # remaining funds, after the fee and amount are paid, will be transferred to it
                    # TxnField.close_remainder_to: Txn.sender(),
                }
            ),
        )


def demo():
    ###################################
    # Setup of clients and app creation
    ###################################

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

    # Get sandbox algod client
    sandbox_client = sandbox.get_algod_client()

    # Pop an account from sandbox accounts
    sandbox_accounts = _get_accounts_from_sandbox()
    acct_1 = sandbox_accounts.pop()
    acct_2 = sandbox_accounts.pop()
    print(f"Popped out accounts: \n  - {acct_1.address}\n  - {acct_2.address}")

    # Create an Application client containing both an algod client and app
    print("Creating application client 2...")
    app_client_acct_2 = ApplicationClient(
        # Use the sandbox client
        client=sandbox_client,
        # Instantiate app with the program version (default is MAX_TEAL_VERSION)
        app=AlgoBet(),
        # Set the Transaction Signer of acct_1 account
        signer=acct_2.signer
    )

    # Create the application on chain, using the Application Client (signed by acct_2)
    print("Creating the application using account 2...")
    app_id, app_addr, tx_id = app_client_acct_2.create()
    print(f"Created app with id: {app_id} and address: {app_addr} in tx: {tx_id}")

    # Setup the application
    app_client_acct_2.call(
        AlgoBet.setup,
        manager_addr=acct_2.address,
        oracle_addr=acct_1.address,
        event_end_unix_timestamp=int(time.time() + 60),
        payout_time_window_s=int(60)
    )
    print(f"Current app state: {app_client_acct_2.get_application_state()}")

    # Fund the app account with 1 algo (using acct_1) for minimum balance
    app_client_acct_2.fund(1 * consts.algo)

    # Create copies of the app client with different signers __after__ having created the app
    print("Creating application client 1...")
    app_client_acct_1 = app_client_acct_2.prepare(signer=acct_1.signer)

    ###################################
    # Demo
    ###################################

    def spacer(msg=''):
        width = 80
        budget = width - len(msg) - 2 if msg != '' else width
        sep = '=' * ceil(budget / 2)
        print(f"{sep}{f' {msg} ' if msg != '' else msg}{sep if budget % 2 == 0 else sep[:-1]}")

    # Opt-in the accounts
    print("Opting-in account 1...")
    app_client_acct_1.opt_in()
    print("Opting-in account 2...")
    app_client_acct_2.opt_in()

    # Get the local state for each account
    print("Account 1 local state: ", app_client_acct_1.get_account_state())
    print("Account 2 local state: ", app_client_acct_2.get_account_state())

    # Get smart contract's account balance
    print("Smart contract account balance: ", app_client_acct_1.get_application_account_info()['amount'])

    spacer("Account 1 places a bet")

    # Try placing a bet from acct_1
    print("Requesting bet() transaction...")
    result = app_client_acct_1.call(
        AlgoBet.bet,  # noqa
        bet_deposit_tx=TransactionWithSigner(
            txn=transaction.PaymentTxn(
                acct_1.address,
                app_client_acct_1.client.suggested_params(),
                app_addr,
                140 * consts.milli_algo),
            signer=acct_1.signer
        ),
        opt=1
    )
    print(f"Transaction completed with ID: {result.tx_id}")

    # Get smart contract's account balance
    print("Smart contract account balance: ", app_client_acct_1.get_application_account_info()['amount'])
    # Get the local state for each account before and after nickname change
    print("Account 1 local state: ", app_client_acct_1.get_account_state())
    # Get the global state
    print(f"Current app state: {app_client_acct_1.get_application_state()}")

    spacer("Account 2 places a bet")

    # Try placing a bet from acct_2
    print("Requesting bet() transaction...")
    result = app_client_acct_2.call(
        AlgoBet.bet,  # noqa
        bet_deposit_tx=TransactionWithSigner(
            txn=transaction.PaymentTxn(
                acct_2.address,
                app_client_acct_2.client.suggested_params(),
                app_addr,
                140 * consts.milli_algo),
            signer=acct_2.signer
        ),
        opt=2
    )
    print(f"Transaction completed with ID: {result.tx_id}")

    # Get smart contract's account balance
    print("Smart contract account balance: ", app_client_acct_2.get_application_account_info()['amount'])
    # Get the local state for each account before and after nickname change
    print("Account 1 local state: ", app_client_acct_2.get_account_state())
    # Get the global state
    print(f"Current app state: {app_client_acct_2.get_application_state()}")

    spacer("Account 1 (oracle) sets the event result")

    # Try setting the event result
    print("Requesting set_event_result() transaction in 3s...")
    time.sleep(3)
    app_client_acct_1.call(
        AlgoBet.set_event_result,  # noqa
        opt=1
    )

    # Get the global state
    print(f"Current app state: {app_client_acct_1.get_application_state()}")

    spacer("Account 1 requests payout")

    # Print balances before payout
    sc_bal_before = app_client_acct_1.get_application_account_info()['amount']
    acct_1_bal_before = sandbox_client.account_info(acct_1.address)['amount']
    print("Smart contract account balance: ", sc_bal_before)
    print("Account 1 balance: ", acct_1_bal_before)

    # Try to payout
    print("Requesting payout() transaction...")
    app_client_acct_1.call(
        AlgoBet.payout,  # noqa
    )

    # Print balances after payout
    sc_bal_after = app_client_acct_1.get_application_account_info()['amount']
    acct_1_bal_after = sandbox_client.account_info(acct_1.address)['amount']
    print("Smart contract account balance: ", sc_bal_after)
    print("Account 1 balance: ", acct_1_bal_after)
    print("Smart contract account balance difference: ", sc_bal_after - sc_bal_before)
    print("Account 1 balance difference: ", acct_1_bal_after - acct_1_bal_before)
    print("(remember: the minimum fee on Algorand is currently 1000 microAlgos)")

    spacer("Manager account deletes the smart contract after event end")

    print("Requesting delete() transaction in 3s...")
    time.sleep(3)
    app_client_acct_2.delete()

    print("Smart contract account balance: ", app_client_acct_1.get_application_account_info()['amount'])
    print("Account 1 balance: ", sandbox_client.account_info(acct_1.address)['amount'])
    print("Account 2 balance: ", sandbox_client.account_info(acct_2.address)['amount'])


if __name__ == "__main__":
    demo()
