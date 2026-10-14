"""Repeatable importer/service lifecycle regressions; fictional rows, no network."""
import asyncio
import copy
import json

import httpx
import pytest
from langchain_core.embeddings import Embeddings

from qozon_langchain.core.config import Settings
from qozon_langchain.knowledge_base.cloud import CloudPDFRetriever,PublicMetadata,text_hash
from qozon_langchain.knowledge_base.cloud_import import ImportError,import_reviewed
from qozon_langchain.knowledge_base.pdf.chunking import digest
from qozon_langchain.security.policies import training_policy
from qozon_langchain.services.question_service import QuestionServiceError,answer_question

DOC='d6000000-0000-0000-0000-000000000001'
VECTOR=[1.0]+[0.0]*1535


def revision(number):
    rows=[]
    for text in [f'The fictional garden has {number} trees.','The fictional garden grows roses.']:
        meta=PublicMetadata(document_id=digest('fictional book'),source='fictional.pdf',page_numbers=[12],
            content_type='text',parent_asset_id='',source_sha256='',factually_verified=False,
            evidence_sha256=text_hash(text)).model_dump()
        rows.append(dict(chunk_id=digest(text),content=text,evidence_content=text,metadata=meta,embedding=VECTOR))
    sha=digest(rows)
    for row in rows:row['revision']=sha
    return rows,dict(revision=sha,chunks=len(rows),payload_sha256=digest(rows))


class MemoryCloud:
    """Minimal Data API fixture; real RLS is separately checked with real HTTP."""
    def __init__(self):
        self.document=dict(id=DOC,title='Fictional guide',active_revision=None,public_read=False,deleted=False)
        self.chunks={};self.requests=[]

    def visible(self):
        d=self.document
        return [r for r in self.chunks.values() if r['revision']==d['active_revision']] if d['public_read'] and not d['deleted'] else []

    def insert(self,rows):
        for row in rows:self.chunks.setdefault((row['revision'],row['chunk_id']),copy.deepcopy(row))

    def respond(self,req):
        self.requests.append(req);params=req.url.params;path=req.url.path
        privileged=req.headers.get('apikey')=='sb_secret_fictional'
        if path.startswith('/storage/v1/bucket/'):
            assert privileged;return httpx.Response(200,json={'public':False})
        if path.endswith('qozon_documents'):
            if req.method=='PATCH':
                assert privileged
                d=self.document
                expected={'id':'eq.'+DOC,'deleted':'eq.'+str(d['deleted']).lower(),
                          'public_read':'eq.'+str(d['public_read']).lower(),
                          'active_revision':'is.null' if d['active_revision'] is None else 'eq.'+d['active_revision']}
                if any(params.get(k)!=v for k,v in expected.items()):return httpx.Response(200,json=[])
                d.update(json.loads(req.content));return httpx.Response(200,json=[d])
            rows=[self.document] if privileged or self.visible() else []
            return httpx.Response(200,json=rows)
        if '/rpc/' in path:
            assert not privileged
            rows=[dict(content=r['evidence_content'],metadata=dict(r['metadata'],chunk_id=r['chunk_id'],
                cloud_document_id=DOC,revision=r['revision']),similarity=1.0,rank=1.0) for r in self.visible()]
            return httpx.Response(200,json=rows)
        if path.endswith('qozon_chunks'):
            if req.method=='POST':
                assert privileged and req.headers['Prefer']=='resolution=ignore-duplicates,return=minimal'
                self.insert(json.loads(req.content));return httpx.Response(201)
            rows=list(self.chunks.values()) if privileged else self.visible()
            if 'revision' in params:rows=[r for r in rows if 'eq.'+r['revision']==params['revision']]
            rows=sorted(rows,key=lambda r:r['chunk_id'])
            offset=int(params.get('offset',0));limit=int(params.get('limit',100))
            return httpx.Response(200,json=rows[offset:offset+limit])
        pytest.fail('No Auth, PDF transfer or unknown service is permitted')


class FixedEmbeddings(Embeddings):
    def embed_documents(self,texts):pytest.fail('No corpus embeddings')
    def embed_query(self,text):return VECTOR


