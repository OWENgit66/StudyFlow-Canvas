"""Safe errors for local document processing; no raw PDF data in messages."""


class DocumentError(Exception):
    code = "document_error"
    http_status = 422


class InvalidDocumentError(DocumentError):
    code = "invalid_document"


class DocumentParseError(DocumentError):
    code = "document_parse_error"


class ResourceNotFoundError(DocumentError):
    code = "resource_not_found"
    http_status = 404


class DocumentDatabaseError(DocumentError):
    code = "document_database_error"
    http_status = 500
