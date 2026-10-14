-- HISTORICAL owner/share checkpoint before the public Q&A migration.
-- Current acceptance: tests/database/phase4_public_access.sql.
-- Phase 4 database acceptance. Run as a database administrator with ON_ERROR_STOP.
-- Fictional fixtures and grants live in one transaction, always rolled back.
-- SET ROLE/JWT claims exercise database RLS; this does not test HTTP token validation.
begin;
set local statement_timeout = '30s';
insert into auth.users(id) values
 ('a4000000-0000-0000-0000-000000000001'),
 ('a4000000-0000-0000-0000-000000000002'),
 ('a4000000-0000-0000-0000-000000000003'),
 ('a4000000-0000-0000-0000-000000000004');
insert into public.qozon_documents(id,owner_id,title,storage_bucket,storage_object,active_revision,deleted) values
 ('d4000000-0000-0000-0000-000000000001','a4000000-0000-0000-0000-000000000001','Fictional orchid guide','phase4-test','owner.pdf',repeat('1',64),false),
 ('d4000000-0000-0000-0000-000000000002','a4000000-0000-0000-0000-000000000004','Fictional unrelated guide','phase4-test','other.pdf',repeat('1',64),false),
 ('d4000000-0000-0000-0000-000000000003','a4000000-0000-0000-0000-000000000001','Fictional deleted guide','phase4-test','deleted.pdf',repeat('1',64),true);
insert into public.qozon_document_access(document_id,user_id) values
 ('d4000000-0000-0000-0000-000000000001','a4000000-0000-0000-0000-000000000002'),
 ('d4000000-0000-0000-0000-000000000002','a4000000-0000-0000-0000-000000000004');
insert into public.qozon_chunks(document_id,revision,chunk_id,content,evidence_content,metadata,embedding)
 select 'd4000000-0000-0000-0000-000000000001',repeat('1',64),lpad(to_hex(n),64,'0'),
 'orchid training','Complete orchid training evidence.',
 '{"tag":"owner","cloud_document_id":"spoof","revision":"spoof","chunk_id":"spoof"}'::jsonb,
 array_prepend(1::real,array_fill(0::real,array[1535]))::extensions.vector
 from generate_series(1,14) n;
insert into public.qozon_chunks(document_id,revision,chunk_id,content,evidence_content,metadata,embedding) values
 ('d4000000-0000-0000-0000-000000000001',repeat('2',64),repeat('a',64),'orchid training','Complete orchid training evidence.','{"tag":"staged"}',array_prepend(1::real,array_fill(0::real,array[1535]))::extensions.vector),
 ('d4000000-0000-0000-0000-000000000002',repeat('1',64),repeat('b',64),'orchid training','Complete orchid training evidence.','{"tag":"foreign"}',array_prepend(1::real,array_fill(0::real,array[1535]))::extensions.vector),
 ('d4000000-0000-0000-0000-000000000003',repeat('1',64),repeat('c',64),'orchid training','Complete orchid training evidence.','{"tag":"deleted"}',array_prepend(1::real,array_fill(0::real,array[1535]))::extensions.vector);
