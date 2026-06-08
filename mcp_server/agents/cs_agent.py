# mcp_server/agents/cs_agent.py
"""
CS Agent: 고객 서비스 전담
- VectorDB(product_docs Collection)에서 제품 문서/FAQ/매뉴얼 검색
- 고객 문의 응대, 반품/교환 절차 안내
- 외부 고객 대상 (Sales/CS 부서용)
"""
import sys
import asyncio
from .base_agent import BaseAgent


class CSAgent(BaseAgent):
    """고객 서비스(CS) 전문 Agent"""

    def __init__(self, llm_config: dict, service_manager=None):
        super().__init__(
            name="CS Agent",
            description="고객 서비스를 전담합니다. 제품 FAQ, 반품/교환 절차, "
                       "제품 사용법, 고객 문의에 대한 답변을 제공합니다. "
                       "VectorDB의 product_docs 컬렉션에서 제품 관련 문서를 검색합니다.",
            llm_config=llm_config,
        )
        self.service_manager = service_manager

    def register_tools_from_services(self, user_id: str = None):
        """제품 문서 RAG 도구 등록"""
        from ..services import vectordb_service, openai_service

        # 제품 문서 업로드 (product_docs Collection)
        async def upload_product_document(content: str, file_name: str = None, **kwargs):
            """제품 관련 문서를 VectorDB에 업로드합니다 (content, file_name)"""
            # OpenAI가 filename, doc_name 등 다른 이름으로 보낼 수 있음
            if not file_name:
                file_name = kwargs.get('filename') or kwargs.get('doc_name') or kwargs.get('name') or 'untitled.txt'
            try:
                chunks = vectordb_service.split_text_into_chunks(content)
                embeddings_list = []
                for chunk in chunks:
                    emb = await asyncio.to_thread(openai_service.create_embedding, chunk)
                    if emb:
                        embeddings_list.append(emb)

                if not embeddings_list:
                    return {'success': False, 'error': '임베딩 생성 실패'}

                result = vectordb_service.add_document(
                    content=content,
                    file_name=file_name,
                    embeddings=embeddings_list,
                    collection_name='product_docs',
                )
                return {'success': True, 'file_name': file_name, 'chunks': len(chunks)}
            except Exception as e:
                return {'success': False, 'error': str(e)}

        # 제품 문서 검색
        async def search_product_documents(query: str, top_k: int = 5):
            """제품 관련 문서를 검색합니다"""
            query_embedding = await asyncio.to_thread(openai_service.create_embedding, query)
            if not query_embedding:
                return {'success': False, 'error': '임베딩 생성 실패'}
            results = vectordb_service.search_documents(
                query_embedding, top_k=top_k, collection_name='product_docs'
            )
            return {'success': True, 'results': results}

        # 고객 문의 응대 (RAG)
        async def answer_customer_inquiry(question: str):
            """고객 문의에 대해 제품 문서 기반으로 답변합니다"""
            query_embedding = await asyncio.to_thread(openai_service.create_embedding, question)
            if not query_embedding:
                return {'success': False, 'error': '임베딩 생성 실패'}

            results = vectordb_service.search_documents(
                query_embedding, top_k=3, collection_name='product_docs'
            )
            if not results:
                return {
                    'success': True,
                    'answer': '관련 제품 문서를 찾을 수 없습니다. 고객센터로 문의해주세요.',
                    'sources': []
                }

            context_parts = []
            sources = []
            for r in results:
                context_parts.append(r.get('content', ''))
                sources.append(r.get('file_name', 'unknown'))

            context = "\n\n---\n\n".join(context_parts)

            answer = await asyncio.to_thread(
                openai_service.generate_text_with_system,
                system_prompt="""당신은 고객 서비스 전문가입니다.
제품 문서를 기반으로 고객의 질문에 친절하고 정확하게 답변하세요.

규칙:
1. 문서에 있는 정보만 사용하세요
2. 확실하지 않은 내용은 "확인 후 답변드리겠습니다"라고 안내하세요
3. 반품/교환/AS 관련은 정확한 절차를 안내하세요
4. 한국어로 친절하게 답변하세요""",
                user_prompt=f"제품 문서 내용:\n{context}\n\n고객 질문: {question}",
                temperature=0.3,
                max_tokens=1000,
            )

            return {'success': True, 'answer': answer, 'sources': list(set(sources))}

        # 제품 문서 목록
        async def list_product_documents():
            """업로드된 제품 문서 목록을 조회합니다"""
            return vectordb_service.list_documents(collection_name='product_docs')

        # 도구 등록
        self.register_tool('upload_product_document', upload_product_document,
                          '제품 관련 문서를 업로드합니다 (FAQ, 매뉴얼, 반품규정 등)')
        self.register_tool('search_product_documents', search_product_documents,
                          '제품 문서를 검색합니다 (query, top_k)')
        self.register_tool('answer_customer_inquiry', answer_customer_inquiry,
                          '고객 문의에 제품 문서 기반으로 답변합니다 (question)')
        self.register_tool('list_product_documents', list_product_documents,
                          '업로드된 제품 문서 목록을 조회합니다')

        print(f"[CS Agent] {len(self._tools)} tools registered for user: {user_id}", file=sys.stderr)
