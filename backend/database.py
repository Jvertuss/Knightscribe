import os

import psycopg

from dotenv import load_dotenv
from psycopg.rows import dict_row


# Load variables from backend/.env
load_dotenv()


DATABASE_URL = os.getenv("DATABASE_URL")


if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is missing. "
        "Make sure backend/.env contains your Neon connection string."
    )


def get_connection():
    """
    Create and return a connection to the
    KnightScribe Neon PostgreSQL database.
    """

    return psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row,
    )