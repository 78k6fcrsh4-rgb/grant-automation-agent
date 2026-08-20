from fastapi import APIRouter, UploadFile, File, HTTPException, Form, Depends
from fastapi.responses import FileResponse
from app.deps import get_current_user
from app.models.db_models import User
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
from app.utils.file_helpers import save_uploaded_file, extract_text_from_file, extract_text_from_pdf, generate_file_id
from typing import Dict, List, Optional
import io
import os
import time
import glob

router = APIRouter(prefix="/api/grants", tags=["grants"])

grant_data_store: Dict[str, GrantData] = {}
generated_docs_store: Dict[str, Dict[str, str]] = {}
# Maps grant/package id -> owning tenant_id, so each org sees only its own grants.
grant_tenant: Dict[str, int] = {}
# --- Ephemeral / "forget-by-design" state ---
# Grant data lives only in memory and is purged after a short idle window. It is
# never written to a durable database — the app is a tool to manage a grant when
# it is awarded, not a system of record.
grant_created_at: Dict[str, float] = {}
GRANT_TTL_SECONDS = int(os.getenv("GRANT_TTL_MINUTES", "120")) * 60
TEMP_DIR = "temp_files"


def _touch(file_id: str) -> None:
    """(Re)start the idle clock for a grant — called on create and on each access
    so an active session is never purged mid-use (sliding expiration)."""
    grant_created_at[file_id] = time.time()


def _delete_generated_files(file_id: str) -> None:
    for path in (generated_docs_store.get(file_id) or {}).values():
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except OSError:
            pass


def _forget(file_id: str) -> None:
    """Erase every trace of one grant: in-memory records + generated files."""
    _delete_generated_files(file_id)
    grant_data_store.pop(file_id, None)
    generated_docs_store.pop(file_id, None)
    grant_tenant.pop(file_id, None)
    grant_created_at.pop(file_id, None)


def purge_expired() -> int:
    """Forget grants idle longer than GRANT_TTL_SECONDS. Returns count purged."""
    now = time.time()
    expired = [fid for fid, ts in list(grant_created_at.items())
               if now - ts > GRANT_TTL_SECONDS]
    for fid in expired:
        _forget(fid)
    return len(expired)


def clear_temp_dir() -> int:
    """Wipe leftover files in temp_files/ (orphaned after a restart, since the
    in-memory index that referenced them is gone). Keeps .gitkeep."""
    removed = 0
    for path in glob.glob(os.path.join(TEMP_DIR, "*")):
        if path.endswith(".gitkeep"):
            continue
        try:
            os.remove(path); removed += 1
        except OSError:
            pass
    return removed

llm_service = LLMService()
document_service = DocumentService()
privacy_service = PrivacyService()
local_extraction_service = LocalExtractionService()


def _check_access(file_id: str, user: User):
    """404 if the grant doesn't belong to the caller's tenant (don't leak existence)."""
    owner = grant_tenant.get(file_id)
    if owner is not None and owner != user.tenant_id:
        raise HTTPException(status_code=404, detail="Grant data not found")


def _ocr_pdf_text(filepath: str, max_pages: int = 5) -> str:
    """OCR a scanned PDF using PyMuPDF (page rendering) + pytesseract.

    Renders each page at 2x scale (~144 DPI) and passes the result to
    Tesseract. This handles both embedded-image PDFs and fully rasterised
    scans. Returns an empty string if OCR fails for any reason.

    max_pages caps processing to avoid hanging on large scanned documents
    (e.g. 30+ page contracts where only the first few pages contain the
    key grant header information needed for extraction).
    """
    try:
        import fitz  # PyMuPDF
        import pytesseract
        from PIL import Image

        doc = fitz.open(filepath)
        text_parts: list[str] = []
        mat = fitz.Matrix(2, 2)  # 2× scale ≈ 144 DPI — reliable for Tesseract
        for page in doc.pages(0, min(max_pages, len(doc))):
            pix = page.get_pixmap(matrix=mat)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            text_parts.append(pytesseract.image_to_string(img))
        doc.close()
        return "\n".join(text_parts).strip()
    except Exception:
        return ""


