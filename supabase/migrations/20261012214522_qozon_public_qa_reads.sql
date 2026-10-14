-- User-selected model: public Q&A and approved citations; original PDF stays private.
-- Publishing is opt-in and only trusted ingestion/admin jobs may write rows.
alter table public.qozon_documents add column public_read boolean not null default false;
alter table public.qozon_documents alter column owner_id drop not null;
create unique index qozon_ownerless_source_idx
    on public.qozon_documents(storage_bucket, storage_object) where owner_id is null;

create policy qozon_public_documents on public.qozon_documents
    for select to anon, authenticated
    using (public_read and not deleted and active_revision is not null);

create policy qozon_public_chunks on public.qozon_chunks
    for select to anon, authenticated
    using (exists (
        select 1 from public.qozon_documents d
        where d.id = qozon_chunks.document_id and d.public_read and not d.deleted
          and d.active_revision = qozon_chunks.revision
    ));

-- The visitor cannot select owner IDs or the private PDF's bucket/object location.
grant select (id, title, active_revision, public_read, deleted)
    on public.qozon_documents to anon;
grant select on public.qozon_chunks to anon;
-- No anonymous sharing/write privileges; existing private owner/share rules are retained.
-- Storage stays private and closed to direct user reads. The API has no PDF route.

-- Vector lane: cosine distance 0.65 matches the local baseline cutoff.
-- Optional metadata filters only narrow already-authorized rows.
create or replace function public.qozon_match_chunks(
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
    where c.metadata @> filter
      and c.embedding operator(extensions.<=>) query_embedding <= 0.65
    order by c.embedding operator(extensions.<=>) query_embedding, c.id
    limit greatest(0, least(coalesce(match_count, 12), 12));
$$;

-- Keyword lane: caller supplies normalized search terms (including aim/purpose).
-- Full-text ranking is not BM25; calibrate fusion against the local gold cases.
create or replace function public.qozon_keyword_chunks(
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
    where length(query_text) between 1 and 2000
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
    to anon, authenticated;
grant execute on function public.qozon_keyword_chunks(text, integer, jsonb)
    to anon, authenticated;

