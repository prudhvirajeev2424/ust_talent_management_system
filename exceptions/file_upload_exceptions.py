from fastapi import HTTPException
 
 
class FileFormatException(HTTPException):
    def __init__(self, detail="Invalid file format"):
        super().__init__(status_code=400, detail=detail)
 
class ValidationException(HTTPException):
    def __init__(self, detail):
        super().__init__(status_code=422, detail={"validation_error": detail})
 
 
class ReportProcessingException(HTTPException):
    def __init__(self, detail):
        super().__init__(status_code=400, detail=detail)
 
 