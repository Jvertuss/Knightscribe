
from getpass import getpass

from argon2 import PasswordHasher
from database import get_connection


def main():
    print("=== KnightScribe Test Password Reset ===")

    email = input("Enter test account email: ").strip().lower()

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, role
                FROM users
                WHERE email = %s
                """,
                (email,)
            )
            user = cur.fetchone()

    if user is None:
        print("Account not found.")
        return

    print(f"Account: {user['name']} ({user['role']})")

    password = getpass("Enter new password: ")
    confirmation = getpass("Confirm new password: ")

    if len(password) < 12:
        print("Password must be at least 12 characters.")
        return

    if password != confirmation:
        print("Passwords do not match.")
        return

    password_hash = PasswordHasher().hash(password)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE users
                SET password_hash = %s
                WHERE id = %s
                """,
                (password_hash, user["id"])
            )

            # Log out existing sessions for this account.
            cur.execute(
                """
                DELETE FROM sessions
                WHERE user_id = %s
                """,
                (user["id"],)
            )

    print("Password reset successfully!")
    print("Existing login sessions have been revoked.")


if __name__ == "__main__":
    main()
