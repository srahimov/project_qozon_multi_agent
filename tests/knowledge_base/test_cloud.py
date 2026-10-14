"""Cloud retrieval/publication boundaries using fictional rows and fixed vectors."""
import asyncio
import copy
import hashlib
import json
from uuid import UUID

import httpx
from langchain_core.embeddings import Embeddings
import pytest

from qozon_langchain.core.config import Settings
from qozon_langchain.knowledge_base.cloud import CloudPDFRetriever, text_hash
from qozon_langchain.knowledge_base.cloud_import import ImportError, import_reviewed, vector32
from qozon_langchain.knowledge_base.pdf.chunking import digest
from qozon_langchain.knowledge_base.pdf.retrieval import RetrievalError
from qozon_langchain.services.question_service import QuestionServiceError, answer_question
from qozon_langchain.security.policies import training_policy

DOC = 'd5000000-0000-0000-0000-000000000001'
CHUNK, ORIGINAL, REVISION = 'a'*64, 'b'*64, 'c'*64
TEXT = 'The fictional garden contains four trees.'
META = dict(document_id=ORIGINAL, source='fictional.pdf', page_numbers=[12], content_type='text',
            parent_asset_id='', source_sha256='', factually_verified=False, evidence_sha256=text_hash(TEXT))
ROW = dict(content=TEXT, metadata=dict(META, chunk_id=CHUNK, cloud_document_id=DOC, revision=REVISION), similarity=1.0)


class FixedEmbeddings(Embeddings):
    def __init__(self): self.calls=[]
    def embed_documents(self, texts): pytest.fail('Corpus embeddings must never be generated')
    def embed_query(self, text):
        self.calls.append(text)
        return [1.0] + [0.0]*1535


def fixture(tmp_path, handler=None):
    settings = Settings(_env_file=None, supabase_url='https://synthetic.supabase.co',
        supabase_publishable_key='sb_publishable_synthetic', supabase_secret_key='sb_secret_synthetic',
        supabase_storage_bucket='private-pdfs', supabase_assets_bucket='approved-assets',
        rag_publication_manifest=tmp_path/'publication.json', rag_backend='supabase')
    requests=[]
    def respond(req):
        requests.append(req)
        if handler:
            value=handler(req)
            if value is not None: return value
        if req.url.path.endswith('qozon_match_chunks'):
            return httpx.Response(200, json=[ROW])
        if req.url.path.endswith('qozon_keyword_chunks'):
            return httpx.Response(200, json=[dict(ROW, rank=1)])
        if req.url.path.endswith('qozon_documents'):
            return httpx.Response(200, json=[dict(id=DOC, title='Fictional book', active_revision=REVISION)])
        if req.url.path.endswith('qozon_chunks'):
            return httpx.Response(200, json=[dict(chunk_id=CHUNK, revision=REVISION, content=TEXT,
                                                 evidence_content=TEXT, metadata=META)])
        pytest.fail('No original-PDF, Auth or unexpected request')
    embeddings=FixedEmbeddings()
    return CloudPDFRetriever(settings=settings, embeddings=embeddings, transport=httpx.MockTransport(respond)), requests


def test_real_langchain_interface_and_evidence_preserve_contract(tmp_path):
    retriever,requests=fixture(tmp_path)
    docs=asyncio.run(retriever.ainvoke('How many trees are in the fictional garden?'))
    assert docs[0].page_content==TEXT
    evidence=asyncio.run(retriever.retrieve('How many trees are in the fictional garden?'))
    assert len(evidence)==1 and evidence[0].page_numbers==(12,) and evidence[0].text==TEXT
    assert evidence[0].document_id==ORIGINAL and evidence[0].cloud_document_id==DOC
    assert all(r.headers['apikey']=='sb_publishable_synthetic' and 'authorization' not in r.headers for r in requests)
    assert not any('/storage/' in r.url.path for r in requests)
    rpc=[json.loads(r.content) for r in requests if '/rpc/' in r.url.path]
    assert all(r['match_count']==12 and r['filter']=={} for r in rpc)


