-- Private reads use the same document/chunk RLS as retrieval.
-- Scope is the existing private pdf_rag bucket; no bucket or object is changed.
-- Public legacy crops remain public. Readers gain no upload/edit/delete rights.
create policy qozon_read_private_sources on storage.objects
    for select to authenticated
    using (
        bucket_id = 'pdf_rag'
        and (select auth.uid()) is not null
        and (
            exists (
                select 1 from public.qozon_documents d
                where d.storage_bucket = storage.objects.bucket_id
                  and d.storage_object = storage.objects.name
            )
            or exists (
                select 1 from public.qozon_chunks c
                where (
                    c.metadata #>> '{private_sources,image,bucket}' = storage.objects.bucket_id
                    and c.metadata #>> '{private_sources,image,object}' = storage.objects.name
                ) or (
                    c.metadata #>> '{private_sources,structured,bucket}' = storage.objects.bucket_id
                    and c.metadata #>> '{private_sources,structured,object}' = storage.objects.name
                )
                -- Chunks RLS requires a visible document and its active revision.
            )
        )
    );