def _save_and_extract(file: UploadFile, document_type: str) -> tuple[str, str, str, Optional[str]]:
    """Extract text from an uploaded file.

    Returns (file_id, filename, text, content_warning).
    content_warning is None when the file looks complete, or a plain-English
    advisory string when the file was sparse or needed OCR.
    Raises HTTPException only when the file is truly unreadable even after OCR.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in [".pdf", ".docx", ".doc"]:
        raise HTTPException(status_code=400, detail=f"Unsupported file type for '{file.filename}'")
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=400, detail=f"'{file.filename}' is empty — please check the file and try again")
    file_id = generate_file_id()
    filepath = save_uploaded_file(content, file.filename, file_id)
    text, _ = extract_text_from_file(filepath)
    stripped = (text or "").strip()

    content_warning: Optional[str] = None

    if len(stripped) < 10:
        if ext == ".pdf":
            # Attempt automatic OCR before giving up
            ocr_text = _ocr_pdf_text(filepath)
            if len(ocr_text) >= 10:
                stripped = ocr_text
                content_warning = (
                    f"'{file.filename}' appeared to be a scanned image, so OCR was applied automatically. "
                    f"Text was extracted successfully but may contain minor recognition errors — "
                    f"please review any dates or dollar amounts in the generated documents."
                )
            else:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"No readable text could be extracted from '{file.filename}', even after attempting OCR. "
                        f"This usually means the file is password-protected or corrupted. "
                        f"Please unlock or repair the file and try again."
                    ),
                )
        else:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"No readable text could be extracted from '{file.filename}'. "
                    f"The document appears to be empty or corrupted. "
                    f"Please check the file and try again."
                ),
            )

    if content_warning is None and len(stripped) < 400:
        content_warning = (
            f"'{file.filename}' contains only a small amount of text "
            f"({len(stripped)} characters), which is typical of a brief award letter or cover page. "
            f"Extraction will proceed but some fields — such as the work plan, budget breakdown, "
            f"and detailed timeline — may be incomplete or missing. "
            f"For the most complete output, upload both the award letter and the original proposal together."
        )

    # Forget the raw source document immediately — its text is already
    # extracted and stored in memory; the PII file must not linger on disk.
    try:
        os.remove(filepath)
    except OSError:
        pass

    return file_id, file.filename, stripped, content_warning


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


def _llm_required() -> bool:
    """Strict mode (default ON): when AI extraction is requested, a failure
    returns an explicit HTTP error instead of silently serving regex output.
    Set LLM_REQUIRED=false to restore graceful regex-only fallback."""
    return os.getenv("LLM_REQUIRED", "true").lower() == "true"


def _raise_if_llm_unavailable(requested: bool):
    if requested and _llm_required() and not llm_service.is_available():
        raise HTTPException(
            status_code=503,
            detail=(
                "AI extraction was requested but the language model is not available "
                "(OPENAI_API_KEY missing or client failed to initialize). "
                "Fix the key configuration, or set LLM_REQUIRED=false to allow "
                "regex-only fallback."
            ),
        )


def _raise_if_llm_failed(grant_data: GrantData, requested: bool):
    if requested and _llm_required() and grant_data.extraction_method != "llm+regex":
        reason = next(
            (f for f in (grant_data.validation_flags or []) if f.lower().startswith("llm extraction failed")),
            "the model call did not complete",
        )
        raise HTTPException(
            status_code=502,
            detail=(
                f"AI extraction failed — {reason} "
                f"Fix the underlying issue, or set LLM_REQUIRED=false to allow regex-only fallback."
            ),
        )


def process_single_file(file: UploadFile, file_num: int, total_files: int, tenant_id: int) -> UploadResponse:
    file_id, filename, text, content_warning = _save_and_extract(file, "unknown")
    settings = PrivacySettings()

    # Auto-classify the document (proposal vs award letter vs combined) instead of
    # assuming. This routes the text correctly so the award letter stays authoritative.
    doc_kind = llm_service.classify_document(text)
    source_documents = [SourceDocument(file_id=file_id, filename=filename, document_type=doc_kind)]

    proposal_text = text if doc_kind in ("proposal", "combined") else None
    # Treat an award letter, a combined doc, OR an unknown single upload as the
    # authoritative award text so disambiguation rules apply.
    award_text = text if doc_kind in ("award_letter", "combined", "unknown") else None

    redacted_text, redactions = privacy_service.redact_text(text, settings)
    redacted_award_text = None
    if award_text:
        redacted_award_text, _ = privacy_service.redact_text(award_text, settings)

    grant_data = local_extraction_service.extract(
        text,                # Extract from raw text so redaction never hides amounts/names
        source_documents=source_documents,
        proposal_text=proposal_text,
        award_letter_text=award_text,
        privacy_settings=settings,
    )
    grant_data.redacted_text = redacted_text
    grant_data.redactions = redactions

    _raise_if_llm_unavailable(settings.enable_external_llm)
    use_external_llm = settings.enable_external_llm and llm_service.is_available()
    grant_data.transmission_preview = privacy_service.build_transmission_preview(
        text,
        redacted_text,
        structured_fields_count=8,
        external_llm_enabled=use_external_llm,
    )

    if use_external_llm:
        grant_data = llm_service.enrich_grant_data(
            grant_data,
            sanitized_text=redacted_text,
            source_documents=source_documents,
            award_text=redacted_award_text,
        )
        _raise_if_llm_failed(grant_data, settings.enable_external_llm)
    else:
        # Always run validators even without an LLM so the reviewer is warned.
        grant_data = llm_service.validate_only(
            grant_data, award_text=redacted_award_text, sanitized_text=redacted_text,
        )

    grant_data_store[file_id] = grant_data
    grant_tenant[file_id] = tenant_id
    _touch(file_id)
    return UploadResponse(
        success=True,
        message="File uploaded and processed successfully",
        file_id=file_id,
        filename=filename,
        document_type=grant_data.document_type,
        content_warning=content_warning,
    )


@router.post("/upload", response_model=List[UploadResponse])
def upload_grant_letters(files: List[UploadFile] = File(...), user: User = Depends(get_current_user)):
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")
    if len(files) > 10:
        raise HTTPException(status_code=400, detail="Maximum 10 files allowed per upload")

    results: List[UploadResponse] = []
    for idx, file in enumerate(files, 1):
        try:
            results.append(process_single_file(file, idx, len(files), user.tenant_id))
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
def upload_grant_package(
    proposal: Optional[UploadFile] = File(None),
    award_letter: Optional[UploadFile] = File(None),
    redact_names: bool = Form(True),
    redact_salaries: bool = Form(True),
    redact_contact_details: bool = Form(True),
    enable_external_llm: bool = Form(True),
    user: User = Depends(get_current_user),
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

    content_warnings: List[str] = []

    if proposal:
        proposal_file_id, proposal_filename, proposal_text, w = _save_and_extract(proposal, "proposal")
        if w:
            content_warnings.append(w)
        proposal_kind = llm_service.classify_document(proposal_text) if proposal_text else "proposal"
        source_documents.append(SourceDocument(file_id=proposal_file_id, filename=proposal_filename, document_type="proposal"))

    if award_letter:
        award_file_id, award_filename, award_text, w = _save_and_extract(award_letter, "award_letter")
        if w:
            content_warnings.append(w)
        award_kind = llm_service.classify_document(award_text) if award_text else "award_letter"
        source_documents.append(SourceDocument(file_id=award_file_id, filename=award_filename, document_type="award_letter"))

    package_id = generate_file_id()
    merged_text_parts = []
    if proposal_text:
        merged_text_parts.append(f"[PROPOSAL]\n{proposal_text}")
    if award_text:
        merged_text_parts.append(f"[AWARD LETTER]\n{award_text}")
    merged_text = "\n\n".join(merged_text_parts)

    redacted_text, redactions = privacy_service.redact_text(merged_text, privacy_settings)
    # Also redact award letter in isolation so the LLM gets a clean authoritative section
    redacted_award_text: Optional[str] = None
    if award_text:
        redacted_award_text, _ = privacy_service.redact_text(award_text, privacy_settings)
    grant_data = local_extraction_service.extract(
        merged_text,         # Always extract from raw text so redaction never hides amounts or names
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

    _raise_if_llm_unavailable(privacy_settings.enable_external_llm)
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
            award_text=redacted_award_text,
        )
        _raise_if_llm_failed(grant_data, privacy_settings.enable_external_llm)
    else:
        # Always run validators even without an LLM so the reviewer is warned.
        grant_data = llm_service.validate_only(
            grant_data, award_text=redacted_award_text, sanitized_text=redacted_text,
        )

    grant_data_store[package_id] = grant_data
    grant_tenant[package_id] = user.tenant_id
    _touch(package_id)

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
        content_warnings=content_warnings,
    )


@router.get("/data/{file_id}")
async def get_grant_data(file_id: str, user: User = Depends(get_current_user)):
    _check_access(file_id, user)
    if file_id not in grant_data_store:
        raise HTTPException(status_code=404, detail="Grant data not found")
    _touch(file_id)
    return grant_data_store[file_id]


@router.get("/list")
async def list_grants(user: User = Depends(get_current_user)):
    grants = []
    for file_id, grant_data in grant_data_store.items():
        if grant_tenant.get(file_id) != user.tenant_id:
            continue
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
def generate_documents(file_id: str, request: GenerateDocumentsRequest, user: User = Depends(get_current_user)):
    _check_access(file_id, user)
    if file_id not in grant_data_store:
        raise HTTPException(status_code=404, detail="Grant data not found")

    grant_data = grant_data_store[file_id]
    _touch(file_id)
    options = {
        "generate_workplan": request.generate_workplan,
        "generate_budget": request.generate_budget,
        "generate_report_template": request.generate_report_template,
        "generate_calendar": request.generate_calendar,
        "generate_agenda_template": request.generate_agenda_template,
        "generate_summary": request.generate_summary,
        "generate_meeting_calendar": request.generate_meeting_calendar,
        "generate_disbursement_calendar": request.generate_disbursement_calendar,
        "generate_reporting_calendar": request.generate_reporting_calendar,
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
async def download_document(file_id: str, doc_type: str, user: User = Depends(get_current_user)):
    _check_access(file_id, user)
    extensions = {
        "workplan": ".pdf",
        "budget": ".xlsx",
        "report": ".docx",
        "agenda": ".docx",
        "summary": ".docx",
        "meeting_calendar": ".ics",
        "disbursement_calendar": ".ics",
        "reporting_calendar": ".ics",
        # legacy single-calendar key kept for backward compat
        "calendar": ".ics",
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
async def delete_grant(file_id: str, user: User = Depends(get_current_user)):
    """Explicit 'forget now' — erase this grant and its generated files immediately."""
    _check_access(file_id, user)
    if file_id not in grant_data_store:
        raise HTTPException(status_code=404, detail="Grant data not found")
    _forget(file_id)  # removes in-memory records + generated files on disk
    return {"success": True, "message": "Grant deleted"}
