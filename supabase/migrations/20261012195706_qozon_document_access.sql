-- Phase 4 document index: owners plus named-user sharing.
-- Validated with tests/database/phase4_access.sql before application.
-- Reader: publishable API key + verified user JWT. Never the ingestion secret.

create extension if not exists vector with schema extensions;

create table public.qozon_documents (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null references auth.users(id) on delete cascade,
    title text not null check (length(btrim(title)) > 0),
    storage_bucket text not null,
    storage_object text not null,
    active_revision text check (active_revision ~ '^[0-9a-f]{64}$'),
    deleted boolean not null default false,
    embedding_model text not null default 'text-embedding-3-small'
        check (embedding_model = 'text-embedding-3-small'),
    created_at timestamptz not null default now(),
    unique (owner_id, storage_bucket, storage_object)
);

create table public.qozon_document_access (
    document_id uuid not null references public.qozon_documents(id) on delete cascade,
    user_id uuid not null references auth.users(id) on delete cascade,
    primary key (document_id, user_id)
);

create table public.qozon_chunks (
    id uuid primary key default gen_random_uuid(),
    document_id uuid not null references public.qozon_documents(id) on delete cascade,
    revision text not null check (revision ~ '^[0-9a-f]{64}$'),
    chunk_id text not null check (chunk_id ~ '^[0-9a-f]{64}$'),
    content text not null check (length(content) between 1 and 16000),
    evidence_content text check (length(evidence_content) between 1 and 16000),
    metadata jsonb not null check (jsonb_typeof(metadata) = 'object'),
    embedding extensions.vector(1536) not null,
    search_vector tsvector generated always as (to_tsvector('english', content)) stored,
    unique (document_id, revision, chunk_id)
);

create index qozon_documents_owner_idx on public.qozon_documents(owner_id);
create index qozon_access_user_idx on public.qozon_document_access(user_id, document_id);
create index qozon_chunks_search_idx on public.qozon_chunks using gin(search_vector);
-- The chunk uniqueness index already covers document_id + revision lookups.
-- Start with exact vector search; measure before adding an approximate index.

alter table public.qozon_documents enable row level security;
alter table public.qozon_document_access enable row level security;
alter table public.qozon_chunks enable row level security;

-- Grants are maintained only by an owner-checked privileged backend operation.
-- This policy lets readers see their own grant, avoiding policy recursion.
create policy qozon_own_access_rows on public.qozon_document_access
    for select to authenticated
    using (user_id = (select auth.uid()));

create policy qozon_read_documents on public.qozon_documents
    for select to authenticated
    using (not deleted and (
        owner_id = (select auth.uid()) or exists (
            select 1 from public.qozon_document_access a
            where a.document_id = qozon_documents.id
              and a.user_id = (select auth.uid())
        )
    ));

create policy qozon_read_active_chunks on public.qozon_chunks
    for select to authenticated
    using (exists (
        select 1 from public.qozon_documents d
        where d.id = qozon_chunks.document_id
          and d.active_revision = qozon_chunks.revision
          and not d.deleted
        -- The documents table's RLS applies here too.
    ));

revoke all on public.qozon_documents, public.qozon_document_access,
    public.qozon_chunks from public, anon, authenticated;
grant select on public.qozon_documents, public.qozon_document_access,
    public.qozon_chunks to authenticated;
-- Privileged writes are a separate ingestion/admin capability, never a reader.
grant all on public.qozon_documents, public.qozon_document_access,
    public.qozon_chunks to service_role;

-- Vector lane: cosine distance 0.65 matches the local baseline cutoff.
-- Optional metadata filters only narrow already-authorized rows.
create function public.qozon_match_chunks(
    query_embedding extensions.vector(1536),
    match_count integer default 12,
    filter jsonb default '{}'::jsonb
)
returns table (id uuid, content text, metadata jsonb, similarity double precision)
language sql stable security invoker
set search_path = ''
set row_security = on
as $$
    select c.id, coalesce(c.evidence_content, c.content),
           c.metadata || jsonb_build_object('cloud_document_id', c.document_id,
                'revision', c.revision, 'chunk_id', c.chunk_id),
           1 - (c.embedding operator(extensions.<=>) query_embedding)
    from public.qozon_chunks c
    where (select auth.uid()) is not null
      and c.metadata @> filter
      and c.embedding operator(extensions.<=>) query_embedding <= 0.65
    order by c.embedding operator(extensions.<=>) query_embedding, c.id
    limit greatest(0, least(coalesce(match_count, 12), 12));
$$;

-- Keyword lane: caller supplies normalized search terms (including aim/purpose).
-- Full-text ranking is not BM25; calibrate fusion against the local gold cases.
create function public.qozon_keyword_chunks(
    query_text text,
    match_count integer default 12,
    filter jsonb default '{}'::jsonb
)
returns table (id uuid, content text, metadata jsonb, rank double precision)
language sql stable security invoker
set search_path = ''
set row_security = on
as $$
    select c.id, coalesce(c.evidence_content, c.content),
           c.metadata || jsonb_build_object('cloud_document_id', c.document_id,
                'revision', c.revision, 'chunk_id', c.chunk_id),
           ts_rank(c.search_vector, websearch_to_tsquery('english', query_text))::double precision
    from public.qozon_chunks c
    where (select auth.uid()) is not null
      and length(query_text) between 1 and 2000
      and c.metadata @> filter
      and c.search_vector @@ websearch_to_tsquery('english', query_text)
    order by ts_rank(c.search_vector, websearch_to_tsquery('english', query_text)) desc, c.id
    limit greatest(0, least(coalesce(match_count, 12), 12));
$$;

revoke all on function public.qozon_match_chunks(extensions.vector, integer, jsonb)
    from public, anon, authenticated, service_role;
revoke all on function public.qozon_keyword_chunks(text, integer, jsonb)
    from public, anon, authenticated, service_role;
grant execute on function public.qozon_match_chunks(extensions.vector, integer, jsonb)
    to authenticated;
grant execute on function public.qozon_keyword_chunks(text, integer, jsonb)
    to authenticated;

-- Private Storage object policies and verified user-token API wiring are separate
-- required implementation steps. This migration does not change existing buckets.
