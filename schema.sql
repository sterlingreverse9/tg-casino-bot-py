-- The Casino — database schema
-- Run this in Supabase SQL Editor before starting the bot

-- Users / wallets
create table if not exists users (
  telegram_id bigint primary key,
  username text,
  balance numeric not null default 1000,
  total_wagered numeric not null default 0,
  total_won numeric not null default 0,
  total_lost numeric not null default 0,
  is_admin boolean not null default false,
  created_at timestamptz not null default now()
);

-- Bet history
create table if not exists bets (
  id bigserial primary key,
  telegram_id bigint references users(telegram_id),
  game text not null,
  bet_amount numeric not null,
  payout numeric not null default 0,
  result text not null, -- 'win' | 'loss'
  meta jsonb,
  created_at timestamptz not null default now()
);

-- Admin action audit log (add/deduct/rain/promote/updatehb)
create table if not exists admin_actions (
  id bigserial primary key,
  admin_id bigint not null,
  action text not null,
  target_id bigint,
  amount numeric,
  created_at timestamptz not null default now()
);

-- House virtual balance (single row)
create table if not exists house (
  id int primary key default 1,
  balance numeric not null default 0
);
insert into house (id, balance) values (1, 0) on conflict (id) do nothing;
