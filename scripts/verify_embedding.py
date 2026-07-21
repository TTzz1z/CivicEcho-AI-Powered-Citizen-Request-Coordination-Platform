"""Verify embedding API and RAG retrieval quality."""
import sys
sys.path.insert(0, '/app')
from app.database import SessionLocal
from app.services.kb_service import KnowledgeBaseService
from app.authorization import Principal

with SessionLocal() as db:
    svc = KnowledgeBaseService(db)
    principal = Principal(kind='user', user_id=2, username='citizen_local', role='citizen')
    results = svc.retrieve('博士人才家属享受什么待遇', principal, top_k=3)
    print('accessible_doc_count=', results['accessible_doc_count'])
    print('no_evidence=', results['no_evidence'])
    print('chunks count=', len(results['chunks']))
    for i, c in enumerate(results['chunks']):
        print('--- Chunk', i, '---')
        print('  type=', type(c).__name__)
        if hasattr(c, '__dict__'):
            for attr in vars(c).keys():
                if not attr.startswith('_'):
                    val = getattr(c, attr)
                    print(' ', attr, '=', str(val)[:200])
        elif isinstance(c, dict):
            for k, v in c.items():
                print(' ', k, '=', str(v)[:200])
        else:
            print('  repr=', repr(c)[:500])
