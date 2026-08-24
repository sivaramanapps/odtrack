






CREATE TABLE public.account_rate_history (
    id uuid NOT NULL,
    account_id uuid NOT NULL,
    effective_date date NOT NULL,
    interest_rate numeric(5,2) NOT NULL,
    penal_rate numeric(5,2) NOT NULL
);


ALTER TABLE public.account_rate_history OWNER TO odtrack;


CREATE TABLE public.accounts (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    label character varying(120) NOT NULL,
    sanctioned_limit numeric(18,2) NOT NULL,
    interest_rate numeric(8,6) NOT NULL,
    penal_rate numeric(8,6) NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT ck_account_limit_nonnegative CHECK ((sanctioned_limit >= (0)::numeric))
);


ALTER TABLE public.accounts OWNER TO odtrack;


CREATE TABLE public.transactions (
    id uuid NOT NULL,
    account_id uuid NOT NULL,
    effective_date date NOT NULL,
    type character varying(16) NOT NULL,
    amount numeric(18,2) NOT NULL,
    CONSTRAINT ck_transaction_amount_positive CHECK ((amount > (0)::numeric)),
    CONSTRAINT ck_transaction_type CHECK (((type)::text = ANY ((ARRAY['debit'::character varying, 'credit'::character varying])::text[])))
);


ALTER TABLE public.transactions OWNER TO odtrack;


CREATE TABLE public.users (
    id uuid NOT NULL,
    username character varying(80) NOT NULL,
    pin_hash text NOT NULL
);


ALTER TABLE public.users OWNER TO odtrack;


ALTER TABLE ONLY public.account_rate_history
    ADD CONSTRAINT account_rate_history_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.accounts
    ADD CONSTRAINT accounts_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.transactions
    ADD CONSTRAINT transactions_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.account_rate_history
    ADD CONSTRAINT uq_account_rate_effective_date UNIQUE (account_id, effective_date);



ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);



CREATE INDEX ix_account_rate_history_account_id ON public.account_rate_history USING btree (account_id);



CREATE INDEX ix_account_rate_history_effective_date ON public.account_rate_history USING btree (effective_date);



CREATE INDEX ix_accounts_user_id ON public.accounts USING btree (user_id);



CREATE INDEX ix_transactions_account_id ON public.transactions USING btree (account_id);



CREATE INDEX ix_transactions_effective_date ON public.transactions USING btree (effective_date);



CREATE UNIQUE INDEX ix_users_username ON public.users USING btree (username);



ALTER TABLE ONLY public.account_rate_history
    ADD CONSTRAINT account_rate_history_account_id_fkey FOREIGN KEY (account_id) REFERENCES public.accounts(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.accounts
    ADD CONSTRAINT accounts_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.transactions
    ADD CONSTRAINT transactions_account_id_fkey FOREIGN KEY (account_id) REFERENCES public.accounts(id) ON DELETE CASCADE;