@pytest.mark.parametrize('mutate',[
    lambda r:r.update(content='Altered source.'),
    lambda r:r['metadata'].update(storage_object='private.pdf'),
    lambda r:r['metadata'].update(source='/private/path/book.pdf'),
    lambda r:r['metadata'].update(page_numbers=[0]),
    lambda r:r['metadata'].update(document_id='bad'),
    lambda r:r['metadata'].update(revision='bad'),
    lambda r:r['metadata'].update(cloud_document_id='bad'),
    lambda r:r.update(similarity=float('nan')),
    lambda r:r.update(similarity=2),
    lambda r:r['metadata'].update(parent_asset_id='d'*64,content_type='image_description'),
])
def test_malformed_changed_or_unapproved_hits_are_withheld(tmp_path, mutate):
    def handler(req):
        if req.url.path.endswith('qozon_match_chunks'):
            row=copy.deepcopy(ROW); mutate(row)
            return httpx.Response(200,json=[row])
    retriever,_=fixture(tmp_path,handler)
    with pytest.raises(RetrievalError): asyncio.run(retriever.retrieve('fictional garden'))


@pytest.mark.parametrize('kind',['hidden','changed_revision','changed_text','changed_metadata','removed_chunk'])
def test_final_read_withholds_withdrawn_changed_or_deleted_evidence(tmp_path,kind):
    retriever,_=fixture(tmp_path)
    evidence=asyncio.run(retriever.retrieve('fictional garden'))
    def handler(req):
        if req.url.path.endswith('qozon_documents'):
            return httpx.Response(200,json=[] if kind=='hidden' else [dict(id=DOC,active_revision='d'*64 if kind=='changed_revision' else REVISION)])
        if req.url.path.endswith('qozon_chunks'):
            row=dict(chunk_id=CHUNK, revision=REVISION, content=TEXT,evidence_content=TEXT,metadata=copy.deepcopy(META))
            if kind=='changed_text':row['evidence_content']='Other text.'
            if kind=='changed_metadata':row['metadata']['page_numbers']=[13]
            return httpx.Response(200,json=[] if kind=='removed_chunk' else [row])
    retriever.transport=httpx.MockTransport(handler)
    with pytest.raises(Exception): asyncio.run(retriever.validate_evidence(evidence))


def test_activation_between_rpc_calls_cannot_mix_revisions(tmp_path):
    def handler(req):
        if req.url.path.endswith('qozon_keyword_chunks'):
            row=copy.deepcopy(ROW);row['metadata']['revision']='d'*64
            return httpx.Response(200,json=[row])
    retriever,_=fixture(tmp_path,handler)
    with pytest.raises(RetrievalError): asyncio.run(retriever.retrieve('fictional garden'))


@pytest.mark.parametrize('status',[401,403,429,500,302])
def test_safe_remote_failures_no_privileged_fallback(tmp_path,status):
    retriever,requests=fixture(tmp_path,lambda req:httpx.Response(status,text='private upstream error'))
    with pytest.raises(RetrievalError,match='retrieval_unavailable'):
        asyncio.run(retriever.retrieve('fictional garden'))
    assert all(r.headers['apikey']=='sb_publishable_synthetic' for r in requests)


def test_question_gate_prevents_cloud_calls_and_final_check_withholds_buffered_answer(tmp_path):
    retriever,requests=fixture(tmp_path)
    class Model:
        async def generate_grounded_answer(self, question,evidence):
            retriever.transport=httpx.MockTransport(lambda r:httpx.Response(200,json=[]))
            return TEXT+' [S1]'
    with pytest.raises(QuestionServiceError):
        asyncio.run(answer_question('password=fictional-secret-value',model=Model(),policy=training_policy(),retriever=retriever))
    assert not requests and not retriever.embeddings.calls
    with pytest.raises(QuestionServiceError) as caught:
        asyncio.run(answer_question('How many trees?',model=Model(),policy=training_policy(),retriever=retriever))
    assert caught.value.code=='source_access_changed'