@pytest.fixture
def cloud(tmp_path):
    settings=Settings(_env_file=None,supabase_url='https://fictional.supabase.co',
        supabase_publishable_key='sb_publishable_fictional',supabase_secret_key='sb_secret_fictional',
        supabase_storage_bucket='private-pdfs',rag_publication_manifest=tmp_path/'publication.json')
    state=MemoryCloud();transport=httpx.MockTransport(lambda request:state.respond(request))
    with httpx.Client(base_url=settings.supabase_url,headers={'apikey':'sb_secret_fictional'},transport=transport) as admin:
        def publish(pair,hook=None):return import_reviewed(settings,*pair,client=admin,storage_object='fictional.pdf',progress=hook)
        retriever=CloudPDFRetriever(settings=settings,embeddings=FixedEmbeddings(),transport=transport)
        yield state,publish,retriever


def test_partial_update_resume_and_repeated_import_keep_exact_rows(cloud):
    state,publish,retriever=cloud;a,b=revision('four'),revision('five')
    publish(a);state.insert([b[0][0]])
    assert state.document['active_revision']==a[1]['revision']
    assert {r['revision'] for r in state.visible()}=={a[1]['revision']}
    result=publish(b)
    assert result['previous_revision']==a[1]['revision'] and result['verified_chunks']==2
    evidence=asyncio.run(retriever.retrieve('Fictional garden'))
    assert len(evidence)==2 and all(e.revision==b[1]['revision'] for e in evidence)
    assert any('five trees' in e.text for e in evidence) and not any('four trees' in e.text for e in evidence)
    before=copy.deepcopy(state.chunks);posts=len([r for r in state.requests if r.method=='POST'])
    publish(b)
    assert state.chunks==before and len([r for r in state.requests if r.method=='POST'])==posts


def test_rollback_verifies_and_restores_previous_payload_retaining_both_revisions(cloud):
    state,publish,retriever=cloud;a,b=revision('four'),revision('five')
    publish(a);original=copy.deepcopy(state.chunks);publish(b)
    result=publish(a)
    assert result['previous_revision']==b[1]['revision']
    assert len(state.chunks)==4 and all(state.chunks[key]==row for key,row in original.items())
    evidence=asyncio.run(retriever.retrieve('Fictional garden'))
    assert all(e.revision==a[1]['revision'] for e in evidence)
    assert any('four trees' in e.text for e in evidence) and not any('five trees' in e.text for e in evidence)


@pytest.mark.parametrize('change',['competing','withdrawn','deleted','corrupt'])
def test_change_during_import_cannot_publish_or_overwrite_current_state(cloud,change):
    state,publish,_=cloud;a,b,c=revision('four'),revision('five'),revision('six')
    publish(a);publish(b);publish(a)
    def hook(_):
        if change=='competing':state.document['active_revision']=b[1]['revision']
        elif change=='withdrawn':state.document['public_read']=False
        elif change=='deleted':state.document['deleted']=True
        else:state.chunks[(c[1]['revision'],c[0][0]['chunk_id'])]['evidence_content']='Unreviewed text.'
    with pytest.raises(ImportError,match='cloud_readback_mismatch' if change=='corrupt' else 'concurrent_activation'):
        publish(c,hook)
    assert state.document['active_revision']!=c[1]['revision']
    assert all(r['revision']!=c[1]['revision'] for r in state.visible())
    if change=='withdrawn':assert state.document['public_read'] is False
    if change=='deleted':assert state.document['deleted'] is True


def test_corrupted_rollback_target_is_not_silently_overwritten_or_activated(cloud):
    state,publish,_=cloud;a,b=revision('four'),revision('five')
    publish(a);publish(b)
    key=(a[1]['revision'],a[0][0]['chunk_id']);state.chunks[key]['evidence_content']='Corrupted prior revision.'
    with pytest.raises(ImportError,match='cloud_readback_mismatch'):publish(a)
    assert state.document['active_revision']==b[1]['revision']
    assert state.chunks[key]['evidence_content']=='Corrupted prior revision.'


