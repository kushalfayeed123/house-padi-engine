-- 1. Enable pgvector and UUID extensions
create extension if not exists vector;
create extension if not exists "uuid-ossp";

-- 2. Define System Enums to enforce state validity
-- 2. Define System Enums to enforce state validity (Idempotent)
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'property_status') THEN
        CREATE TYPE property_status AS ENUM ('available', 'rented', 'sold', 'under_maintenance', 'off_market');
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'transaction_type') THEN
        CREATE TYPE transaction_type AS ENUM ('rent_payment', 'security_deposit', 'maintenance_fee', 'commission');
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'payment_status') THEN
        CREATE TYPE payment_status AS ENUM ('pending', 'completed', 'failed');
    END IF;
END $$;

-- 3. Core Property Entity
create table if not exists public.properties (
    id uuid default gen_random_uuid() primary key,
    internal_code text unique not null,
    address text not null,
    status property_status default 'available',
    base_price numeric(15, 2) not null,
    specs jsonb default '{}', -- Structured metadata (e.g., {"beds": 3, "sqft": 2000})
    features text[],
    embedding vector(1536),   -- For semantic similarity search
    updated_at timestamp with time zone default now()
);

-- 4. Financial Ledger (Source of Truth)
create table if not exists public.financial_transactions (
    id uuid default gen_random_uuid() primary key,
    property_id uuid references public.properties(id),
    payer_id uuid not null,
    amount numeric(15, 2) not null,
    tx_type transaction_type not null,
    status payment_status default 'pending',
    created_at timestamp with time zone default now()
);

-- 5. Operational History (Context for Accuracy)
create table if not exists public.property_history (
    id uuid default gen_random_uuid() primary key,
    property_id uuid references public.properties(id),
    event_type text not null,
    payload jsonb,
    created_at timestamp with time zone default now()
);

-- 6. AI Agent Audit Ledger (Compliance/Tracing)
create table if not exists public.ai_agent_audit_ledger (
    id bigserial primary key,
    thread_id text not null,
    agent_persona text not null,
    query_context jsonb,
    agent_response text not null,
    created_at timestamp with time zone default now()
);

create table if not exists public.inspections (
    id uuid default gen_random_uuid() primary key,
    property_id uuid references public.properties(id),
    inspector_name text,
    notes text,
    created_at timestamp with time zone default now()
);

-- Indexing for high-performance retrieval
create index on public.properties using hnsw (embedding vector_cosine_ops);

-- Add to schema.sql
create or replace function match_properties(
  query_embedding vector(1536),
  budget_limit numeric,
  match_threshold float
)
returns table (
  id uuid,
  address text,
  base_price numeric,
  similarity float
)
language plpgsql
as $$
begin
  return query
  select
    p.id,
    p.address,
    p.base_price,
    1 - (p.embedding <=> query_embedding) as similarity
  from properties p
  where p.base_price <= budget_limit
  and 1 - (p.embedding <=> query_embedding) > match_threshold
  order by p.embedding <=> query_embedding
  limit 5;
end;
$$;