"""Import reviewed text and existing vectors; no model calls or PDF uploads.

Run --check to inspect locally, or --import-reviewed to stage, verify and publish.
The ingestion key is used only here; public retrieval uses the publishable key.
"""

import argparse
from collections import Counter
import json
import math
import os
from pathlib import Path
import sqlite3
import struct
import time

import httpx

from qozon_langchain.core.config import Settings
from qozon_langchain.knowledge_base.cloud import PublicMetadata, text_hash
from qozon_langchain.knowledge_base.documents import public_configuration
from qozon_langchain.knowledge_base.pdf.chunking import checked_document_text, digest, save_json
from qozon_langchain.knowledge_base.pdf.indexing import index_read_lock, load_corpus
from qozon_langchain.knowledge_base.pdf.publication import published_links
from qozon_langchain.knowledge_base.pdf.retrieval import resolve_record


class ImportError(Exception):
    """Fixed codes without source text, private locators or credentials."""


def vector32(vector):
    if (len(vector) != 1536 or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in vector)
            or not any(vector)):
        raise ImportError("cached_vector_invalid")
    return [struct.unpack('f', struct.pack('f', x))[0] for x in vector]


def prepare_index(settings):
    """Validate every source and cached vector before the first network write."""
    if settings.embedding_model_name != 'text-embedding-3-small' or settings.embedding_dimensions != 1536:
        raise ImportError("cloud_embedding_configuration_mismatch")
    with index_read_lock(settings.rag_vector_directory):
        corpus, records = load_corpus(settings.rag_chunks_directory)
        index = json.loads((settings.rag_vector_directory / 'index-manifest.json').read_text())
        if (index['status'] != 'complete' or index['corpus_sha256'] != corpus['corpus_sha256']
                or index['model'] != settings.embedding_model_name or index['dimensions'] != 1536
                or index['completed_chunks'] != len(records)):
            raise ImportError("local_index_mismatch")
        hashes = {x['path']: x['sha256'] for x in corpus['input_files']}
        for name, sha in hashes.items():
            import hashlib
            if hashlib.sha256(Path(name).read_bytes()).hexdigest() != sha:
                raise ImportError("reviewed_source_changed")
        rows = []
        cache = settings.rag_vector_directory / 'embedding-cache.sqlite3'
        with sqlite3.connect(cache.resolve().as_uri() + '?mode=ro', uri=True) as db:
            for record in records:
                meta = record['metadata']
                if meta['document_id'] != corpus['document_id']:
                    raise ImportError("mixed_source_documents")
                text, _ = resolve_record(settings, record, hashes,
                    budget=settings.rag_context_characters // settings.rag_top_k, image_selected=True)
                checked = checked_document_text(text)[0]
                if checked is None or len(checked) > 16000:
                    raise ImportError("cloud_evidence_needs_review")
                if meta['parent_asset_id'] and not published_links(settings, meta['document_id'],
                                            meta['parent_asset_id'], meta.get('source_sha256', '')):
                    raise ImportError("cloud_asset_not_approved")
                # Construct explicitly; never copy the local extraction metadata dictionary.
                public = PublicMetadata(document_id=meta['document_id'], source=meta['source'],
                    page_numbers=meta['page_numbers'], content_type=meta['content_type'],
                    parent_asset_id=meta['parent_asset_id'], source_sha256=meta.get('source_sha256', ''),
                    factually_verified=meta['factually_verified'], evidence_sha256=text_hash(checked)).model_dump()
                key = digest([settings.embedding_model_name, 1536, record['page_content']])
                saved = db.execute('SELECT vector FROM vectors WHERE identity=?', (key,)).fetchone()
                if saved is None:
                    raise ImportError("cached_vector_missing")
                rows.append(dict(chunk_id=record['id'], content=record['page_content'],
                                 evidence_content=checked, metadata=public, embedding=vector32(json.loads(saved[0]))))
        # Identity includes full evidence and the actual public contract, not local paths.
        revision = digest(rows)
        for row in rows:
            row['revision'] = revision
        return corpus, rows, dict(status='reviewed', revision=revision, corpus_sha256=corpus['corpus_sha256'],
            chunks=len(rows), chunk_types=dict(Counter(r['metadata']['content_type'] for r in rows)),
            approved_assets=len({r['metadata']['parent_asset_id'] for r in rows if r['metadata']['parent_asset_id']}),
            payload_sha256=digest(rows), embedding_model=settings.embedding_model_name, dimensions=1536,
            embedding_calls=0, model_calls=0, original_pdf_uploaded=False)


def request(client, method, path, **kwargs):
    # Only reads and immutable duplicate-ignoring inserts are safe to repeat.
    attempts = 3 if method == 'GET' or (method == 'POST' and path == '/rest/v1/qozon_chunks') else 1
    for attempt in range(attempts):
        try:
            response = client.request(method, path, **kwargs)
            if response.status_code not in {429, 500, 502, 503, 504} or attempt == attempts - 1:
                break
        except httpx.RequestError:
            if attempt == attempts - 1:
                raise
        time.sleep(attempt + 1)
    if response.status_code not in {200, 201, 204}:
        raise ImportError("cloud_import_request_failed")
    return response


def stored_payload(row):
    vector = row['embedding']
    if isinstance(vector, str):
        vector = json.loads(vector)
    return {**{k: row[k] for k in ('chunk_id', 'revision', 'content', 'evidence_content', 'metadata')},
            'embedding': vector32(vector)}


def import_reviewed(settings, rows, report, *, client=None, storage_object=None, progress=None):
    """Idempotent immutable staging, complete read-back, conditional atomic activation."""
    # Reuse the strict project/publishable configuration validator, without a read.
    public_configuration(settings)
    if settings.supabase_secret_key is None or not settings.supabase_secret_key.get_secret_value().startswith('sb_secret_'):
        raise ImportError("cloud_ingestion_key_not_configured")
    expected_payload = digest(rows)
    if expected_payload != report['payload_sha256'] or len(rows) != report['chunks'] or not rows:
        raise ImportError("reviewed_payload_changed")
    owned = client is None
    client = client or httpx.Client(base_url=settings.supabase_url.rstrip('/'),
        headers={'apikey': settings.supabase_secret_key.get_secret_value()},
        timeout=60, follow_redirects=False, trust_env=False,
        limits=httpx.Limits(max_keepalive_connections=0))
    try:
        bucket = settings.supabase_storage_bucket or ''
        private = request(client, 'GET', '/storage/v1/bucket/' + bucket).json()
        if private.get('public') is not False:
            raise ImportError("original_bucket_not_private")
        if storage_object is None:
            objects = request(client, 'POST', '/storage/v1/object/list/' + bucket,
                              json={'prefix': '', 'limit': 100, 'offset': 0}).json()
            pdfs = [x['name'] for x in objects if x.get('id') and x['name'].lower().endswith('.pdf')]
            if len(pdfs) != 1:
                raise ImportError("private_source_selection_required")
            storage_object = pdfs[0]
        params = {'select': 'id,active_revision,public_read,deleted', 'owner_id': 'is.null',
                  'storage_bucket': 'eq.' + bucket, 'storage_object': 'eq.' + storage_object, 'limit': 1}
        documents = request(client, 'GET', '/rest/v1/qozon_documents', params=params).json()
        if not documents:
            documents = request(client, 'POST', '/rest/v1/qozon_documents',
                headers={'Prefer': 'return=representation'}, json={
                    'title': rows[0]['metadata']['source'].removesuffix('.pdf'),
                    'storage_bucket': bucket, 'storage_object': storage_object, 'public_read': False}).json()
        document = documents[0]
        if document['deleted']:
            raise ImportError("document_deleted")
        doc_id, previous = document['id'], document['active_revision']
        existing = set()
        for offset in range(0, len(rows) + 1, 1000):
            page = request(client, 'GET', '/rest/v1/qozon_chunks', params={
                'select': 'chunk_id', 'document_id': 'eq.' + doc_id,
                'revision': 'eq.' + report['revision'], 'order': 'chunk_id.asc',
                'limit': 1000, 'offset': offset}).json()
            existing.update(row['chunk_id'] for row in page)
            if len(page) < 1000:
                break
        pending = [row for row in rows if row['chunk_id'] not in existing]
        for start in range(0, len(pending), 32):
            batch = [dict(row, document_id=doc_id) for row in pending[start:start + 32]]
            # Do not overwrite a published revision or a competing staging writer.
            request(client, 'POST', '/rest/v1/qozon_chunks',
                params={'on_conflict': 'document_id,revision,chunk_id'},
                headers={'Prefer': 'resolution=ignore-duplicates,return=minimal'}, json=batch)
            if progress:
                progress(dict(staged_chunks=len(existing) + min(start+32, len(pending)), total_chunks=len(rows)))
        current = []
        for offset in range(0, len(rows) + 1, 100):
            page = request(client, 'GET', '/rest/v1/qozon_chunks', params={
                'select': 'chunk_id,revision,content,evidence_content,metadata,embedding',
                'document_id': 'eq.' + doc_id, 'revision': 'eq.' + report['revision'],
                'order': 'chunk_id.asc', 'limit': 100, 'offset': offset}).json()
            current.extend(stored_payload(r) for r in page)
            if len(page) < 100:
                break
        expected = sorted(rows, key=lambda r: r['chunk_id'])
        if current != expected:
            raise ImportError("cloud_readback_mismatch")
        activated = request(client, 'PATCH', '/rest/v1/qozon_documents',
            params={'id': 'eq.' + doc_id, 'deleted': 'eq.false',
                    'public_read': 'eq.' + str(document['public_read']).lower(),
                    'active_revision': 'is.null' if previous is None else 'eq.' + previous},
            headers={'Prefer': 'return=representation'},
            json={'active_revision': report['revision'], 'public_read': True}).json()
        if len(activated) != 1:
            raise ImportError("concurrent_activation")
        return dict(report, status='imported_verified_public', cloud_document_id=doc_id,
                    previous_revision=previous, verified_chunks=len(current), public_read=True)
    except ImportError:
        raise
    except httpx.TimeoutException:
        raise ImportError("cloud_import_timeout") from None
    except httpx.RequestError:
        raise ImportError("cloud_import_connection_failed") from None
    except Exception:
        raise ImportError("cloud_import_unavailable") from None
    finally:
        if owned:
            client.close()


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--check', action='store_true')
    action.add_argument('--import-reviewed', action='store_true')
    parser.add_argument('--storage-object')
    parser.add_argument('--report', type=Path, default=Path('data/evaluations/phase4-cloud-index-v1.json'))
    args = parser.parse_args()
    try:
        settings = Settings()
        _, rows, report = prepare_index(settings)
        if args.import_reviewed:
            report = import_reviewed(settings, rows, report, storage_object=args.storage_object,
                                     progress=lambda x: print(json.dumps(x), flush=True))
        save_json(args.report, report)
        print(json.dumps(report))
    except Exception as error:
        print(json.dumps({'status': 'failed', 'code': str(error) if isinstance(error, ImportError) else 'cloud_index_review_failed'}))
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
