from fastapi import APIRouter, UploadFile, File, HTTPException, Form
from fastapi.responses import FileResponse
from app.models.schemas import (
    UploadResponse,
    GenerateDocumentsRequest,
    GrantData,
    PackageUploadResponse,
    SourceDocument,
    PrivacySettings,
)
from app.services.llm_service import LLMService
from app.services.document_service import DocumentService
from app.services.privacy_service import PrivacyService
from app.services.local_extraction_service import LocalExtractionService
from app.utils.file_helpers import save_uploaded_file, extract_text_from_file, generate_file_id
from typing import Dict, List, Optional
import os

router = APIRouter(prefix="/api/grants", tags=["grants"])

grant_data_store: Dict[str, GrantData] = {}
generated_docs_store: Dict[str, Dict[str, str]] = {}

llm_service = LLMService()
document_service = DocumentService()
privacy_service = PrivacyService()
local_extraction_service = LocalExtractionService()


async def _save_and_extract(file: UploadFile, document_type: str) -> tuple[str, str, str]:
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in [".pdf", ".docx", ".doc"]:
        raise HTTPException(status_code=400, detail=f"Unsupported file type for '{file.filename}'")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail=f"File '{file.filename}' is empty")
    file_id = generate_file_id()
    filepath = save_uploaded_file(content, file.filename, file_id)
    text, _ = extract_text_from_file(filepath)
    if not text or len(text.strip()) < 50:
        raise HTTPException(status_code=400, detail=f"'{file.filename}' does not contain sufficient readable text")
    return file_id, file.filename, text


def _build_privacy_settings(
    redact_names: bool,
    redact_salaries: bool,
    redact_contact_details: bool,
    enable_external_llm: bool,
) -> PrivacySettings:
    return PrivacySettings(
        redact_names=redact_names,
        redact_salaries=redact_salaries,
        redact_contact_details=redact_contact_details,
        enable_external_llm=enable_external_llm,
    )


async def process_single_file(file: UploadFile, file_num: int, total_files: int) -> UploadResponse:
    file_id, filename, text = await _save_and_extract(file, "unknown")
    source_documents = [SourceDocument(file_id=file_id, filename=filename, document_type="unknown")]
    settings = PrivacySettings()
    redacted_text, redactions = privacy_service.redact_text(text, settings)
    grant_data = local_extraction_service.extract(
        redacted_text,
        source_documents=source_documents,
        proposal_text=None,
        award_letter_text=None,
        privacy_settings=settings,
    )
    grant_data.redacted_text = redacted_text
    grant_data.redactions = redactions
    grant_data.transmission_preview = privacy_service.build_transmission_preview(
        text,
        redacted_text,
        structured_fields_count=8,
        external_llm_enabled=False,
    )
    grant_data_store[file_id] = grant_data
    return UploadResponse(
        success=True,
        message="File uploaded and locally processed successfully",
        file_id=file_id,
        filename=filename,
        document_type=grant_data.document_type,
    )


@router.post("/upload", response_model=List[UploadResponse])
async def upload_grant_letters(files: List[UploadFile] = File(...)):
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")
    if len(files) > 10:
        raise HTTPException(status_code=400, detail="Maximum 10 files allowed per upload")

    results: List[UploadResponse] = []
    for idx, file in enumerate(files, 1):
        try:
            results.append(await process_single_file(file, idx, len(files)))
        except Exception as e:
            results.append(
                UploadResponse(
                    success=False,
                    message=str(e),
                    file_id="",
                    filename=file.filename or f"file_{idx}",
                    document_type="unknown",
                )
            )
    return results


@router.post("/upload-package", response_model=PackageUploadResponse)
async def upload_grant_package(
    proposal: Optional[UploadFile] = File(None),
    award_letter: Optional[UploadFile] = File(None),
    redact_names: bool = Form(True),
    redact_salaries: bool = Form(True),
    redact_contact_details: bool = Form(True),
    enable_external_llm: bool = Form(True),
):
    if not proposal and not award_letter:
        raise HTTPException(status_code=400, detail="Upload at least a proposal or an award letter")

    privacy_settings = _build_privacy_settings(
        redact_names,
        redact_salaries,
        redact_contact_details,
        enable_external_llm,
    )

    source_documents: List[SourceDocument] = []
    proposal_text = None
    award_text = None
    proposal_file_id = None
    award_file_id = None
    proposal_filename = None
    award_filename = None

    if proposal:
        proposal_file_id, proposal_filename, proposal_text = await _save_and_extract(proposal, "proposal")
        source_documents.append(SourceDocument(file_id=proposal_file_id, filename=proposal_filename, document_type="proposal"))

    if award_letter:
        award_file_id, award_filename, award_text = await _save_and_extract(award_letter, "award_letter")
        source_documents.append(SourceDocument(file_id=award_file_id, filename=award_filename, document_type="award_letter"))

    package_id = generate_file_id()
    merged_text_parts = []
    if proposal_text:
        merged_text_parts.append(f"[PROPOSAL]\n{proposal_text}")
    if award_text:
        merged_text_parts.append(f"[AWARD LETTER]\n{award_text}")
    merged_text = "\n\n".join(merged_text_parts)

    redacted_text, redactions = privacy_service.redact_text(merged_text, privacy_settings)
    grant_data = local_extraction_service.extract(
        redacted_text,
        source_documents=source_documents,
        proposal_text=proposal_text,
        award_letter_text=award_text,
        privacy_settings=privacy_settings,
    )
    grant_data.redacted_text = redacted_text
    grant_data.redactions = redactions

    structured_fields_count = len([
        grant_data.organization_name,
        grant_data.grant_title,
        grant_data.grant_amount,
        grant_data.grant_period,
        grant_data.funder_name,
        grant_data.timeline.items if grant_data.timeline else [],
        grant_data.reporting_requirements,
        grant_data.submission_requirements,
    ])

    use_external_llm = privacy_settings.enable_external_llm and llm_service.is_available()
    grant_data.transmission_preview = privacy_service.build_transmission_preview(
        merged_text,
        redacted_text,
        structured_fields_count=structured_fields_count,
        external_llm_enabled=use_external_llm,
    )

    if use_external_llm:
        grant_data = llm_service.enrich_grant_data(
            grant_data,
            sanitized_text=redacted_text,
            source_documents=source_documents,
        )

    grant_data_store[package_id] = grant_data

    message = "Grant package uploaded and locally processed successfully"
    if use_external_llm:
        message += "; sanitized content was also sent to the external LLM"

    return PackageUploadResponse(
        success=True,
        package_id=package_id,
        message=message,
        proposal_file_id=proposal_file_id,
        award_file_id=award_file_id,
        proposal_filename=proposal_filename,
        award_filename=award_filename,
        used_external_llm=use_external_llm,
        redaction_count=len(redactions),
    )


