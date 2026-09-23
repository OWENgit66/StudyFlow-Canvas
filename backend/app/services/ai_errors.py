"""Safe public errors; never include provider bodies, prompts or credentials."""
class AIError(Exception):
    code = 'ai_error'
    http_status = 502

class AIConfigurationError(AIError):
    code = 'ai_not_configured'
    http_status = 503

class AITransientError(AIError):
    code = 'ai_temporarily_unavailable'
    http_status = 503

class AIResponseError(AIError):
    code = 'invalid_ai_response'

class AIRefusalError(AIError):
    code = 'ai_refusal'

class KnowledgeInputError(AIError):
    code = 'knowledge_input_error'
    http_status = 409

class KnowledgeNotFoundError(AIError):
    code = 'knowledge_not_found'
    http_status = 404

class KnowledgeDatabaseError(AIError):
    code = 'knowledge_database_error'
    http_status = 500
