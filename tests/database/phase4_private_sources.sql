-- Phase 4 private sources: direct user Storage reads are closed; the API proxy authorizes via document RLS.
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
 ('d4000000-0000-0000-0000-000000000001','a4000000-0000-0000-0000-000000000001','Fictional orchid guide','pdf_rag','phase4-rls-fixture/owner.pdf',repeat('1',64),false),
 ('d4000000-0000-0000-0000-000000000002','a4000000-0000-0000-0000-000000000004','Fictional unrelated guide','pdf_rag','phase4-rls-fixture/other.pdf',repeat('1',64),false),
 ('d4000000-0000-0000-0000-000000000003','a4000000-0000-0000-0000-000000000001','Fictional deleted guide','pdf_rag','phase4-rls-fixture/deleted.pdf',repeat('1',64),true);
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
update public.qozon_chunks set metadata = jsonb_build_object('private_sources',jsonb_build_object(
'image',jsonb_build_object('bucket','pdf_rag','object','phase4-rls-fixture/picture.png'),
'structured',jsonb_build_object('bucket','pdf_rag','object','phase4-rls-fixture/table.json')))
where document_id='d4000000-0000-0000-0000-000000000001' and revision=repeat('1',64);
update public.qozon_chunks set metadata = '{"private_sources":{"image":{"bucket":"pdf_rag","object":"phase4-rls-fixture/staged.png"}}}'
where document_id='d4000000-0000-0000-0000-000000000001' and revision=repeat('2',64);
insert into storage.objects(bucket_id,name) values
('pdf_rag','phase4-rls-fixture/owner.pdf'),('pdf_rag','phase4-rls-fixture/other.pdf'),
('pdf_rag','phase4-rls-fixture/deleted.pdf'),('pdf_rag','phase4-rls-fixture/picture.png'),
('pdf_rag','phase4-rls-fixture/table.json'),('pdf_rag','phase4-rls-fixture/staged.png'),
('pdf_rag','phase4-rls-fixture/unmapped.pdf');
set local role authenticated;
select set_config('request.jwt.claims','{"sub":"a4000000-0000-0000-0000-000000000001","role":"authenticated"}',true);
do $$ begin if not ((select count(*) from storage.objects where name like 'phase4-rls-fixture/%') = 0) then raise exception 'Private source failed: owner_mapped_objects'; end if; end $$;
do $$ begin if not (not exists(select 1 from storage.objects where name='phase4-rls-fixture/staged.png')) then raise exception 'Private source failed: owner_no_staged_source'; end if; end $$;
do $$ begin if not (not exists(select 1 from storage.objects where name='phase4-rls-fixture/deleted.pdf')) then raise exception 'Private source failed: owner_no_deleted_source'; end if; end $$;
do $$ begin if not (not exists(select 1 from storage.objects where name='phase4-rls-fixture/unmapped.pdf')) then raise exception 'Private source failed: owner_no_unmapped_source'; end if; end $$;
reset role;
set local role authenticated;
select set_config('request.jwt.claims','{"sub":"a4000000-0000-0000-0000-000000000002","role":"authenticated"}',true);
do $$ begin if not ((select count(*) from storage.objects where name like 'phase4-rls-fixture/%') = 0) then raise exception 'Private source failed: shared_mapped_objects'; end if; end $$;
do $$ begin if not (not exists(select 1 from storage.objects where name='phase4-rls-fixture/staged.png')) then raise exception 'Private source failed: shared_no_staged_source'; end if; end $$;
do $$ begin if not (not exists(select 1 from storage.objects where name='phase4-rls-fixture/deleted.pdf')) then raise exception 'Private source failed: shared_no_deleted_source'; end if; end $$;
do $$ begin if not (not exists(select 1 from storage.objects where name='phase4-rls-fixture/unmapped.pdf')) then raise exception 'Private source failed: shared_no_unmapped_source'; end if; end $$;
reset role;
set local role authenticated;
select set_config('request.jwt.claims','{"sub":"a4000000-0000-0000-0000-000000000003","role":"authenticated"}',true);
do $$ begin if not ((select count(*) from storage.objects where name like 'phase4-rls-fixture/%') = 0) then raise exception 'Private source failed: unrelated_mapped_objects'; end if; end $$;
do $$ begin if not (not exists(select 1 from storage.objects where name='phase4-rls-fixture/staged.png')) then raise exception 'Private source failed: unrelated_no_staged_source'; end if; end $$;
do $$ begin if not (not exists(select 1 from storage.objects where name='phase4-rls-fixture/deleted.pdf')) then raise exception 'Private source failed: unrelated_no_deleted_source'; end if; end $$;
do $$ begin if not (not exists(select 1 from storage.objects where name='phase4-rls-fixture/unmapped.pdf')) then raise exception 'Private source failed: unrelated_no_unmapped_source'; end if; end $$;
reset role;
set local role authenticated;
select set_config('request.jwt.claims','{"sub":"a4000000-0000-0000-0000-000000000004","role":"authenticated"}',true);
do $$ begin if not ((select count(*) from storage.objects where name like 'phase4-rls-fixture/%') = 0) then raise exception 'Private source failed: other_owner_mapped_objects'; end if; end $$;
do $$ begin if not (not exists(select 1 from storage.objects where name='phase4-rls-fixture/staged.png')) then raise exception 'Private source failed: other_owner_no_staged_source'; end if; end $$;
do $$ begin if not (not exists(select 1 from storage.objects where name='phase4-rls-fixture/deleted.pdf')) then raise exception 'Private source failed: other_owner_no_deleted_source'; end if; end $$;
do $$ begin if not (not exists(select 1 from storage.objects where name='phase4-rls-fixture/unmapped.pdf')) then raise exception 'Private source failed: other_owner_no_unmapped_source'; end if; end $$;
reset role;
set local role authenticated;
select set_config('request.jwt.claims','{}',true);
do $$ begin if not (not exists(select 1 from storage.objects where name like 'phase4-rls-fixture/%')) then raise exception 'Private source failed: absent_identity'; end if; end $$;
reset role;
set local role anon;
do $$ begin if not (not exists(select 1 from storage.objects where name like 'phase4-rls-fixture/%')) then raise exception 'Private source failed: anonymous'; end if; end $$;
reset role;
delete from public.qozon_document_access where document_id='d4000000-0000-0000-0000-000000000001';
set local role authenticated;
select set_config('request.jwt.claims','{"sub":"a4000000-0000-0000-0000-000000000002","role":"authenticated"}',true);
do $$ begin if not (not exists(select 1 from storage.objects where name like 'phase4-rls-fixture/%')) then raise exception 'Private source failed: revoked_shared_source'; end if; end $$;
reset role;
update public.qozon_documents set active_revision=repeat('2',64) where id='d4000000-0000-0000-0000-000000000001';
set local role authenticated;
select set_config('request.jwt.claims','{"sub":"a4000000-0000-0000-0000-000000000001","role":"authenticated"}',true);
do $$ begin if not (not exists(select 1 from storage.objects where name='phase4-rls-fixture/staged.png')) then raise exception 'Private source failed: activation_does_not_expose_raw_source'; end if; end $$;
do $$ begin if not (not exists(select 1 from storage.objects where name in ('phase4-rls-fixture/picture.png','phase4-rls-fixture/table.json'))) then raise exception 'Private source failed: activation_hides_previous_assets'; end if; end $$;
reset role;
update public.qozon_documents set deleted=true where id='d4000000-0000-0000-0000-000000000001';
set local role authenticated;
select set_config('request.jwt.claims','{"sub":"a4000000-0000-0000-0000-000000000001","role":"authenticated"}',true);
do $$ begin if not (not exists(select 1 from storage.objects where name like 'phase4-rls-fixture/%')) then raise exception 'Private source failed: soft_deletion_hides_sources'; end if; end $$;
reset role;
rollback;
select jsonb_build_object('status','passed','checks',22,'fixtures','rolled back','scope','Storage metadata RLS; real Storage HTTP verification is separate') as private_source_access_result;
