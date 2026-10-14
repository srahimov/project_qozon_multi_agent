-- Current public Q&A acceptance. Fictional fixtures roll back.
begin;
set local statement_timeout='30s';
insert into public.qozon_documents(id,title,storage_bucket,storage_object,active_revision,public_read,deleted) values
('d5000000-0000-0000-0000-000000000001','Fictional reviewed guide','pdf_rag','public-fixture/reviewed.pdf',repeat('1',64),true,false),
('d5000000-0000-0000-0000-000000000002','Fictional private guide','pdf_rag','public-fixture/private.pdf',repeat('1',64),false,false),
('d5000000-0000-0000-0000-000000000003','Fictional deleted guide','pdf_rag','public-fixture/deleted.pdf',repeat('1',64),true,true),
('d5000000-0000-0000-0000-000000000004','Fictional pending guide','pdf_rag','public-fixture/pending.pdf',null,true,false);
insert into public.qozon_chunks(document_id,revision,chunk_id,content,metadata,embedding)
 select 'd5000000-0000-0000-0000-000000000001',repeat('1',64),lpad(to_hex(n),64,'0'),
 'Fictional orchid evidence.','{"scope":"reviewed"}',array_prepend(1::real,array_fill(0::real,array[1535]))::extensions.vector
 from generate_series(1,14) n;