@pytest.mark.parametrize('change',['withdrawn','updated','deleted'])
def test_lifecycle_change_during_buffered_answer_withholds_valid_old_claim(cloud,change):
    state,publish,retriever=cloud;a,b=revision('four'),revision('five')
    publish(a);state.insert(b[0])
    class Model:
        async def generate_grounded_answer(self,question,evidence):
            if change=='withdrawn':state.document['public_read']=False
            elif change=='updated':state.document['active_revision']=b[1]['revision']
            else:state.document['deleted']=True
            for n,item in enumerate(evidence,1):
                if 'trees' in item.text:return item.text+f' [S{n}]'
    with pytest.raises(QuestionServiceError) as caught:
        asyncio.run(answer_question('Fictional garden',model=Model(),retriever=retriever,policy=training_policy()))
    assert caught.value.code=='source_access_changed'
    assert 'four trees' not in str(caught.value)


@pytest.mark.parametrize('change',['withdrawn','deleted'])
def test_hidden_document_abstains_without_answer_call_and_deleted_import_fails(cloud,change):
    state,publish,retriever=cloud;a=revision('four');publish(a)
    if change=='withdrawn':state.document['public_read']=False
    else:state.document['deleted']=True
    class Model:
        async def generate_grounded_answer(self,*args):pytest.fail('Hidden sources must not invoke a model')
    result=asyncio.run(answer_question('Fictional garden',model=Model(),retriever=retriever,policy=training_policy()))
    assert result.sources==[] and 'sufficient evidence' in result.answer
    if change=='deleted':
        with pytest.raises(ImportError,match='document_deleted'):publish(a)


@pytest.mark.parametrize('failure',['partial_insert','read_failure','activation_response_lost'])
def test_interrupted_import_resumes_without_duplicate_vectors_or_unchecked_activation(cloud,monkeypatch,failure):
    state,publish,_=cloud;a,b=revision('four'),revision('five');publish(a)
    original=state.respond;once=True
    monkeypatch.setattr('qozon_langchain.knowledge_base.cloud_import.time.sleep',lambda _:None)
    def respond(req):
        nonlocal once
        if once and req.url.path.endswith('qozon_chunks'):
            if failure=='partial_insert' and req.method=='POST':
                once=False;state.insert(json.loads(req.content)[:1]);raise httpx.WriteError('fictional interrupted write')
            if failure=='read_failure' and req.method=='GET' and 'embedding' in req.url.params.get('select',''):
                once=False;raise httpx.ReadError('fictional interrupted verification')
        if once and failure=='activation_response_lost' and req.method=='PATCH':
            once=False;original(req);raise httpx.ReadError('fictional lost activation reply')
        return original(req)
    state.respond=respond
    if failure=='activation_response_lost':
        with pytest.raises(ImportError,match='cloud_import_connection_failed'):publish(b)
        assert state.document['active_revision']==b[1]['revision']
    else:publish(b)
    result=publish(b)
    assert result['verified_chunks']==2 and len(state.chunks)==4
    assert state.document['active_revision']==b[1]['revision']
    assert {r['revision'] for r in state.visible()}=={b[1]['revision']}


def test_persistent_insert_failure_stops_after_three_safe_attempts_and_later_resumes(cloud,monkeypatch):
    state,publish,_=cloud;a,b=revision('four'),revision('five');publish(a);original=state.respond;attempts=[]
    monkeypatch.setattr('qozon_langchain.knowledge_base.cloud_import.time.sleep',lambda _:None)
    def unavailable(req):
        if req.method=='POST' and req.url.path.endswith('qozon_chunks'):
            attempts.append(req);return httpx.Response(503,text='fictional private upstream data')
        return original(req)
    state.respond=unavailable
    with pytest.raises(ImportError,match='cloud_import_request_failed'):publish(b)
    assert len(attempts)==3 and state.document['active_revision']==a[1]['revision']
    state.respond=original;publish(b)
    assert state.document['active_revision']==b[1]['revision'] and len(state.chunks)==4
