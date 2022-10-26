[![Compile TEAL](https://github.com/n-elia/algorand-beaker-example/actions/workflows/tests.yml/badge.svg?branch=dev)](https://github.com/n-elia/algorand-beaker-example/actions/workflows/tests.yml)
# An Algorand smart contract example using Beaker

This repository serves as an example to beginners. It contains an example of a working smart contract and its testing.

The example has been developed starting from [AlgoBet](https://github.com/n-elia/algobet), a very basic proposal of
decentralized bet system powered by Algorand that was born during
the 2022 edition
of [International School on Algorand Smart Contracts](https://algorand-school.github.io/algorand-school/).

## How to: deploy the smart contract and run a demo

### Environment setup

A Python 3 installation and Algorand sandbox are required to run the demo or tests.

Clone the repository and its submodules, prepare a virtual environment and install the project requirements with:

```shell
git clone --recurse-submodules https://github.com/n-elia/algorand-beaker-example.git

python3 -m venv venv
source venv/bin/activate 

pip install -r src/requirements.txt
pip install -r src/test/requirements.txt
```

### Run a Demo

To run a demo of this smart contract, a sandbox (note: it requires you a
working [docker-compose installation](https://docs.docker.com/compose/install/)) must be up and running. To use the
sandbox included in this repository:

```shell
cd src/test/sandbox
./sandbox up dev

# After sandbox loading, run the demo
python src/contract.py
```

The `demo()` method inside `src/contract.py` will be executed.

### Run the demo using the testnet

The tests can be run deploying the `sandbox` and attaching it to the `testnet`:

```shell
cd src/test/sandbox
./sandbox up testnet
```

From `sandbox` folder, create a wallet and populate it with two accounts:

```shell
cd src/test/sandbox
./sandbox enter algod
goal wallet new mywallet
goal account new -w mywallet
goal account new -w mywallet
```

Note: keep track of wallet name and password for next steps!

Then, fund those accounts using the [testnet bank](https://bank.testnet.algorand.network/) faucet.

To make `beaker.sandbox` client able to access your wallet, create a `src/.env` file as follows:

```shell
cd src
touch .env
```

And paste this content:

```dotenv
TEST_SANDBOX_CONFIG=testnet
TEST_SANDBOX_WALLET_NAME=mywallet
TEST_SANDBOX_WALLET_PASS=mywalletpassword
```

Then, you will be able to run the demo script as explained in the previous subsection.

## How to: run tests over the smart contract

### Run tests using sandbox in dev configuration

Tests are implemented using the `pytest` test framework for Python.
To run tests, the sandbox in `dev`mode must be up and running.
Therefore, we provided the test suite with the possibility to set up and teardown the sandbox network during each test
session.

This repository contains `sandbox` as a submodule, and the provided scripts point to it. Therefore, you can choose
between:

- setting up the `src/test/sandbox-scripts/sandbox_setup.sh`
  and `src/test/sandbox-scripts/sandbox_teardown.sh` shell scripts to point to your own `sandbox` directory.
- download `sandbox` submodule (note: it requires you a
  working [docker-compose installation](https://docs.docker.com/compose/install/)):

  ```shell
  # After moving in repo root directory
  git submodule init
  git submodule update
  ```

Then, you can enable automatic execution of those scripts at each run by using the `--sandbox` parameter on the `pytest`
CLI.

To run the test suite with default settings, just issue:

``` shell
# After moving in repo root directory
make test
```

The report will be located at `src/test/reports/pytest_report.html`. You can find a sample report there.

### Run tests using sandbox to connect to devnet

To run tests deploying the contract on `devnet`, you have to implement the snippet shown in _"Run the demo using the
testnet"_ section into `test_contract.py/TestBase.accounts()`.
Be sure to create enough accounts before running the tests.

### Compile to TEAL

Beaker framework can also be used for exporting TEAL code of the developed application.
The script `src/teal/compile.py` can be run to generate the Approval Program, Clear Program and transactions json:

```shell
python src/teal/compile.py
```

## What you can see this repository

- Smart contract implemented using Beaker framework: `src/contract.py`.

- Parent-child architecture implemented using Beaker Precompile: `src/parent.py` is a parent contract, which can be used
  to spawn AlgoBet child contracts, using the approach
  suggested in [algorand-devrel/parent-child-contracts](https://github.com/algorand-devrel/parent-child-contracts).

- Tests of time-based transactions with sandbox in `dev` mode, overcoming the issues introduced by the sandbox
  explained [here](https://github.com/n-elia/algobet#smart-contract-testing-issues-and-workarounds).