def test_reviewed_image_bytes_are_hash_checked_and_only_one_is_loaded(tmp_path):
    image=b'\x89PNG\r\n\x1a\nfictional image';sha=hashlib.sha256(image).hexdigest();asset='e'*64;fp='f'*64
    def handler(req):
        if '/rpc/' in req.url.path:
            row=copy.deepcopy(ROW);row['metadata'].update(parent_asset_id=asset,source_sha256=fp,content_type='image_description')
            return httpx.Response(200,json=[row])
        if '/storage/v1/object/public/approved-assets/' in req.url.path:return httpx.Response(200,content=image)
        if req.url.path.endswith('qozon_chunks'):
            meta=dict(META,parent_asset_id=asset,source_sha256=fp,content_type='image_description')
            return httpx.Response(200,json=[dict(chunk_id=CHUNK,revision=REVISION,content=TEXT,evidence_content=TEXT,metadata=meta)])
    retriever,requests=fixture(tmp_path,handler)
    retriever.settings.rag_publication_manifest.write_text(json.dumps(dict(project_url=retriever.settings.supabase_url,
        bucket='approved-assets',assets={asset:dict(document_id=ORIGINAL,source_sha256=fp,files=[
            dict(role='url',key=f'{ORIGINAL}/{asset}/{sha}.png',verified_public=True)])})))
    result=asyncio.run(retriever.retrieve('fictional garden'))
    assert result[0].image==image and result[0].url.endswith(sha+'.png')
    assert len([r for r in requests if '/storage/' in r.url.path])==1
    retriever.transport=httpx.MockTransport(lambda req:httpx.Response(200,content=b'altered') if '/storage/' in req.url.path else handler(req) or httpx.Response(200,json=[]))
    with pytest.raises(RetrievalError):asyncio.run(retriever.retrieve('fictional garden'))


def test_oversized_response_and_invalid_vectors_are_withheld(tmp_path):
    retriever,_=fixture(tmp_path,lambda r:httpx.Response(200,content=b' '* (1024*1024+1)))
    with pytest.raises(RetrievalError):asyncio.run(retriever.retrieve('garden'))
    with pytest.raises(ImportError):vector32([0.0]*1536)
    with pytest.raises(ImportError):vector32([1.0])


@pytest.mark.parametrize('failure',[None,'readback','concurrent','public_bucket'])
def test_import_stages_immutably_verifies_before_atomic_activation(tmp_path,failure):
    retriever,_=fixture(tmp_path);s=retriever.settings
    rows=[dict(chunk_id=CHUNK,revision=REVISION,content=TEXT,evidence_content=TEXT,metadata=META,embedding=[1.0]+[0.0]*1535)]
    report=dict(payload_sha256=digest(rows),chunks=1,revision=REVISION)
    requests=[]
    def respond(req):
        requests.append(req)
        if req.url.path.startswith('/storage/v1/bucket/'):
            return httpx.Response(200,json={'public':failure=='public_bucket'})
        if req.url.path.endswith('qozon_documents'):
            if req.method=='PATCH':return httpx.Response(200,json=[] if failure=='concurrent' else [dict(id=DOC)])
            return httpx.Response(200,json=[dict(id=DOC,active_revision=None,deleted=False,public_read=False)])
        if req.url.path.endswith('qozon_chunks'):
            if req.method=='GET' and req.url.params.get('select')=='chunk_id':return httpx.Response(200,json=[])
            if req.method=='POST':
                assert req.headers['Prefer']=='resolution=ignore-duplicates,return=minimal'
                return httpx.Response(201)
            return httpx.Response(200,json=[] if failure=='readback' else rows)
        pytest.fail('No PDF download or upload allowed')
    with httpx.Client(base_url=s.supabase_url,headers={'apikey':'sb_secret_synthetic'},transport=httpx.MockTransport(respond)) as client:
        if failure:
            with pytest.raises(ImportError):import_reviewed(s,rows,report,client=client,storage_object='fictional.pdf')
        else:
            result=import_reviewed(s,rows,report,client=client,storage_object='fictional.pdf')
            assert result['verified_chunks']==1
    patches=[r for r in requests if r.method=='PATCH']
    if failure in {'readback','public_bucket'}:assert not patches
    else:
        assert len(patches)==1 and patches[0].url.params['active_revision']=='is.null'
        assert patches[0].url.params['public_read']=='eq.false'
        assert json.loads(patches[0].content)==dict(active_revision=REVISION,public_read=True)


