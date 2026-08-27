BEGIN;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS is_view_only BOOLEAN NOT NULL DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS account_members (
    id UUID PRIMARY KEY,
    account_id UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role VARCHAR(16) NOT NULL DEFAULT 'viewer',
    CONSTRAINT uq_account_member UNIQUE (account_id, user_id)
);

CREATE INDEX IF NOT EXISTS ix_account_members_account_id ON account_members(account_id);
CREATE INDEX IF NOT EXISTS ix_account_members_user_id ON account_members(user_id);

COMMIT;