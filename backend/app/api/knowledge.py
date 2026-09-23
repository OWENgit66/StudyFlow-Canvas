from typing import Annotated
from fastapi import APIRouter,Depends,Path,Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database import get_db
from app.schemas.knowledge import KnowledgeResponse
from app.services.ai_errors import AIError
from app.services.ai_service import AIService
from app.services.llm_factory import create_llm_provider
from app.services.document_service import DocumentService
from app.services.knowledge_service import KnowledgeService

router=APIRouter(prefix='/api/resources',tags=['knowledge'])
DB=Annotated[Session,Depends(get_db)]
ID=Annotated[int,Path(gt=0)]


def get_ai_service():
    settings=Settings()
    return AIService(create_llm_provider(settings),settings)


def get_knowledge_service():
    return KnowledgeService(DocumentService(Settings()))


async def ai_error_handler(_request:Request,error:AIError):
    return JSONResponse(status_code=error.http_status,content={'detail':{'code':error.code,'message':str(error)}})


@router.post('/{resource_id}/knowledge',response_model=KnowledgeResponse)
def generate(resource_id:ID,db:DB,ai:Annotated[AIService,Depends(get_ai_service)],
             service:Annotated[KnowledgeService,Depends(get_knowledge_service)]):
    return service.generate(db,resource_id,ai)


@router.get('/{resource_id}/knowledge',response_model=KnowledgeResponse)
def read(resource_id:ID,db:DB,service:Annotated[KnowledgeService,Depends(get_knowledge_service)],
         include_stale: bool = False):
    return service.read(db,resource_id,include_stale=include_stale)