def test_modified_reviewed_payload_is_rejected_before_network(tmp_path):
    retriever,_=fixture(tmp_path)
    with pytest.raises(ImportError,match='reviewed_payload_changed'):
        import_reviewed(retriever.settings,[dict(content='changed')],dict(payload_sha256='bad',chunks=1))


@pytest.mark.parametrize('failure',[None,'missing_vector','changed_source','changed_corpus','private_metadata'])
def test_prepare_validates_sources_and_reuses_cache_without_any_model(tmp_path,failure):
    import sqlite3
    from qozon_langchain.knowledge_base.cloud_import import prepare_index
    retriever,_=fixture(tmp_path);s=retriever.settings
    chunks=tmp_path/'chunks';vectors=tmp_path/'vectors';chunks.mkdir();vectors.mkdir()
    source=tmp_path/'checked-source.txt';source.write_text(TEXT)
    meta=dict(META,manifest='/private/local/manifest.json',original_document='/private/extraction.json',
              summary_file='/private/summary.json',url='https://untrusted.example/private.pdf')
    if failure=='private_metadata':meta['source']='/private/original.pdf'
    record=dict(id=CHUNK,page_content=TEXT,metadata=meta)
    raw=json.dumps(record)+'\n';(chunks/'chunks.jsonl').write_text(raw)
    corpus=dict(document_id=ORIGINAL,corpus_sha256=text_hash(raw),chunk_count=1,
                input_files=[dict(path=str(source),sha256=text_hash(TEXT))])
    (chunks/'manifest.json').write_text(json.dumps(corpus))
    (vectors/'index-manifest.json').write_text(json.dumps(dict(status='complete',corpus_sha256=corpus['corpus_sha256'],
        model='text-embedding-3-small',dimensions=1536,completed_chunks=1)))
    with sqlite3.connect(vectors/'embedding-cache.sqlite3') as db:
        db.execute('CREATE TABLE vectors (identity TEXT PRIMARY KEY, vector TEXT NOT NULL)')
        if failure!='missing_vector':db.execute('INSERT INTO vectors VALUES (?,?)',
            (digest(['text-embedding-3-small',1536,TEXT]),json.dumps([1.0]+[0.0]*1535)))
    if failure=='changed_source':source.write_text('Changed source.')
    if failure=='changed_corpus':(chunks/'chunks.jsonl').write_text(raw+'\n')
    s.rag_chunks_directory=chunks;s.rag_vector_directory=vectors
    if failure:
        with pytest.raises(Exception):prepare_index(s)
    else:
        _,rows,report=prepare_index(s)
        assert report['embedding_calls']==report['model_calls']==0
        assert len(rows)==1 and rows[0]['evidence_content']==TEXT
        assert set(rows[0]['metadata'])==set(META)
        assert '/private/' not in json.dumps(rows) and 'https://' not in json.dumps(rows)
        assert report['revision']==prepare_index(s)[2]['revision']


@pytest.mark.parametrize('failed_lane',['qozon_match_chunks','qozon_keyword_chunks'])
def test_one_rpc_failure_cancels_and_joins_the_other_lane(tmp_path,failed_lane):
    async def scenario():
        started=asyncio.Event();cancelled=asyncio.Event()
        async def handler(req):
            if req.url.path.endswith(failed_lane):
                await started.wait()
                return httpx.Response(503,text='fictional upstream details')
            started.set()
            try:await asyncio.Event().wait()
            finally:cancelled.set()
        retriever,_=fixture(tmp_path)
        retriever.transport=httpx.MockTransport(handler)
        before=asyncio.all_tasks()
        try:
            with pytest.raises(RetrievalError):await retriever.retrieve('fictional garden')
            assert cancelled.is_set(), 'Failed retrieval returned while the sibling RPC was still running'
            assert not (asyncio.all_tasks()-before), 'Retrieval left orphaned child work'
        finally:
            pending=asyncio.all_tasks()-before
            for task in pending:task.cancel()
            if pending:await asyncio.gather(*pending,return_exceptions=True)
    asyncio.run(scenario())