set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"a4000000-0000-0000-0000-000000000001","role":"authenticated"}', true);
do $$ begin if not ((select count(*) from public.qozon_documents) = 1) then raise exception 'Phase 4 failed: owner_documents'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_chunks) = 14) then raise exception 'Phase 4 failed: owner_active_chunks'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_document_access) = 0) then raise exception 'Phase 4 failed: owner_own_grants'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_match_chunks(array_prepend(1::real,array_fill(0::real,array[1535]))::extensions.vector,999)) = 12) then raise exception 'Phase 4 failed: owner_vector_cap'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_keyword_chunks('orchid',999)) = 12) then raise exception 'Phase 4 failed: owner_keyword_cap'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_match_chunks(array_prepend(1::real,array_fill(0::real,array[1535]))::extensions.vector,12,'{"tag":"foreign"}')) = 0) then raise exception 'Phase 4 failed: owner_filter_cannot_grant'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_keyword_chunks('orchid',12,'{"tag":"staged"}')) = 0) then raise exception 'Phase 4 failed: owner_staged_hidden'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_match_chunks(array_prepend(1::real,array_fill(0::real,array[1535]))::extensions.vector,12,'{"tag":"deleted"}')) = 0) then raise exception 'Phase 4 failed: owner_deleted_hidden'; end if; end $$;
do $$ begin if not (not exists (select 1 from public.qozon_match_chunks(array_prepend(1::real,array_fill(0::real,array[1535]))::extensions.vector) where content <> 'Complete orchid training evidence.')) then raise exception 'Phase 4 failed: owner_checked_evidence'; end if; end $$;
do $$ begin if not (not exists (select 1 from public.qozon_match_chunks(array_prepend(1::real,array_fill(0::real,array[1535]))::extensions.vector) where metadata->>'cloud_document_id' = 'spoof' or metadata->>'revision' = 'spoof' or metadata->>'chunk_id' = 'spoof')) then raise exception 'Phase 4 failed: owner_authoritative_metadata'; end if; end $$;
do $$ begin begin insert into public.qozon_document_access(document_id,user_id) values ('d4000000-0000-0000-0000-000000000001','a4000000-0000-0000-0000-000000000003'); raise exception 'Phase 4 failed: owner_share_write_denied'; exception when insufficient_privilege then null; end; end $$;
do $$ begin begin update public.qozon_documents set deleted=true; raise exception 'Phase 4 failed: owner_document_write_denied'; exception when insufficient_privilege then null; end; end $$;
do $$ begin begin delete from public.qozon_chunks; raise exception 'Phase 4 failed: owner_chunk_write_denied'; exception when insufficient_privilege then null; end; end $$;
reset role;
set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"a4000000-0000-0000-0000-000000000002","role":"authenticated"}', true);
do $$ begin if not ((select count(*) from public.qozon_documents) = 1) then raise exception 'Phase 4 failed: shared_documents'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_chunks) = 14) then raise exception 'Phase 4 failed: shared_active_chunks'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_document_access) = 1) then raise exception 'Phase 4 failed: shared_own_grants'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_match_chunks(array_prepend(1::real,array_fill(0::real,array[1535]))::extensions.vector,999)) = 12) then raise exception 'Phase 4 failed: shared_vector_cap'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_keyword_chunks('orchid',999)) = 12) then raise exception 'Phase 4 failed: shared_keyword_cap'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_match_chunks(array_prepend(1::real,array_fill(0::real,array[1535]))::extensions.vector,12,'{"tag":"foreign"}')) = 0) then raise exception 'Phase 4 failed: shared_filter_cannot_grant'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_keyword_chunks('orchid',12,'{"tag":"staged"}')) = 0) then raise exception 'Phase 4 failed: shared_staged_hidden'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_match_chunks(array_prepend(1::real,array_fill(0::real,array[1535]))::extensions.vector,12,'{"tag":"deleted"}')) = 0) then raise exception 'Phase 4 failed: shared_deleted_hidden'; end if; end $$;
do $$ begin if not (not exists (select 1 from public.qozon_match_chunks(array_prepend(1::real,array_fill(0::real,array[1535]))::extensions.vector) where content <> 'Complete orchid training evidence.')) then raise exception 'Phase 4 failed: shared_checked_evidence'; end if; end $$;
do $$ begin if not (not exists (select 1 from public.qozon_match_chunks(array_prepend(1::real,array_fill(0::real,array[1535]))::extensions.vector) where metadata->>'cloud_document_id' = 'spoof' or metadata->>'revision' = 'spoof' or metadata->>'chunk_id' = 'spoof')) then raise exception 'Phase 4 failed: shared_authoritative_metadata'; end if; end $$;
do $$ begin begin insert into public.qozon_document_access(document_id,user_id) values ('d4000000-0000-0000-0000-000000000001','a4000000-0000-0000-0000-000000000003'); raise exception 'Phase 4 failed: shared_share_write_denied'; exception when insufficient_privilege then null; end; end $$;
do $$ begin begin update public.qozon_documents set deleted=true; raise exception 'Phase 4 failed: shared_document_write_denied'; exception when insufficient_privilege then null; end; end $$;
do $$ begin begin delete from public.qozon_chunks; raise exception 'Phase 4 failed: shared_chunk_write_denied'; exception when insufficient_privilege then null; end; end $$;
reset role;
set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"a4000000-0000-0000-0000-000000000003","role":"authenticated"}', true);
do $$ begin if not ((select count(*) from public.qozon_documents) = 0) then raise exception 'Phase 4 failed: unrelated_documents'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_chunks) = 0) then raise exception 'Phase 4 failed: unrelated_active_chunks'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_document_access) = 0) then raise exception 'Phase 4 failed: unrelated_own_grants'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_match_chunks(array_prepend(1::real,array_fill(0::real,array[1535]))::extensions.vector,999)) = 0) then raise exception 'Phase 4 failed: unrelated_vector_cap'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_keyword_chunks('orchid',999)) = 0) then raise exception 'Phase 4 failed: unrelated_keyword_cap'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_match_chunks(array_prepend(1::real,array_fill(0::real,array[1535]))::extensions.vector,12,'{"tag":"foreign"}')) = 0) then raise exception 'Phase 4 failed: unrelated_filter_cannot_grant'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_keyword_chunks('orchid',12,'{"tag":"staged"}')) = 0) then raise exception 'Phase 4 failed: unrelated_staged_hidden'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_match_chunks(array_prepend(1::real,array_fill(0::real,array[1535]))::extensions.vector,12,'{"tag":"deleted"}')) = 0) then raise exception 'Phase 4 failed: unrelated_deleted_hidden'; end if; end $$;
do $$ begin if not (not exists (select 1 from public.qozon_match_chunks(array_prepend(1::real,array_fill(0::real,array[1535]))::extensions.vector) where content <> 'Complete orchid training evidence.')) then raise exception 'Phase 4 failed: unrelated_checked_evidence'; end if; end $$;
do $$ begin if not (not exists (select 1 from public.qozon_match_chunks(array_prepend(1::real,array_fill(0::real,array[1535]))::extensions.vector) where metadata->>'cloud_document_id' = 'spoof' or metadata->>'revision' = 'spoof' or metadata->>'chunk_id' = 'spoof')) then raise exception 'Phase 4 failed: unrelated_authoritative_metadata'; end if; end $$;
do $$ begin begin insert into public.qozon_document_access(document_id,user_id) values ('d4000000-0000-0000-0000-000000000001','a4000000-0000-0000-0000-000000000003'); raise exception 'Phase 4 failed: unrelated_share_write_denied'; exception when insufficient_privilege then null; end; end $$;
do $$ begin begin update public.qozon_documents set deleted=true; raise exception 'Phase 4 failed: unrelated_document_write_denied'; exception when insufficient_privilege then null; end; end $$;
do $$ begin begin delete from public.qozon_chunks; raise exception 'Phase 4 failed: unrelated_chunk_write_denied'; exception when insufficient_privilege then null; end; end $$;
reset role;
set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"a4000000-0000-0000-0000-000000000004","role":"authenticated"}', true);
do $$ begin if not ((select count(*) from public.qozon_documents) = 1) then raise exception 'Phase 4 failed: other_owner_documents'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_chunks) = 1) then raise exception 'Phase 4 failed: other_owner_active_chunks'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_document_access) = 1) then raise exception 'Phase 4 failed: other_owner_own_grants'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_match_chunks(array_prepend(1::real,array_fill(0::real,array[1535]))::extensions.vector,999)) = 1) then raise exception 'Phase 4 failed: other_owner_vector_cap'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_keyword_chunks('orchid',999)) = 1) then raise exception 'Phase 4 failed: other_owner_keyword_cap'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_match_chunks(array_prepend(1::real,array_fill(0::real,array[1535]))::extensions.vector,12,'{"tag":"foreign"}')) = 1) then raise exception 'Phase 4 failed: other_owner_filter_cannot_grant'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_keyword_chunks('orchid',12,'{"tag":"staged"}')) = 0) then raise exception 'Phase 4 failed: other_owner_staged_hidden'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_match_chunks(array_prepend(1::real,array_fill(0::real,array[1535]))::extensions.vector,12,'{"tag":"deleted"}')) = 0) then raise exception 'Phase 4 failed: other_owner_deleted_hidden'; end if; end $$;
do $$ begin if not (not exists (select 1 from public.qozon_match_chunks(array_prepend(1::real,array_fill(0::real,array[1535]))::extensions.vector) where content <> 'Complete orchid training evidence.')) then raise exception 'Phase 4 failed: other_owner_checked_evidence'; end if; end $$;
do $$ begin if not (not exists (select 1 from public.qozon_match_chunks(array_prepend(1::real,array_fill(0::real,array[1535]))::extensions.vector) where metadata->>'cloud_document_id' = 'spoof' or metadata->>'revision' = 'spoof' or metadata->>'chunk_id' = 'spoof')) then raise exception 'Phase 4 failed: other_owner_authoritative_metadata'; end if; end $$;
do $$ begin begin insert into public.qozon_document_access(document_id,user_id) values ('d4000000-0000-0000-0000-000000000001','a4000000-0000-0000-0000-000000000003'); raise exception 'Phase 4 failed: other_owner_share_write_denied'; exception when insufficient_privilege then null; end; end $$;
do $$ begin begin update public.qozon_documents set deleted=true; raise exception 'Phase 4 failed: other_owner_document_write_denied'; exception when insufficient_privilege then null; end; end $$;
do $$ begin begin delete from public.qozon_chunks; raise exception 'Phase 4 failed: other_owner_chunk_write_denied'; exception when insufficient_privilege then null; end; end $$;
reset role;
set local role authenticated;
select set_config('request.jwt.claims','{}',true);
do $$ begin if not ((select count(*) from public.qozon_documents) = 0) then raise exception 'Phase 4 failed: missing_identity_qozon_documents'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_document_access) = 0) then raise exception 'Phase 4 failed: missing_identity_qozon_document_access'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_chunks) = 0) then raise exception 'Phase 4 failed: missing_identity_qozon_chunks'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_match_chunks(array_prepend(1::real,array_fill(0::real,array[1535]))::extensions.vector)) = 0) then raise exception 'Phase 4 failed: missing_identity_vector'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_keyword_chunks('orchid')) = 0) then raise exception 'Phase 4 failed: missing_identity_keyword'; end if; end $$;
reset role;
set local role anon;
do $$ begin begin perform 1 from public.qozon_documents; raise exception 'Phase 4 failed: anonymous_qozon_documents'; exception when insufficient_privilege then null; end; end $$;
do $$ begin begin perform 1 from public.qozon_document_access; raise exception 'Phase 4 failed: anonymous_qozon_document_access'; exception when insufficient_privilege then null; end; end $$;
do $$ begin begin perform 1 from public.qozon_chunks; raise exception 'Phase 4 failed: anonymous_qozon_chunks'; exception when insufficient_privilege then null; end; end $$;
do $$ begin begin perform 1 from public.qozon_match_chunks(array_prepend(1::real,array_fill(0::real,array[1535]))::extensions.vector); raise exception 'Phase 4 failed: anonymous_vector'; exception when insufficient_privilege then null; end; end $$;
do $$ begin begin perform 1 from public.qozon_keyword_chunks('orchid'); raise exception 'Phase 4 failed: anonymous_keyword'; exception when insufficient_privilege then null; end; end $$;
reset role;
delete from public.qozon_document_access where document_id='d4000000-0000-0000-0000-000000000001';
set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"a4000000-0000-0000-0000-000000000002","role":"authenticated"}', true);
do $$ begin if not ((select count(*) from public.qozon_documents) = 0) then raise exception 'Phase 4 failed: revoked_share_documents'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_match_chunks(array_prepend(1::real,array_fill(0::real,array[1535]))::extensions.vector)) = 0) then raise exception 'Phase 4 failed: revoked_share_vector'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_keyword_chunks('orchid')) = 0) then raise exception 'Phase 4 failed: revoked_share_keyword'; end if; end $$;
reset role;
update public.qozon_documents set active_revision=repeat('2',64) where id='d4000000-0000-0000-0000-000000000001';
set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"a4000000-0000-0000-0000-000000000001","role":"authenticated"}', true);
do $$ begin if not ((select count(*) from public.qozon_chunks) = 1 and not exists(select 1 from public.qozon_chunks where revision <> repeat('2',64))) then raise exception 'Phase 4 failed: activation_only_new_revision'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_match_chunks(array_prepend(1::real,array_fill(0::real,array[1535]))::extensions.vector)) = 1) then raise exception 'Phase 4 failed: activation_vector'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_keyword_chunks('orchid')) = 1) then raise exception 'Phase 4 failed: activation_keyword'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_match_chunks(array_prepend(1::real,array_fill(0::real,array[1535]))::extensions.vector,-1)) = 0) then raise exception 'Phase 4 failed: negative_limit'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_keyword_chunks('')) = 0) then raise exception 'Phase 4 failed: blank_keyword'; end if; end $$;
reset role;
update public.qozon_documents set deleted=true where id='d4000000-0000-0000-0000-000000000001';
set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"a4000000-0000-0000-0000-000000000001","role":"authenticated"}', true);
do $$ begin if not ((select count(*) from public.qozon_documents) = 0) then raise exception 'Phase 4 failed: soft_delete_documents'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_match_chunks(array_prepend(1::real,array_fill(0::real,array[1535]))::extensions.vector)) = 0) then raise exception 'Phase 4 failed: soft_delete_vector'; end if; end $$;
do $$ begin if not ((select count(*) from public.qozon_keyword_chunks('orchid')) = 0) then raise exception 'Phase 4 failed: soft_delete_keyword'; end if; end $$;
reset role;
rollback;
select jsonb_build_object('status','passed','checks',73,'fixtures','rolled back','scope','database roles and JWT claims; HTTP authentication not tested') as phase4_access_result;