insert into public.qozon_chunks(document_id,revision,chunk_id,content,metadata,embedding) values
('d5000000-0000-0000-0000-000000000001',repeat('2',64),repeat('a',64),'Fictional orchid staged.','{"scope":"staged"}',array_prepend(1::real,array_fill(0::real,array[1535]))::extensions.vector),
('d5000000-0000-0000-0000-000000000002',repeat('1',64),repeat('b',64),'Fictional orchid private.','{"scope":"private"}',array_prepend(1::real,array_fill(0::real,array[1535]))::extensions.vector),
('d5000000-0000-0000-0000-000000000003',repeat('1',64),repeat('c',64),'Fictional orchid deleted.','{"scope":"deleted"}',array_prepend(1::real,array_fill(0::real,array[1535]))::extensions.vector),
('d5000000-0000-0000-0000-000000000004',repeat('1',64),repeat('d',64),'Fictional orchid pending.','{"scope":"pending"}',array_prepend(1::real,array_fill(0::real,array[1535]))::extensions.vector);
set local role anon;
select set_config('request.jwt.claims','{}',true);
do $$ begin if not ((select count(id) from public.qozon_documents where id::text like 'd5000000-%')=1) then raise exception 'Public access failed: anon_only_reviewed_document'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_chunks where document_id::text like 'd5000000-%')=14) then raise exception 'Public access failed: anon_only_active_chunks'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_match_chunks(array_prepend(1::real,array_fill(0::real,array[1535]))::extensions.vector,999))=12) then raise exception 'Public access failed: anon_bounded_vector'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_keyword_chunks('orchid',999))=12) then raise exception 'Public access failed: anon_bounded_keyword'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_match_chunks(array_prepend(1::real,array_fill(0::real,array[1535]))::extensions.vector,12,'{"scope":"private"}'))=0) then raise exception 'Public access failed: anon_filter_private_does_not_grant'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_match_chunks(array_prepend(1::real,array_fill(0::real,array[1535]))::extensions.vector,12,'{"scope":"staged"}'))=0) then raise exception 'Public access failed: anon_filter_staged_does_not_grant'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_match_chunks(array_prepend(1::real,array_fill(0::real,array[1535]))::extensions.vector,12,'{"scope":"pending"}'))=0) then raise exception 'Public access failed: anon_filter_pending_does_not_grant'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_match_chunks(array_prepend(1::real,array_fill(0::real,array[1535]))::extensions.vector,12,'{"scope":"deleted"}'))=0) then raise exception 'Public access failed: anon_filter_deleted_does_not_grant'; end if; end $$;
do $$ begin begin update public.qozon_documents set public_read=true; raise exception 'Public access failed: anon_doc_write_denied'; exception when insufficient_privilege then null; end; end $$;
do $$ begin begin delete from public.qozon_chunks; raise exception 'Public access failed: anon_chunk_write_denied'; exception when insufficient_privilege then null; end; end $$;
do $$ begin begin delete from public.qozon_document_access; raise exception 'Public access failed: anon_grant_write_denied'; exception when insufficient_privilege then null; end; end $$;
reset role;
set local role authenticated;
select set_config('request.jwt.claims','{}',true);
do $$ begin if not ((select count(id) from public.qozon_documents where id::text like 'd5000000-%')=1) then raise exception 'Public access failed: authenticated_only_reviewed_document'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_chunks where document_id::text like 'd5000000-%')=14) then raise exception 'Public access failed: authenticated_only_active_chunks'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_match_chunks(array_prepend(1::real,array_fill(0::real,array[1535]))::extensions.vector,999))=12) then raise exception 'Public access failed: authenticated_bounded_vector'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_keyword_chunks('orchid',999))=12) then raise exception 'Public access failed: authenticated_bounded_keyword'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_match_chunks(array_prepend(1::real,array_fill(0::real,array[1535]))::extensions.vector,12,'{"scope":"private"}'))=0) then raise exception 'Public access failed: authenticated_filter_private_does_not_grant'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_match_chunks(array_prepend(1::real,array_fill(0::real,array[1535]))::extensions.vector,12,'{"scope":"staged"}'))=0) then raise exception 'Public access failed: authenticated_filter_staged_does_not_grant'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_match_chunks(array_prepend(1::real,array_fill(0::real,array[1535]))::extensions.vector,12,'{"scope":"pending"}'))=0) then raise exception 'Public access failed: authenticated_filter_pending_does_not_grant'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_match_chunks(array_prepend(1::real,array_fill(0::real,array[1535]))::extensions.vector,12,'{"scope":"deleted"}'))=0) then raise exception 'Public access failed: authenticated_filter_deleted_does_not_grant'; end if; end $$;
do $$ begin begin update public.qozon_documents set public_read=true; raise exception 'Public access failed: authenticated_doc_write_denied'; exception when insufficient_privilege then null; end; end $$;
do $$ begin begin delete from public.qozon_chunks; raise exception 'Public access failed: authenticated_chunk_write_denied'; exception when insufficient_privilege then null; end; end $$;
do $$ begin begin delete from public.qozon_document_access; raise exception 'Public access failed: authenticated_grant_write_denied'; exception when insufficient_privilege then null; end; end $$;
reset role;
set local role anon;
do $$ begin begin perform storage_bucket,storage_object from public.qozon_documents; raise exception 'Public access failed: anon_private_pdf_location_denied'; exception when insufficient_privilege then null; end; end $$;
do $$ begin begin perform owner_id from public.qozon_documents; raise exception 'Public access failed: anon_owner_ids_denied'; exception when insufficient_privilege then null; end; end $$;
do $$ begin begin perform 1 from public.qozon_document_access; raise exception 'Public access failed: anon_shares_denied'; exception when insufficient_privilege then null; end; end $$;
reset role;
update public.qozon_documents set public_read=false where id='d5000000-0000-0000-0000-000000000001';
set local role anon;
do $$ begin if not ((select count(id) from public.qozon_documents where id::text like 'd5000000-%')=0) then raise exception 'Public access failed: withdrawn_document_hidden'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_match_chunks(array_prepend(1::real,array_fill(0::real,array[1535]))::extensions.vector))=0) then raise exception 'Public access failed: withdrawn_vector_hidden'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_keyword_chunks('orchid'))=0) then raise exception 'Public access failed: withdrawn_keyword_hidden'; end if; end $$;
reset role;
update public.qozon_documents set public_read=true,active_revision=repeat('2',64) where id='d5000000-0000-0000-0000-000000000001';
set local role anon;
do $$ begin if not ((select count(*) from public.qozon_chunks where document_id::text like 'd5000000-%')=1) then raise exception 'Public access failed: activation_only_new_revision'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_match_chunks(array_prepend(1::real,array_fill(0::real,array[1535]))::extensions.vector))=1) then raise exception 'Public access failed: activation_vector'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_keyword_chunks('orchid'))=1) then raise exception 'Public access failed: activation_keyword'; end if; end $$;
reset role;
rollback;
select jsonb_build_object('status','passed','checks',31,'fixtures','rolled back','scope','opt-in public RLS, no Auth user needed') as public_qa_access_result;
