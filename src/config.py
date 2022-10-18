import os
from typing import Optional

from pydantic import BaseSettings


class Config(BaseSettings):
    ###########################################################################
    # General
    ###########################################################################

    ###########################################################################
    # Logging
    ###########################################################################
    LOG_LEVEL: Optional[str] = None
    LOG_FORMAT: Optional[str] = None

    ###########################################################################
    # Test
    ###########################################################################
    TEST_SANDBOX_CONFIG: str = 'dev'  # dev, testnet
    TEST_SANDBOX_WALLET_NAME: Optional[str] = None  # only for testnet
    TEST_SANDBOX_WALLET_PASS: Optional[str] = None  # only for testnet

    class Config:
        case_sensitive = False
        env_file = os.getenv('DOT_ENV_FILE', './.env')
        env_file_encoding = os.getenv('DOT_ENV_FILE_ENCODING', 'utf-8')


current_config = Config()