@pytest.mark.parametrize('slow_stage',['embedding','rpc','final_validation'])
def test_cloud_workflow_deadline_cleans_up_and_next_request_recovers(tmp_path,slow_stage):
    async def scenario():
        retriever,_=fixture(tmp_path);normal=retriever.transport
        phase={'slow':True,'generated':False};cancelled=set();model_calls=[]
        original_embedding=retriever.embeddings.aembed_query
        async def embedding(query):
            if phase['slow'] and slow_stage=='embedding':
                try:await asyncio.Event().wait()
                finally:cancelled.add('embedding')
            return await original_embedding(query)
        retriever.embeddings.aembed_query=embedding
        async def handler(req):
            slow=phase['slow'] and ((slow_stage=='rpc' and '/rpc/' in req.url.path)
                or (slow_stage=='final_validation' and phase['generated']))
            if slow:
                try:await asyncio.Event().wait()
                finally:cancelled.add(req.url.path.rsplit('/',1)[-1])
            return await normal.handle_async_request(req)
        retriever.transport=httpx.MockTransport(handler)
        class Model:
            async def generate_grounded_answer(self,question,evidence):
                model_calls.append(question);phase['generated']=True
                return TEXT+' [S1]'
        before=asyncio.all_tasks()
        with pytest.raises(QuestionServiceError) as caught:
            await answer_question('Fictional garden',model=Model(),policy=training_policy(),retriever=retriever,timeout_seconds=0.08)
        assert caught.value.code=='question_timeout'
        expected={'embedding'} if slow_stage=='embedding' else {'qozon_match_chunks','qozon_keyword_chunks'} if slow_stage=='rpc' else {'qozon_documents'}
        assert cancelled==expected and not (asyncio.all_tasks()-before)
        assert len(model_calls)==(1 if slow_stage=='final_validation' else 0)
        phase.update(slow=False,generated=False)
        response=await answer_question('Fictional garden',model=Model(),policy=training_policy(),retriever=retriever)
        assert response.answer==TEXT+' [S1]' and response.sources[0].chunk_id==CHUNK
    asyncio.run(scenario())


def test_caller_cancellation_joins_both_cloud_lanes_then_next_request_succeeds(tmp_path):
    async def scenario():
        retriever,_=fixture(tmp_path);normal=retriever.transport
        started=set();cancelled=set();ready=asyncio.Event();slow=True
        async def handler(req):
            if slow and '/rpc/' in req.url.path:
                lane=req.url.path.rsplit('/',1)[-1];started.add(lane)
                if len(started)==2:ready.set()
                try:await asyncio.Event().wait()
                finally:cancelled.add(lane)
            return await normal.handle_async_request(req)
        retriever.transport=httpx.MockTransport(handler)
        before=asyncio.all_tasks();task=asyncio.create_task(retriever.retrieve('Fictional garden'))
        await asyncio.wait_for(ready.wait(),1);task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        assert cancelled==started and len(cancelled)==2 and not (asyncio.all_tasks()-before)
        slow=False
        assert (await retriever.retrieve('Fictional garden'))[0].text==TEXT
    asyncio.run(scenario())


def test_cloud_outage_does_not_poison_shared_retriever_or_retry_the_answer(tmp_path):
    async def scenario():
        retriever,requests=fixture(tmp_path);normal=retriever.transport;unavailable=True;calls=[]
        async def handler(req):
            if unavailable and '/rpc/' in req.url.path:return httpx.Response(503,text='private upstream details')
            return await normal.handle_async_request(req)
        retriever.transport=httpx.MockTransport(handler)
        class Model:
            async def generate_grounded_answer(self,question,evidence):calls.append(question);return TEXT+' [S1]'
        with pytest.raises(QuestionServiceError) as caught:
            await answer_question('Fictional garden',model=Model(),policy=training_policy(),retriever=retriever)
        assert caught.value.code=='retrieval_unavailable' and not calls
        assert 'private upstream' not in str(caught.value)
        unavailable=False
        result=await answer_question('Fictional garden',model=Model(),policy=training_policy(),retriever=retriever)
        assert result.sources and len(calls)==1
        assert all(r.headers['apikey']=='sb_publishable_synthetic' for r in requests)
    asyncio.run(scenario())