@router.get("/data/{file_id}")
async def get_grant_data(file_id: str):
    if file_id not in grant_data_store:
        raise HTTPException(status_code=404, detail="Grant data not found")
    return grant_data_store[file_id]


@router.get("/list")
async def list_grants():
    grants = []
    for file_id, grant_data in grant_data_store.items():
        grants.append(
            {
                "file_id": file_id,
                "filename": f"grant_{file_id[:8]}",
                "organization": grant_data.organization_name,
                "grant_title": grant_data.grant_title,
                "grant_amount": grant_data.grant_amount,
                "created_at": None,
                "processed": True,
            }
        )
    return {"grants": grants}


@router.post("/generate-documents/{file_id}")
async def generate_documents(file_id: str, request: GenerateDocumentsRequest):
    if file_id not in grant_data_store:
        raise HTTPException(status_code=404, detail="Grant data not found")

    grant_data = grant_data_store[file_id]
    options = {
        "generate_workplan": request.generate_workplan,
        "generate_budget": request.generate_budget,
        "generate_report_template": request.generate_report_template,
        "generate_calendar": request.generate_calendar,
        "generate_agenda_template": request.generate_agenda_template,
        "disbursement_interval_days": request.disbursement_interval_days,
        "disbursement_reminder_days": request.disbursement_reminder_days,
        "meeting_interval_days": request.meeting_interval_days,
    }
    generated_files = document_service.generate_all_documents(grant_data, file_id, options)
    generated_docs_store.setdefault(file_id, {})
    response: dict = {"success": True, "files": {}, "calendar_discrepancy": []}

    for doc_type, value in generated_files.items():
        if doc_type == "calendar_discrepancy":
            response["calendar_discrepancy"] = value
            continue
        if not doc_type.endswith("_error") and os.path.exists(value):
            generated_docs_store[file_id][doc_type] = value
            response["files"][doc_type] = {
                "filename": os.path.basename(value),
                "download_url": f"/api/grants/download/{file_id}/{doc_type}",
            }
        else:
            response["files"][doc_type] = value
    return response


@router.get("/download/{file_id}/{doc_type}")
async def download_document(file_id: str, doc_type: str):
    extensions = {
        "workplan": ".pdf",
        "budget": ".xlsx",
        "report": ".docx",
        "calendar": ".ics",
        "agenda": ".docx",
    }
    if doc_type not in extensions:
        raise HTTPException(status_code=400, detail=f"Invalid document type: {doc_type}")

    filepath = generated_docs_store.get(file_id, {}).get(doc_type)
    if not filepath:
        filename = f"{file_id}_{doc_type}{extensions[doc_type]}"
        filepath = os.path.join("temp_files", filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail=f"File not found: {os.path.basename(filepath)}")

    media_types = {
        ".pdf": "application/pdf",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".ics": "text/calendar",
    }
    ext = extensions[doc_type]
    return FileResponse(
        path=filepath,
        media_type=media_types.get(ext, "application/octet-stream"),
        filename=os.path.basename(filepath),
        headers={"Content-Disposition": f'attachment; filename="{os.path.basename(filepath)}"'},
    )


@router.delete("/{file_id}")
async def delete_grant(file_id: str):
    grant_data = grant_data_store.pop(file_id, None)
    generated_docs = generated_docs_store.pop(file_id, {})

    if not grant_data:
        raise HTTPException(status_code=404, detail="Grant data not found")

    for source in grant_data.source_documents or []:
        if source.file_id and source.filename:
            ext = os.path.splitext(source.filename)[1]
            source_path = os.path.join("temp_files", f"{source.file_id}{ext}")
            if os.path.exists(source_path):
                try:
                    os.remove(source_path)
                except OSError:
                    pass

    for path in generated_docs.values():
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass

    return {"success": True, "message": "Grant deleted"}
